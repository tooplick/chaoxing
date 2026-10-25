# -*- coding: utf-8 -*-
"""REST + SSE 路由层."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

from flask import Blueprint, Response, jsonify, request, session

from web.auth import AuthManager
from web.config_gen import ConfigError, sanitize_params, validate_tiku, write_config
from web.runner import PROJECT_ROOT, RunManager
from web.store import Store

bp = Blueprint("api", __name__, url_prefix="/api")

_store: Store | None = None
_auth: AuthManager | None = None
_runner: RunManager | None = None


def init_deps(store: Store, auth: AuthManager, runner: RunManager) -> None:
    global _store, _auth, _runner
    _store, _auth, _runner = store, auth, runner


# ---------- 鉴权门 ----------
@bp.before_request
def auth_gate():
    if request.path.startswith("/api/auth/"):
        return None
    if not session.get("admin"):
        return jsonify({"error": "unauthorized"}), 401
    return None


@bp.errorhandler(ConfigError)
def handle_config_error(exc):
    return jsonify({"error": str(exc)}), 400


# ---------- 管理员认证 ----------
@bp.get("/auth/state")
def auth_state():
    return jsonify({"initialized": _auth.is_initialized(), "logged_in": bool(session.get("admin"))})


@bp.post("/auth/setup")
def auth_setup():
    if _auth.is_initialized():
        return jsonify({"error": "管理员口令已设置"}), 400
    password = (request.get_json(silent=True) or {}).get("password", "")
    try:
        _auth.setup(password)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    session["admin"] = True
    session.permanent = True
    return jsonify({"ok": True})


@bp.post("/auth/login")
def auth_login():
    ip = request.remote_addr or "?"
    wait = _auth.check_rate_limit(ip)
    if wait:
        return jsonify({"error": f"尝试过于频繁, 请 {wait} 秒后再试"}), 429
    if not _auth.is_initialized():
        return jsonify({"error": "管理员口令未初始化, 请先设置口令"}), 400
    password = (request.get_json(silent=True) or {}).get("password", "")
    if _auth.verify(password):
        _auth.record_success(ip)
        session["admin"] = True
        session.permanent = True
        return jsonify({"ok": True})
    _auth.record_failure(ip)
    return jsonify({"error": "口令错误"}), 401


@bp.post("/auth/logout")
def auth_logout():
    session.pop("admin", None)
    return jsonify({"ok": True})


# ---------- 账号管理 ----------
@bp.get("/accounts")
def list_accounts():
    return jsonify({"accounts": _store.list_accounts()})


@bp.post("/accounts")
def create_account():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    if not username:
        return jsonify({"error": "手机号不能为空"}), 400
    email = str(data.get("email", "") or "").strip()
    if email and "@" not in email:
        return jsonify({"error": "邮箱格式无效"}), 400
    account = _store.create_account(
        label=str(data.get("label", "")),
        username=username,
        password=str(data.get("password", "") or ""),
        cookies=str(data.get("cookies", "") or ""),
        email=email,
    )
    return jsonify({"ok": True, "account": account})


@bp.put("/accounts/<account_id>")
def update_account(account_id):
    if not _store.get_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    data = request.get_json(silent=True) or {}
    fields = {}
    for key in ("label", "username", "password", "email", "course_ids"):
        if key in data and data[key] is not None:
            fields[key] = data[key]
    if "email" in fields:
        email = str(fields["email"]).strip()
        if email and "@" not in email:
            return jsonify({"error": "邮箱格式无效"}), 400
        fields["email"] = email
    if "params" in data and data["params"] is not None:
        fields["params"] = {**(_store.get_account(account_id).get("params") or {}),
                            **sanitize_params(data["params"])}
    account = _store.update_account(account_id, fields)
    if data.get("cookies"):
        _store.write_cookies(account_id, str(data["cookies"]))
    return jsonify({"ok": True, "account": account})


@bp.delete("/accounts/<account_id>")
def delete_account(account_id):
    if _runner.is_running(account_id):
        return jsonify({"error": "该账号有任务正在运行, 请先停止"}), 409
    if not _store.delete_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    return jsonify({"ok": True})


# ---------- 子进程查询 ----------
def _run_cli(cli_args: list[str], account_dir: str, timeout: int) -> dict:
    """拉起 web.cli 子进程, 解析 stdout 末行 JSON; 失败时抛 RuntimeError."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [sys.executable, "-u", "-m", "web.cli", *cli_args],
            cwd=account_dir, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"查询超时({timeout}s), 请稍后重试") from None
    stdout_lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    result = None
    if stdout_lines:
        try:
            result = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            result = None
    if result is None:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError("查询失败: " + (" | ".join(tail) or f"退出码 {proc.returncode}"))
    return result


@bp.post("/accounts/<account_id>/test")
def test_account(account_id):
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404
    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    result = _run_cli(["login-test", "--config", config_path], account_dir, timeout=90)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


# 课程列表缓存: {account_id: (fetched_at, result)}; 拉取慢(子进程+登录+多页请求), 缓存换体验
_COURSES_CACHE_TTL = 600
_courses_cache: dict[str, tuple[float, dict]] = {}


@bp.get("/accounts/<account_id>/courses")
def account_courses(account_id):
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404
    refresh = request.args.get("refresh") == "1"

    account_dir = _store.account_dir(account_id)
    cache_file = os.path.join(account_dir, "courses.json")
    if not refresh:
        cached = _courses_cache.get(account_id)
        if cached and time.time() - cached[0] < _COURSES_CACHE_TTL:
            return jsonify(cached[1])
        # 服务重启后尝试上次落盘的结果(可能过期, 但能让对话框秒开, 前端可点刷新)
        if cached is None and os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    stale = json.load(f)
                return jsonify(stale)
            except (json.JSONDecodeError, OSError):
                pass

    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    result = _run_cli(["courses", "--config", config_path], account_dir, timeout=120)
    if result.get("ok"):
        result["fetched_at"] = time.time()
        _courses_cache[account_id] = (time.time(), result)
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False)
        except OSError:
            pass
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


# ---------- 任务运行 ----------
@bp.post("/accounts/<account_id>/start")
def start_task(account_id):
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404
    if _runner.is_running(account_id):
        return jsonify({"error": "该账号已有任务在运行"}), 409

    data = request.get_json(silent=True) or {}
    course_ids = [str(c).strip() for c in data.get("course_ids", []) if str(c).strip()]
    if not course_ids:
        return jsonify({"error": "请至少选择一门课程"}), 400

    merged = {**(account.get("params") or {}), **(data.get("params") or {})}
    params = sanitize_params(merged)
    tiku = _store.get_tiku()
    providers = validate_tiku(tiku)  # ConfigError -> 400 (含 TikuManual 拒绝)

    if not account.get("password"):
        cookies_path = os.path.join(_store.account_dir(account_id), "cookies.txt")
        if not (os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0):
            return jsonify({"error": "该账号未配置密码, 也无可用 cookies"}), 400

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "config.ini")
    write_config(config_path, account, course_ids, params, tiku, _store.get_notification())
    # 大模型连通性检查已前移到刷课对话框的「检查题库」按钮, 启动流程不再阻塞

    # 章节总数用于进度百分比, 前端从课程列表带回 id:clazz:cpi; 失败仅降级为无百分比
    total = None
    chapters_courses = [str(c).strip() for c in data.get("chapters_courses", []) if str(c).strip()]
    if chapters_courses:
        try:
            plan = _run_cli(
                ["chapters", "--config", config_path, "--courses", ",".join(chapters_courses)],
                account_dir, timeout=60,
            )
            if plan.get("ok"):
                total = plan.get("total")
        except RuntimeError:
            total = None

    _runner.start(account_id, config_path, account_dir, total=total)

    # 记住本次课程选择; 参数按需保存为账号默认
    updates = {"course_ids": course_ids}
    if data.get("save_default"):
        updates["params"] = params
    _store.update_account(account_id, updates)
    return jsonify({"ok": True})


@bp.post("/accounts/<account_id>/stop")
def stop_task(account_id):
    if not _store.get_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    if not _runner.stop(account_id):
        return jsonify({"error": "该账号没有正在运行的任务"}), 400
    return jsonify({"ok": True})


@bp.post("/accounts/<account_id>/restart")
def restart_task(account_id):
    """一键重启: 停止运行中的任务并立即用记忆的课程选择与参数重新启动."""
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404

    if _runner.is_running(account_id):
        _runner.stop(account_id)
        if not _runner.wait_stopped(account_id, timeout=30):
            return jsonify({"error": "停止超时, 请稍后手动启动"}), 409

    course_ids = account.get("course_ids") or []
    if not course_ids:
        return jsonify({"error": "该账号还没有记忆的课程选择, 请先点「刷课」发起一次"}), 400

    params = sanitize_params(account.get("params") or {})
    tiku = _store.get_tiku()
    validate_tiku(tiku)

    if not account.get("password"):
        cookies_path = os.path.join(_store.account_dir(account_id), "cookies.txt")
        if not (os.path.exists(cookies_path) and os.path.getsize(cookies_path) > 0):
            return jsonify({"error": "该账号未配置密码, 也无可用 cookies"}), 400

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "config.ini")
    write_config(config_path, account, course_ids, params, tiku, _store.get_notification())
    # 重启跳过大模型预检: 首次启动时已校验过, 中途重启不应被阻塞
    _runner.start(account_id, config_path, account_dir, total=None)
    return jsonify({"ok": True})


@bp.post("/stop-all")
def stop_all():
    return jsonify({"ok": True, "stopped": _runner.stop_all()})


@bp.get("/status")
def status():
    accounts = []
    for account in _store.list_accounts():
        run = _runner.get_run(account["id"])
        item = {
            "id": account["id"],
            "label": account["label"],
            "username": account["username"],
            "state": "idle",
        }
        if run:
            item.update(run.snapshot())
            _maybe_diagnose_block(account, run)
        accounts.append(item)
    return jsonify({"accounts": accounts, "server_time": time.time()})


def _diagnose_course_arg(account_id: str) -> str | None:
    """从课程缓存中拼出 face-check 需要的 courseId:clazzId:cpi."""
    course_id = None
    account = _store.get_account(account_id)
    if account:
        course_id = (account.get("course_ids") or [""])[0]
    cache_file = os.path.join(_store.account_dir(account_id), "courses.json")
    if not course_id or not os.path.exists(cache_file):
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cached = json.load(f)
        meta = next((c for c in cached.get("courses", []) if c.get("courseId") == course_id), None)
        if meta:
            return f"{meta['courseId']}:{meta['clazzId']}:{meta['cpi']}"
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _maybe_diagnose_block(account: dict, run) -> None:
    """needs_attention 且未判别时, 后台跑一次 face-check 区分人脸抓拍/风控冷却."""
    if not run.needs_attention or run.diagnosed or run.diagnosing:
        return
    with run.lock:
        if run.diagnosing or run.diagnosed:
            return
        run.diagnosing = True

    def worker():
        account_id = account["id"]
        try:
            course_arg = _diagnose_course_arg(account_id)
            if not course_arg:
                run.blocked_reason = None  # 无法判别, 前端显示通用提示
                return
            account_dir = _store.account_dir(account_id)
            config_path = os.path.join(account_dir, "login-test.ini")
            write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
            cli_args = ["face-check", "--config", config_path, "--course", course_arg]
            if run.current_chapter:
                cli_args += ["--chapter-title", run.current_chapter]
            result = _run_cli(cli_args, account_dir, timeout=90)
            run.blocked_reason = "face" if result.get("face_required") else "cooldown"
        except Exception:
            run.blocked_reason = None  # 判别失败保持未知, 前端显示通用提示
        finally:
            run.diagnosed = True
            run.diagnosing = False
            # 判别结果邮件通知(账号绑定了邮箱且配置了 SMTP 时)
            _notify_by_email(account, run)

    threading.Thread(target=worker, daemon=True, name=f"diagnose-{account['id']}").start()


def _notify_by_email(account: dict, run) -> None:
    """按 blocked_reason 发送判别结果邮件; 配置缺失时静默跳过."""
    from web.emailer import resolve_cfg, send_async

    cfg = resolve_cfg(_store)
    if not cfg:
        return
    to = str(account.get("email", "") or "").strip()
    if not to:
        return
    label = account.get("label", "")
    reason = run.blocked_reason
    if reason == "face":
        subject = f"【刷课平台】{label} 需要人脸采集"
        body = (
            f"账号「{label}」({account.get('username', '')}) 的任务因人脸抓拍被自动停止。\n\n"
            f"触发章节: {run.current_chapter or '未知'}\n"
            "处理方式: 打开刷课面板, 点该账号的「人脸」按钮获取二维码, "
            "用登录此账号的学习通App扫码完成人脸采集, 然后点「重启」继续。\n\n"
            "— chaoxing 多账号刷课平台"
        )
    elif reason == "cooldown":
        subject = f"【刷课平台】{label} 风控冷却中"
        body = (
            f"账号「{label}」({account.get('username', '')}) 的任务被风控拦截自动停止(无需人脸)。\n\n"
            "处理方式: 等待 30-60 分钟后再到面板点「重启」, 期间不要反复启动。\n\n"
            "— chaoxing 多账号刷课平台"
        )
    else:
        return
    send_async(cfg, to, subject, body)


@bp.get("/accounts/<account_id>/logs/tail")
def account_logs_tail(account_id):
    """日志缓冲快照(非流式), 供账号行展开详情使用."""
    if not _store.get_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    try:
        limit = min(200, max(10, int(request.args.get("limit", 50))))
    except ValueError:
        limit = 50
    run = _runner.get_run(account_id)
    lines = []
    if run:
        with run.lock:
            lines = [{"seq": seq, "text": text} for seq, text in list(run.lines)[-limit:]]
    return jsonify({"lines": lines})


@bp.get("/accounts/<account_id>/logs")
def account_logs(account_id):
    if not _store.get_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    try:
        after = int(request.args.get("after", 0))
    except ValueError:
        after = 0

    def generate():
        last_seq = after
        idle_seconds = 0.0
        while True:
            lines = []
            run = _runner.get_run(account_id)
            if run:
                lines = run.lines_after(last_seq)
            if lines:
                for seq, text in lines:
                    last_seq = seq
                    yield f"id: {seq}\ndata: {json.dumps(text, ensure_ascii=False)}\n\n"
                idle_seconds = 0.0
            elif run and run.state in ("finished", "stopped", "error"):
                # 回放完缓冲且运行已结束, 通知前端关闭连接
                yield "event: end\ndata: {}\n\n"
                return
            else:
                idle_seconds += 0.4
            if idle_seconds > 1800:  # 30 分钟无输出则断开, EventSource 会自动重连
                return
            time.sleep(0.4)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


# 章节树缓存: {(account_id, course_ids_key): (ts, tree)}; 章节结构基本静态, 1 小时
_chapter_tree_cache: dict[str, tuple[float, dict]] = {}
_CHAPTER_TREE_TTL = 3600


@bp.get("/accounts/<account_id>/chapter-tree")
def chapter_tree(account_id):
    """账号所记课程的章节树(含每章完成状态), 供行展开详情展示."""
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404

    course_ids = account.get("course_ids") or []
    if not course_ids:
        return jsonify({"error": "该账号还没有记忆的课程选择"}), 400
    with_jobs = request.args.get("jobs") == "1"
    cache_key = f"{account_id}:{','.join(course_ids)}:{'jobs' if with_jobs else 'plain'}"
    if request.args.get("refresh") == "1":
        _chapter_tree_cache.pop(cache_key, None)
    cached = _chapter_tree_cache.get(cache_key)
    if cached and time.time() - cached[0] < (_CHAPTER_JOBS_TTL if with_jobs else _CHAPTER_TREE_TTL):
        return jsonify(cached[1])

    # 从课程缓存拼 courseId:clazzId:cpi, 同时记录课程名供章节树展示
    course_args = []
    course_titles: dict[str, str] = {}
    cache_file = os.path.join(_store.account_dir(account_id), "courses.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_courses = json.load(f)
            for meta in cached_courses.get("courses", []):
                if meta.get("courseId") in course_ids:
                    course_args.append(f"{meta['courseId']}:{meta['clazzId']}:{meta['cpi']}")
                    course_titles[meta["courseId"]] = meta.get("title", "")
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    if not course_args:
        return jsonify({"error": "课程缓存中没有这些课程, 请先刷新课程列表"}), 400

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    cli_args = ["chapter-tree", "--config", config_path, "--courses", ",".join(course_args)]
    if with_jobs:
        cli_args.append("--with-jobs")
    result = _run_cli(cli_args, account_dir, timeout=300 if with_jobs else 120)
    if result.get("ok"):
        for course in result.get("courses", []):
            course["title"] = course_titles.get(course.get("courseId"), "")
        _chapter_tree_cache[cache_key] = (time.time(), result)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


# 章节任务点缓存: {(account_id, chapter_id): (ts, jobs)}; 完成状态会变化, 10 分钟
_chapter_jobs_cache: dict[str, tuple[float, dict]] = {}
_CHAPTER_JOBS_TTL = 600


@bp.get("/accounts/<account_id>/chapter-jobs")
def chapter_jobs(account_id):
    """单个章节的任务点列表(含已完成), 供章节树二级展开."""
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404
    chapter_id = request.args.get("chapterId", "")
    course_id = request.args.get("courseId", "")
    if not chapter_id or not course_id:
        return jsonify({"error": "缺少 chapterId / courseId"}), 400

    cache_key = f"{account_id}:{chapter_id}"
    if request.args.get("refresh") == "1":
        _chapter_jobs_cache.pop(cache_key, None)
    cached = _chapter_jobs_cache.get(cache_key)
    if cached and time.time() - cached[0] < _CHAPTER_JOBS_TTL:
        return jsonify(cached[1])

    # 从课程缓存找 clazzId/cpi
    course_arg = None
    cache_file = os.path.join(_store.account_dir(account_id), "courses.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_courses = json.load(f)
            meta = next((c for c in cached_courses.get("courses", []) if c.get("courseId") == course_id), None)
            if meta:
                course_arg = f"{meta['courseId']}:{meta['clazzId']}:{meta['cpi']}"
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    if not course_arg:
        return jsonify({"error": "课程缓存中没有该课程"}), 400

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    result = _run_cli(
        ["chapter-jobs", "--config", config_path, "--course", course_arg, "--chapter-id", chapter_id],
        account_dir, timeout=90,
    )
    if result.get("ok"):
        _chapter_jobs_cache[cache_key] = (time.time(), result)
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


# 人脸扫码轮询令牌: {account_id: status_tokens}
_face_tokens: dict[str, dict] = {}


@bp.post("/accounts/<account_id>/face-qr")
def face_qr(account_id):
    """拉取人脸采集二维码(定位当前课程中有人脸要求的任务点)."""
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404

    # 从缓存的课程列表中找出 clazzId/cpi(account.course_ids 记忆的是 courseId)
    course_id = (account.get("course_ids") or [""])[0]
    course_meta = None
    cache_file = os.path.join(_store.account_dir(account_id), "courses.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            course_meta = next(
                (c for c in cached.get("courses", []) if c.get("courseId") == course_id), None
            )
        except (json.JSONDecodeError, OSError):
            course_meta = None
    if not course_meta:
        return jsonify({"error": "没有该账号的课程缓存, 请先打开一次「刷课」对话框拉取课程"}), 400

    run = _runner.get_run(account_id)
    chapter_title = (run.current_chapter if run else "") or ""

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    cli_args = [
        "face-qr", "--config", config_path,
        "--course", f"{course_meta['courseId']}:{course_meta['clazzId']}:{course_meta['cpi']}",
    ]
    if chapter_title:
        cli_args += ["--chapter-title", chapter_title]
    result = _run_cli(cli_args, account_dir, timeout=120)
    if result.get("ok") and result.get("status_tokens"):
        _face_tokens[account_id] = result["status_tokens"]
        result.pop("status_tokens")
    # 查询结果(含"未发现人脸需求")不是请求错误, 统一 200 由前端展示原因
    return jsonify(result)


@bp.get("/accounts/<account_id>/face-status")
def face_status(account_id):
    """轮询人脸扫码状态; 完成后清除令牌."""
    if not _store.get_account(account_id):
        return jsonify({"error": "账号不存在"}), 404
    tokens = _face_tokens.get(account_id)
    if not tokens:
        return jsonify({"error": "尚未获取二维码"}), 400
    account = _store.get_account(account_id)
    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    result = _run_cli(
        ["face-status", "--config", config_path, "--tokens", json.dumps(tokens, ensure_ascii=False)],
        account_dir, timeout=60,
    )
    if result.get("done"):
        _face_tokens.pop(account_id, None)
    return jsonify(result)


@bp.post("/accounts/<account_id>/face-config")
def face_config(account_id):
    """课程级人脸抓拍配置检测(批量, 每课 2 个请求)."""
    account = _store.get_account(account_id)
    if not account:
        return jsonify({"error": "账号不存在"}), 404
    data = request.get_json(silent=True) or {}
    wanted = {str(c).strip() for c in data.get("course_ids", []) if str(c).strip()}
    if not wanted:
        return jsonify({"error": "未指定课程"}), 400

    course_args = []
    cache_file = os.path.join(_store.account_dir(account_id), "courses.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            for meta in cached.get("courses", []):
                if meta.get("courseId") in wanted:
                    course_args.append(f"{meta['courseId']}:{meta['clazzId']}:{meta['cpi']}")
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    if not course_args:
        return jsonify({"error": "课程缓存中没有这些课程, 请先刷新课程列表"}), 400

    account_dir = _store.account_dir(account_id)
    config_path = os.path.join(account_dir, "login-test.ini")
    write_config(config_path, account, [], dict(account.get("params") or {}), {}, {})
    result = _run_cli(
        ["face-config", "--config", config_path, "--courses", ",".join(course_args)],
        account_dir, timeout=120,
    )
    status = 200 if result.get("ok") else 400
    return jsonify(result), status


@bp.post("/settings/email/test")
def test_email():
    """发送测试邮件, 同步返回真实结果(配置读通知设置里的 Email 字段)."""
    from web.emailer import resolve_cfg, send_sync

    to = str((request.get_json(silent=True) or {}).get("to", "")).strip()
    if not to or "@" not in to:
        return jsonify({"ok": False, "msg": "请填写有效的收件邮箱"}), 400
    cfg = resolve_cfg(_store)
    if not cfg:
        return jsonify({"ok": False, "msg": "请先在通知服务中选择「邮件通知」并填写 SMTP 配置后保存"}), 400
    ok, msg = send_sync(cfg, to, "【刷课平台】测试邮件",
                        "这是一封来自 chaoxing 刷课平台的测试邮件, 收到即表示邮件通知配置成功。")
    return jsonify({"ok": ok, "msg": msg})


# ---------- 全局设置 ----------
@bp.get("/settings/tiku")
def get_tiku():
    return jsonify({"tiku": _store.get_tiku()})


@bp.put("/settings/tiku")
def put_tiku():
    data = request.get_json(silent=True) or {}
    tiku = data.get("tiku") or {}
    validate_tiku(tiku)
    _store.set_tiku(tiku)
    return jsonify({"ok": True})


def _write_temp_tiku_config(tiku: dict) -> str:
    """把题库配置写入临时 ini(补上题库必需键), 供 cli 子进程读取."""
    from web.config_gen import TIKU_COMMON_DEFAULTS, TIKU_PROVIDER_DEFAULTS

    lines = ["[common]", "username = test", "password = ", "[tiku]"]
    merged = {k: str(v) for k, v in tiku.items() if str(v).strip() != ""}
    providers = [p.strip() for p in merged.get("provider", "").split(",") if p.strip()]
    # 默认值仅补缺, 不能覆盖用户已填的 endpoint/key 等
    defaults = dict(TIKU_COMMON_DEFAULTS)
    for provider in providers:
        defaults.update(TIKU_PROVIDER_DEFAULTS.get(provider, {}))
    for key, value in defaults.items():
        merged.setdefault(key, value)
    lines += [f"{k} = {v}" for k, v in merged.items()]
    fd, path = tempfile.mkstemp(suffix=".ini", dir=_store.data_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


@bp.post("/settings/tiku/test")
def test_tiku():
    tiku = _store.get_tiku()
    providers = validate_tiku(tiku)
    if not providers:
        return jsonify({"ok": False, "msg": "未配置题库 provider"})
    if not ({"AI", "SiliconFlow"} & set(providers)):
        # 非大模型题库做必填字段校验
        problems = []
        if {"TikuYanxi", "TikuLike"} & set(providers) and not str(tiku.get("tokens", "")).strip():
            problems.append("言溪/LIKE 题库需要填写 tokens")
        if "TikuAdapter" in providers and not str(tiku.get("url", "")).strip():
            problems.append("TikuAdapter 需要填写 url")
        if problems:
            return jsonify({"ok": False, "msg": "; ".join(problems)})
        return jsonify({"ok": True, "msg": "字段校验通过"})
    # 大模型题库: 用临时配置真实连接一次
    tmp_path = _write_temp_tiku_config(tiku)
    try:
        result = _run_cli(["llm-check", "--config", tmp_path], _store.data_dir, timeout=60)
    finally:
        os.unlink(tmp_path)
    # 测试结果(含失败原因)不是请求错误, 统一 200 返回由前端展示
    return jsonify(result)


@bp.post("/settings/tiku/models")
def tiku_models():
    """拉取大模型端点的可用模型列表; 优先用请求体里的当前表单值(未保存也能测)."""
    data = request.get_json(silent=True) or {}
    tiku = data.get("tiku") or _store.get_tiku()
    providers = validate_tiku(tiku)
    if not ({"AI", "SiliconFlow"} & set(providers)):
        return jsonify({"error": "获取模型需要题库链包含 AI 或 SiliconFlow"}), 400
    tmp_path = _write_temp_tiku_config(tiku)
    try:
        result = _run_cli(["models", "--config", tmp_path], _store.data_dir, timeout=60)
    finally:
        os.unlink(tmp_path)
    return jsonify(result)


@bp.get("/settings/notification")
def get_notification():
    return jsonify({"notification": _store.get_notification()})


@bp.put("/settings/notification")
def put_notification():
    data = request.get_json(silent=True) or {}
    _store.set_notification(data.get("notification") or {})
    return jsonify({"ok": True})
