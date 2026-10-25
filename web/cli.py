# -*- coding: utf-8 -*-
"""Web 平台的查询子进程: 由 Flask 后端拉起, 独立进程内完成登录态操作.

用法(工作目录必须是账号目录, cookies.txt 按相对路径解析):
    python -m web.cli login-test --config <path>
    python -m web.cli courses     --config <path>
    python -m web.cli chapters    --config <path> --courses courseId:clazzId:cpi,...
    python -m web.cli llm-check   --config <path>

结果以 JSON 打印到 stdout(日志走 stderr), 供 Flask 进程解析.
"""
import argparse
import configparser
import json
import sys


def _emit(obj: dict, ok: bool = True) -> None:
    obj.setdefault("ok", ok)
    print(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def _login(config_path: str):
    """cookies 优先登录, 失效自动回退账密; 返回 (chaoxing, 结果dict)."""
    from api.base import Account, Chaoxing

    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf8")
    common = parser["common"] if parser.has_section("common") else {}
    username = common.get("username", "").strip()
    password = common.get("password", "").strip()

    import os

    has_cookies = os.path.exists("cookies.txt") and os.path.getsize("cookies.txt") > 0
    if not password and not has_cookies:
        return None, {"status": False, "msg": "未配置密码, 且账号目录下没有可用 cookies"}

    account = Account(username, password)
    chaoxing = Chaoxing(account=account)
    if has_cookies:
        result = chaoxing.login(login_with_cookies=True)
    else:
        result = chaoxing.login(login_with_cookies=False)
    return chaoxing, result


def cmd_login_test(args) -> None:
    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)
    name = ""
    try:
        name = chaoxing.get_name()
    except Exception:  # noqa: BLE001 - 姓名仅作回显
        pass
    _emit({"ok": True, "msg": "登录成功", "name": name})


def _thread_session(template) -> "requests.Session":
    """基于现有会话 cookies 构造线程独立的 Session(requests.Session 非线程安全)."""
    import requests

    from api.config import GlobalConst as gc

    sess = requests.Session()
    sess.headers.update(gc.HEADERS)
    sess.cookies.update(template.cookies.get_dict())
    return sess


def _fast_course_list(chaoxing) -> list[dict]:
    """并发版课程列表: 主列表 + 各课程文件夹并行拉取(get_course_list 为串行实现)."""
    from concurrent.futures import ThreadPoolExecutor

    from api.base import SessionManager
    from api.decode import decode_course_folder, decode_course_list

    session = SessionManager.get_session()
    url = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
    base_data = {"courseType": 1, "query": "", "superstarClass": 0}
    headers = {
        "Referer": "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans",
    }
    resp = session.post(url, headers=headers, data={**base_data, "courseFolderId": 0})
    courses = decode_course_list(resp.text)

    folders = decode_course_folder(
        session.get("https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction").text
    )
    if folders:

        def fetch(folder):
            sess = _thread_session(session)
            r = sess.post(url, data={**base_data, "courseFolderId": folder["id"]})
            return decode_course_list(r.text)

        with ThreadPoolExecutor(max_workers=4) as pool:
            for course_list in pool.map(fetch, folders):
                courses += course_list
    return courses


def cmd_courses(args) -> None:
    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)
    courses = _fast_course_list(chaoxing)
    data = [
        {
            "courseId": c.get("courseId", ""),
            "clazzId": c.get("clazzId", ""),
            "cpi": c.get("cpi", ""),
            "title": c.get("title", ""),
            "teacher": c.get("teacher", ""),
        }
        for c in courses
    ]
    _emit({"ok": True, "courses": data})


def cmd_chapters(args) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from api.base import SessionManager

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)

    items = [item.strip() for item in args.courses.split(",") if item.strip()]

    def count_chapters(item):
        course_id, clazz_id, cpi = (item.split(":") + ["", ""])[:3]
        sess = _thread_session(SessionManager.get_session())
        url = (
            "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
            f"?courseid={course_id}&clazzid={clazz_id}&cpi={cpi}&ut=s"
        )
        from api.decode import decode_course_point

        return len(decode_course_point(sess.get(url).text).get("points", []))

    with ThreadPoolExecutor(max_workers=4) as pool:
        total = sum(pool.map(count_chapters, items))
    _emit({"ok": True, "total": total})


def cmd_llm_check(args) -> None:
    from api.answer import Tiku

    parser = configparser.ConfigParser()
    parser.read(args.config, encoding="utf8")
    if not parser.has_section("tiku") or not parser.get("tiku", "provider", fallback="").strip():
        _emit({"ok": True, "msg": "未配置题库, 跳过检查"})
        return
    tiku_config = dict(parser.items("tiku"))
    tiku = Tiku.get_tiku_from_config(tiku_config, config_path=args.config)
    tiku.init_tiku()
    if tiku.check_llm_connection():
        _emit({"ok": True, "msg": "大模型连接正常"})
    else:
        _emit({"ok": False, "msg": "大模型连接检查失败"}, ok=False)
        sys.exit(1)


def _llm_client_params(args) -> tuple[str, str, str] | None:
    """从配置的题库链中解析大模型接入参数: (endpoint, key, proxy); 非大模型题库返回 None."""
    parser = configparser.ConfigParser()
    parser.read(args.config, encoding="utf8")
    tiku = dict(parser.items("tiku")) if parser.has_section("tiku") else {}
    providers = [p.strip() for p in tiku.get("provider", "").split(",") if p.strip()]
    if "AI" in providers:
        return tiku.get("endpoint", ""), tiku.get("key", ""), tiku.get("http_proxy", "")
    if "SiliconFlow" in providers:
        endpoint = tiku.get("siliconflow_endpoint", "") or "https://api.siliconflow.cn/v1"
        return endpoint, tiku.get("siliconflow_key", ""), ""
    return None


def cmd_models(args) -> None:
    """拉取大模型端点的可用模型列表 (OpenAI 兼容 /models)."""
    from openai import OpenAI
    import httpx

    params = _llm_client_params(args)
    if params is None:
        _emit({"ok": False, "msg": "题库链未包含 AI / SiliconFlow, 无法获取模型"}, ok=False)
        sys.exit(1)
    endpoint, key, proxy = params
    if not endpoint or not key:
        _emit({"ok": False, "msg": "未配置 endpoint 或 key, 请先填写并保存"}, ok=False)
        sys.exit(1)
    try:
        client = OpenAI(
            base_url=endpoint,
            api_key=key,
            http_client=httpx.Client(proxy=proxy, timeout=30) if proxy else None,
            timeout=30,
        )
        models = sorted(m.id for m in client.models.list().data)
        _emit({"ok": True, "models": models})
    except Exception as exc:  # noqa: BLE001 - 错误以 JSON 回传给 Web 层
        _emit({"ok": False, "msg": f"获取模型失败: {exc}"}, ok=False)
        sys.exit(1)


def _face_context(chaoxing, args):
    """face-qr / face-check 公共前置: 登录、章节树、enc、优先排序的章节列表."""
    from api.decode import decode_course_point

    from web.faceqr import parse_tree_enc

    session = _thread_session(__import__("api.base", fromlist=["SessionManager"]).SessionManager.get_session())
    course_id, clazz_id, cpi = (args.course.split(":") + ["", ""])[:3]
    tree = session.get(
        "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse",
        params={"courseid": course_id, "clazzid": clazz_id, "cpi": cpi, "ut": "s"},
    ).text
    tree_enc = parse_tree_enc(tree)
    if not tree_enc:
        raise RuntimeError("章节树页面未找到 enc 令牌")
    points = decode_course_point(tree).get("points", [])
    ordered = points
    if args.chapter_title:
        hits = [p for p in points if args.chapter_title and args.chapter_title in p.get("title", "")]
        if hits:
            ordered = hits + [p for p in points if p not in hits]
    return session, course_id, clazz_id, cpi, tree_enc, ordered


def cmd_face_check(args) -> None:
    """轻量判别: 课程当前是否存在待完成的人脸采集(不生成二维码)."""
    from web.faceqr import check_face_demand

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)
    try:
        session, course_id, clazz_id, cpi, tree_enc, ordered = _face_context(chaoxing, args)
        face_required, chapter = check_face_demand(
            session, tree_enc, course_id, clazz_id, cpi, ordered,
            chapter_title=args.chapter_title, limit=10,
        )
    except RuntimeError as exc:
        _emit({"ok": False, "msg": str(exc)}, ok=False)
        sys.exit(1)
    _emit({"ok": True, "face_required": face_required, "chapter": chapter})


def cmd_face_config(args) -> None:
    """课程级人脸抓拍配置检测(每课 2 个请求, 并发检查多门课程)."""
    from concurrent.futures import ThreadPoolExecutor

    from api.decode import decode_course_point

    from web.faceqr import course_face_capture, parse_tree_enc

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)

    from api.base import SessionManager

    items = [i.strip() for i in args.courses.split(",") if i.strip()]

    def check(item):
        import time

        course_id, clazz_id, cpi = (item.split(":") + ["", ""])[:3]
        sess = _thread_session(SessionManager.get_session())
        # 同会话并发请求会被服务端返回降级页(实测 145KB->35KB), 必须串行
        for attempt in range(2):
            try:
                r = sess.get(
                    "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse",
                    params={"courseid": course_id, "clazzid": clazz_id, "cpi": cpi, "ut": "s"},
                    timeout=30,
                )
                tree_enc = parse_tree_enc(r.text)
                if tree_enc:
                    points = decode_course_point(r.text).get("points", [])
                    return {
                        "courseId": course_id,
                        "face_capture": course_face_capture(sess, course_id, clazz_id, cpi, points, tree_enc),
                    }
            except Exception:  # noqa: BLE001 - 重试后仍失败则返回不可判定
                pass
            time.sleep(1.0)
        print(f"face-config: 课程 {course_id} 多次未取得章节树", file=sys.stderr)
        return {"courseId": course_id, "face_capture": None}

    results = [check(item) for item in items]
    _emit({"ok": True, "results": results})


def cmd_chapter_tree(args) -> None:
    """按课程拉取章节树(含完成状态), 多课程串行(同会话并发会被降级).

    --with-jobs: 批量预取每章任务点(num=0/1 两页, 覆盖绝大多数章节),
    供前端一次拉全量后本地展开; 耗时约每章 1-2 个请求.
    """
    import time as _time

    from api.decode import decode_course_point

    from web.faceqr import parse_tree_enc

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)

    session = _thread_session(__import__("api.base", fromlist=["SessionManager"]).SessionManager.get_session())
    items = [i.strip() for i in args.courses.split(",") if i.strip()]
    courses_out = []
    for item in items:
        course_id, clazz_id, cpi = (item.split(":") + ["", ""])[:3]
        for attempt in range(2):
            try:
                r = session.get(
                    "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse",
                    params={"courseid": course_id, "clazzid": clazz_id, "cpi": cpi, "ut": "s"},
                    timeout=30,
                )
                tree_enc = parse_tree_enc(r.text)
                if tree_enc:
                    points = decode_course_point(r.text).get("points", [])
                    chapters = [
                        {"id": p.get("id", ""), "title": p.get("title", ""),
                         "done": bool(p.get("has_finished"))}
                        for p in points
                    ]
                    if getattr(args, "with_jobs", False):
                        for ch, p in zip(chapters, points):
                            ch["jobs"] = _collect_card_jobs(session, {
                                "clazzid": clazz_id, "courseid": course_id,
                                "knowledgeid": p.get("id", ""),
                                "ut": "s", "cpi": cpi, "v": "2025-0424-1038", "mooc2": 1,
                            }, nums="01")
                    courses_out.append({"courseId": course_id, "chapters": chapters})
                    break
            except Exception:  # noqa: BLE001
                pass
            _time.sleep(1.0)
    _emit({"ok": True, "courses": courses_out})


def _collect_card_jobs(session, params: dict, nums: str = "0123456") -> list:
    """解析章节卡片页的全部任务点(含已完成), 供章节树/单章查询共用."""
    import json as _json
    import re as _re

    jobs, seen = [], set()
    for num in nums:
        params["num"] = num
        html = session.get("https://mooc1.chaoxing.com/mooc-ans/knowledge/cards", params=params, timeout=30).text
        for fragment in _re.findall(r"mArg=\{(.*?)\};", html.replace(" ", "")):
            try:
                data = _json.loads("{" + fragment + "}")
            except Exception:  # noqa: BLE001
                continue
            for card in data.get("attachments", []):
                key = str(card.get("jobid") or card.get("id") or card.get("objectId") or card.get("name", ""))
                if not key or key in seen:
                    continue
                seen.add(key)
                prop = card.get("property", {}) or {}
                jobs.append({
                    "type": card.get("type", ""),
                    "name": prop.get("name") or prop.get("title") or card.get("name", ""),
                    "done": bool(card.get("isPassed")),
                })
    return jobs


def cmd_chapter_jobs(args) -> None:
    """拉取单个章节的全部任务点(含已完成), 供章节树二级展开."""
    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)

    session = _thread_session(__import__("api.base", fromlist=["SessionManager"]).SessionManager.get_session())
    course_id, clazz_id, cpi = (args.course.split(":") + ["", ""])[:3]
    params = {
        "clazzid": clazz_id, "courseid": course_id, "knowledgeid": args.chapter_id,
        "ut": "s", "cpi": cpi, "v": "2025-0424-1038", "mooc2": 1,
    }
    _emit({"ok": True, "jobs": _collect_card_jobs(session, params)})


def cmd_face_qr(args) -> None:
    """获取人脸采集二维码(自动在课程章节中定位有人脸要求的视频任务点)."""
    from web.faceqr import fetch_study_html, fill_tokens_from_job, has_face_demand, parse_study_tokens, produce_face_qr

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)

    session, course_id, clazz_id, cpi, tree_enc, ordered = _face_context(chaoxing, args)

    course_dict = {"courseId": course_id, "clazzId": clazz_id, "cpi": cpi, "title": ""}
    for point in ordered[:50]:
        study_html = fetch_study_html(session, course_id, clazz_id, cpi, point["id"], tree_enc)
        if not has_face_demand(study_html):
            continue
        tokens = parse_study_tokens(study_html)
        if not tokens:
            continue
        # 服务端 HTML 中 videoJobId 等为空(网页由 JS 填充), 从任务卡片补全
        try:
            jobs, _ = chaoxing.get_job_list(course_dict, point)
        except Exception as exc:  # noqa: BLE001 - 单章失败继续扫描
            print(f"get_job_list failed: {exc}", file=sys.stderr)
            continue
        video_job = next((j for j in jobs if j.get("type") == "video"), None)
        if not video_job:
            continue
        tokens = fill_tokens_from_job(tokens, video_job, point["id"])
        payload = produce_face_qr(session, tokens)
        _emit({
            "ok": True,
            "chapter": point.get("title", ""),
            "qr_base64": payload["qr_base64"],
            "status_tokens": payload["status_tokens"],
        })
        return
    _emit({"ok": False, "msg": "未在课程章节中发现待完成的人脸采集(可能已解除或未触发)"}, ok=False)


def cmd_face_status(args) -> None:
    """轮询人脸扫码状态(202/有结果视为完成)."""
    import json

    from web.faceqr import poll_face_status

    chaoxing, result = _login(args.config)
    if chaoxing is None or not result.get("status"):
        _emit({"ok": False, "msg": result.get("msg", "登录失败")}, ok=False)
        sys.exit(1)
    try:
        tokens = json.loads(args.tokens)
    except json.JSONDecodeError:
        _emit({"ok": False, "msg": "tokens 参数非法"}, ok=False)
        sys.exit(1)
    session = _thread_session(__import__("api.base", fromlist=["SessionManager"]).SessionManager.get_session())
    state = poll_face_status(session, tokens)
    _emit({"ok": True, **state})


def main() -> None:
    parser = argparse.ArgumentParser(prog="web.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("login-test", "courses", "llm-check", "models"):
        p = sub.add_parser(name)
        p.add_argument("--config", required=True)

    p = sub.add_parser("chapters")
    p.add_argument("--config", required=True)
    p.add_argument("--courses", required=True, help="courseId:clazzId:cpi 逗号分隔")

    p = sub.add_parser("face-qr")
    p.add_argument("--config", required=True)
    p.add_argument("--course", required=True, help="courseId:clazzId:cpi")
    p.add_argument("--chapter-title", default="", help="优先匹配的章节标题(运行中被拦截的章节)")

    p = sub.add_parser("face-check")
    p.add_argument("--config", required=True)
    p.add_argument("--course", required=True, help="courseId:clazzId:cpi")
    p.add_argument("--chapter-title", default="", help="优先匹配的章节标题(运行中被拦截的章节)")

    p = sub.add_parser("face-config")
    p.add_argument("--config", required=True)
    p.add_argument("--courses", required=True, help="courseId:clazzId:cpi 逗号分隔")

    p = sub.add_parser("chapter-tree")
    p.add_argument("--config", required=True)
    p.add_argument("--courses", required=True, help="courseId:clazzId:cpi 逗号分隔")
    p.add_argument("--with-jobs", action="store_true", help="批量预取每章任务点")

    p = sub.add_parser("chapter-jobs")
    p.add_argument("--config", required=True)
    p.add_argument("--course", required=True, help="courseId:clazzId:cpi")
    p.add_argument("--chapter-id", required=True)

    p = sub.add_parser("face-status")
    p.add_argument("--config", required=True)
    p.add_argument("--tokens", required=True, help="face-qr 返回的 status_tokens JSON")

    args = parser.parse_args()
    handlers = {
        "login-test": cmd_login_test,
        "courses": cmd_courses,
        "chapters": cmd_chapters,
        "llm-check": cmd_llm_check,
        "models": cmd_models,
        "face-qr": cmd_face_qr,
        "face-check": cmd_face_check,
        "face-config": cmd_face_config,
        "chapter-tree": cmd_chapter_tree,
        "chapter-jobs": cmd_chapter_jobs,
        "face-status": cmd_face_status,
    }
    try:
        handlers[args.command](args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - 错误以 JSON 回传给 Web 层
        _emit({"ok": False, "msg": f"{type(exc).__name__}: {exc}"}, ok=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
