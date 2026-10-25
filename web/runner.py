# -*- coding: utf-8 -*-
"""子进程池管理: 每个学习通账号一个 main.py 子进程, 进程级隔离登录会话单例."""
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime

from web.store import Store

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PY = os.path.join(PROJECT_ROOT, "main.py")

LOG_BUFFER_SIZE = 2000

# loguru 控制台输出带 ANSI 颜色码, 进日志缓冲前剥掉, 前端按级别重新着色
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# tqdm 进度条行, 形如 "video.mp4:  58%|█████▊ | 02:35/04:27"
# 不进日志缓冲, 解析后作为结构化状态暴露给前端
_BAR_RE = re.compile(r"^(?P<name>.+?):\s*(?P<pct>\d+)%\|.*\|\s*(?P<pos>[\d:]+)/(?P<total>[\d:]+)")
_RE_CHAPTER = re.compile(r"当前章节: (.+)")
_RE_TASK_SUCCESS = re.compile(r"Task success: .+ - .+")
_RE_TASK_FAIL = re.compile(r"任务重试次数达到上限")
_RE_COURSE = re.compile(r"(?:开始学习课程|正在读取课程章节): (.+)")
# "开始任务: xxx.mp4, 总时长: 267s, 已进行: 0s" -> 提取文件名与总时长(含尾部已进行)
_RE_VIDEO_START = re.compile(r"开始任务: (.+?), 总时长: (\d+)s(?:, 已进行: \d+s)?")
# 403 行携带被拦任务点: "出现403报错... jobid=1599..., objectId=1676a..."
_RE_BLOCK_JOB = re.compile(r"出现403报错.*?jobid=(\w+)(?:, objectId=(\w+))?")


class AccountRun:
    """一个账号一次运行的进程句柄与状态."""

    def __init__(self, account_id: str):
        self.account_id = account_id
        self.lock = threading.Lock()
        self.lines: deque[tuple[int, str]] = deque(maxlen=LOG_BUFFER_SIZE)
        self.seq = 0
        # starting -> running -> finished | stopped | error
        self.state = "starting"
        self.process: subprocess.Popen | None = None
        self.stopping = False
        # Windows Job Object 句柄, 持有引用使其保持打开(父进程退出时子进程随之终止)
        self._job = None
        # 连续 403 风控拦截计数, 达阈值自动停任务避免加深风控
        self.block_hits = 0
        self.auto_stopped = False
        self.end_announced = False
        # 需要人工处理(人脸核验等), 前端据此弹提醒
        self.needs_attention = False
        # 拦截原因判别: None(待判别/未知) | "face"(人脸采集) | "cooldown"(风控冷却)
        self.blocked_reason: str | None = None
        # 被 403 拦截的任务点 {jobid, objectid}, 供人脸二维码直接定位
        self.blocked_job: dict | None = None
        self.diagnosed = False
        self.diagnosing = False
        # 各并发视频的实时观看进度 {视频名: {percent,pos,total,updated}}
        self.video_progress: dict[str, dict] = {}
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self.finished_at: str | None = None
        self.exit_code: int | None = None
        self.error: str | None = None
        self.current_course = ""
        self.current_chapter = ""
        self.completed = 0
        self.failed = 0
        self.total: int | None = None

    def append(self, text: str) -> None:
        with self.lock:
            self.seq += 1
            self.lines.append((self.seq, text))

    def lines_after(self, after_seq: int) -> list[tuple[int, str]]:
        with self.lock:
            return [(seq, text) for seq, text in self.lines if seq > after_seq]

    def snapshot(self) -> dict:
        with self.lock:
            # 按更新时间倒序取最近活跃的几个视频
            names_by_update = sorted(
                self.video_progress, key=lambda n: self.video_progress[n]["updated"], reverse=True
            )
            videos = [
                {"name": n, **{k: v for k, v in self.video_progress[n].items() if k != "updated"}}
                for n in names_by_update[:4]
            ]
            return {
                "state": self.state,
                "needs_attention": self.needs_attention,
                "blocked_reason": self.blocked_reason,
                "blocked_job": self.blocked_job,
                "videos": videos,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "exit_code": self.exit_code,
                "error": self.error,
                "current_course": self.current_course,
                "current_chapter": self.current_chapter,
                "completed": self.completed,
                "failed": self.failed,
                "total": self.total,
            }

    def _ingest(self, raw: bytes) -> None:
        """解码一行子进程输出, 处理 tqdm 的 \\r 刷新行, 记录并解析进度."""
        text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        # tqdm 进度条用 \r 原地刷新, 只保留最后一段
        if "\r" in text:
            text = text.split("\r")[-1]
        text = _ANSI_RE.sub("", text).rstrip()
        if not text:
            return

        # "开始任务: xxx.mp4, 总时长: 267s, 已进行: Ns" -> 精简为 "开始播放 xxx.mp4 (04:27)"
        if (m := _RE_VIDEO_START.search(text)) and "开始任务" in text:
            name = m.group(1).strip()
            total = int(m.group(2))
            text = _RE_VIDEO_START.sub(f"开始播放 {name} ({total // 60:02d}:{total % 60:02d})", text)

        # tqdm 进度条不进日志, 解析成结构化状态供表格展示
        if bar := _BAR_RE.match(text):
            with self.lock:
                self.video_progress[bar.group("name").strip()] = {
                    "percent": int(bar.group("pct")),
                    "pos": bar.group("pos"),
                    "total": bar.group("total"),
                    "updated": time.monotonic(),
                }
                # 只保留最近几个视频, 防止长任务累积
                if len(self.video_progress) > 8:
                    for name, _ in sorted(
                        self.video_progress.items(), key=lambda kv: kv[1]["updated"]
                    )[: len(self.video_progress) - 8]:
                        del self.video_progress[name]
            return

        self.append(text)

        if match := _RE_CHAPTER.search(text):
            self.current_chapter = match.group(1).strip()
        elif match := _RE_COURSE.search(text):
            self.current_course = match.group(1).strip()
        elif _RE_TASK_SUCCESS.search(text):
            self.completed += 1
        elif _RE_TASK_FAIL.search(text):
            self.failed += 1

        if "出现403报错" in text or "多次验证码通关失败" in text:
            self.block_hits += 1
            # 记录被拦的任务点(铁事实), 人脸二维码优先用它定位, 不依赖页面标记
            if m := _RE_BLOCK_JOB.search(text):
                self.blocked_job = {"jobid": m.group(1), "objectid": m.group(2) or ""}


class RunManager:
    def __init__(self, store: Store):
        self._store = store
        self._runs: dict[str, AccountRun] = {}
        self._lock = threading.Lock()

    # ---------- 对外查询 ----------
    def get_run(self, account_id: str) -> AccountRun | None:
        with self._lock:
            return self._runs.get(account_id)

    def is_running(self, account_id: str) -> bool:
        run = self.get_run(account_id)
        return run is not None and run.state in ("starting", "running")

    def any_running(self) -> bool:
        with self._lock:
            return any(r.state in ("starting", "running") for r in self._runs.values())

    # ---------- 启动/停止 ----------
    def start(self, account_id: str, config_path: str, work_dir: str,
               total: int | None = None) -> AccountRun:
        # 检查与注册必须在同一把锁内, 否则并发启动(如双击重启)会 spawn 出两个进程
        with self._lock:
            existing = self._runs.get(account_id)
            if existing and existing.state in ("starting", "running"):
                raise RuntimeError("该账号已有任务在运行")
            self._ensure_resources(work_dir)
            run = AccountRun(account_id)
            run.total = total
            run.process, run._job = self._spawn(config_path, work_dir)
            self._runs[account_id] = run
        threading.Thread(
            target=self._watch, args=(run,), daemon=True, name=f"run-{account_id}"
        ).start()
        return run

    def _ensure_resources(self, work_dir: str) -> None:
        """子进程 cwd 在账号目录, 字体映射表等资源按相对路径读取, 需要就位一份."""
        import shutil

        src = os.path.join(PROJECT_ROOT, "resource")
        dst = os.path.join(work_dir, "resource")
        if os.path.isdir(src) and not os.path.exists(dst):
            shutil.copytree(src, dst)

    def stop(self, account_id: str) -> bool:
        run = self.get_run(account_id)
        if not run or not self.is_running(account_id):
            return False
        run.stopping = True
        # main.py 的任务点完成状态会上报服务端, 强杀后重跑会跳过已完成任务点
        run.process.terminate()
        run.append("[Web] 已请求停止, 正在终止子进程...")
        return True

    def stop_all(self) -> int:
        with self._lock:
            ids = list(self._runs.keys())
        stopped = 0
        for account_id in ids:
            if self.stop(account_id):
                stopped += 1
        return stopped

    def kill_all(self) -> int:
        """终止所有仍在运行的子进程.

        Flask 服务退出(如 Ctrl+C / 重启)时通过 atexit 调用,
        避免任务子进程变成孤儿继续请求平台。
        """
        with self._lock:
            runs = list(self._runs.values())
        killed = 0
        for run in runs:
            if run.state in ("starting", "running") and run.process and run.process.poll() is None:
                run.stopping = True
                try:
                    run.process.terminate()
                    killed += 1
                except OSError:
                    pass
        return killed

    def wait_stopped(self, account_id: str, timeout: float = 30.0) -> bool:
        """等待账号任务进入终态(供停止后立即重启的场景), 超时返回 False."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            run = self.get_run(account_id)
            if not run or run.state not in ("starting", "running"):
                return True
            time.sleep(0.2)
        return False

    # ---------- 内部 ----------
    def _spawn(self, config_path: str, work_dir: str) -> tuple[subprocess.Popen, object | None]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(
            [sys.executable, "-u", MAIN_PY, "-c", config_path],
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            **kwargs,
        )
        return process, self._assign_kill_on_close_job(process)

    @staticmethod
    def _assign_kill_on_close_job(process: subprocess.Popen):
        """Windows: 把子进程挂进 KILL_ON_JOB_CLOSE 的 Job Object.

        这样父进程(Flask 服务)无论正常退出还是被强杀, 子进程都会被系统一并终止,
        不会再出现孤儿任务进程继续请求平台的情况。
        """
        if os.name != "nt":
            return None
        try:
            import ctypes

            class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", ctypes.c_uint32),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", ctypes.c_uint32),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", ctypes.c_uint32),
                    ("SchedulingClass", ctypes.c_uint32),
                ]

            class IO_COUNTERS(ctypes.Structure):
                _fields_ = [
                    (name, ctypes.c_uint64)
                    for name in (
                        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
                    )
                ]

            class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                    ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("JobMemoryUsed", ctypes.c_size_t),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            # 必须显式声明原型: 默认 restype=c_int 会把 64 位 HANDLE 截断, 导致句柄无效
            kernel32.CreateJobObjectW.restype = ctypes.c_void_p
            kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
            kernel32.SetInformationJobObject.restype = ctypes.c_int
            kernel32.SetInformationJobObject.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
            ]
            kernel32.AssignProcessToJobObject.restype = ctypes.c_int
            kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                return None
            # 用 Extended 结构(class 9): Basic(class 2) 在部分系统版本返回 ERROR_INVALID_PARAMETER
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                job, 9, ctypes.byref(info), ctypes.sizeof(info)
            ):
                kernel32.CloseHandle(job)
                return None
            if not kernel32.AssignProcessToJobObject(job, process._handle):
                kernel32.CloseHandle(job)
                return None
            return job  # 句柄必须保持打开, 由 AccountRun._job 持有引用
        except Exception:
            return None

    def _watch(self, run: AccountRun) -> None:
        process = run.process
        try:
            run.state = "running"
            stream = process.stdout
            if hasattr(stream, "read"):
                # 真实管道: 逐字节读, 以 \n 和 \r 切分(tqdm 进度条用 \r 原地刷新)
                self._pump_bytes(run, stream)
            else:
                # 测试替身: 按行迭代
                for raw_line in stream:
                    run._ingest(raw_line)
                    self._check_autostop(run, process)
            run.exit_code = process.wait()
        except Exception as exc:  # noqa: BLE001 - 状态机必须收敛
            run.error = f"{type(exc).__name__}: {exc}"
            run.exit_code = process.poll()
        finally:
            run.finished_at = datetime.now().isoformat(timespec="seconds")
            # 结束消息只允许广播一次(防 watcher 异常路径重复 append)
            if run.end_announced:
                return
            run.end_announced = True
            if run.stopping:
                run.state = "stopped"
            elif run.auto_stopped:
                run.state = "error"
                run.error = "连续多次 403 风控拦截, 已自动停止; 请在浏览器或学习通App完成人脸采集/验证后再点「重启」"
            elif run.exit_code == 0:
                run.state = "finished"
            else:
                run.state = "error"
                if not run.error:
                    run.error = f"子进程异常退出, 返回码 {run.exit_code}"
            # 防御: 终态只可能是三者之一, 异常路径兜底为 error
            if run.state not in ("finished", "stopped", "error"):
                run.state = "error"
                if not run.error:
                    run.error = f"状态机异常: 非法终态 {run.state}"
            run.append(f"[Web] 运行结束: {run.state}" + (f" ({run.error})" if run.error else ""))
            self._notify_finished_by_email(run)

    def _notify_finished_by_email(self, run: AccountRun) -> None:
        """任务正常完成/异常退出时发邮件(auto-stop 的邮件由判别流程发, 避免重复)."""
        if run.auto_stopped or run.state not in ("finished", "error"):
            return
        try:
            account = self._store.get_account(run.account_id)
        except Exception:  # noqa: BLE001
            return
        if not account or not str(account.get("email", "") or "").strip():
            return
        from web.emailer import resolve_cfg, send_async

        cfg = resolve_cfg(self._store)
        if not cfg:
            return
        label = account.get("label", "")
        if run.state == "finished":
            subject = f"【刷课平台】{label} 刷课完成"
            body = (f"账号「{label}」({account.get('username', '')}) 的所有课程学习任务已完成。\n\n"
                    "— chaoxing 多账号刷课平台")
        else:
            subject = f"【刷课平台】{label} 任务异常停止"
            body = (f"账号「{label}」({account.get('username', '')}) 的任务异常停止。\n\n"
                    f"原因: {run.error or '未知'}\n\n"
                    "请到面板查看日志, 处理后可点「重启」。\n\n— chaoxing 多账号刷课平台")
        send_async(cfg, str(account["email"]).strip(), subject, body)

    def _pump_bytes(self, run: AccountRun, stream) -> None:
        process = run.process
        buf = bytearray()
        while True:
            byte = stream.read(1)
            if not byte:
                break
            buf += byte
            if byte in (b"\n", b"\r"):
                run._ingest(bytes(buf))
                buf.clear()
                self._check_autostop(run, process)
        if buf:
            run._ingest(bytes(buf))
            self._check_autostop(run, process)

    @staticmethod
    def _check_autostop(run: AccountRun, process) -> None:
        """连续 403 说明账号/IP 已被风控拉黑(常为人脸抓拍要求), 继续重试只会加重."""
        # 幂等 guard: terminate 生效存在窗口期, 期间后续日志行会重复进入此函数
        if run.auto_stopped:
            return
        if run.block_hits >= 3 and process.poll() is None:
            run.auto_stopped = True
            run.needs_attention = True
            run.diagnosed = False  # 待后台判别 face / cooldown
            run.append("[Web] 连续多次 403 风控拦截, 已自动停止任务; "
                       "请在浏览器或学习通App打开该课程, 按提示完成人脸采集/验证后再点「重启」")
            process.terminate()
