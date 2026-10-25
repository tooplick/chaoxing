# -*- coding: utf-8 -*-
"""web.runner 单元测试: 用假子进程验证状态机/停止/日志缓冲与进度解析."""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.runner import RunManager  # noqa: E402
from web.store import Store  # noqa: E402


class FakePopen:
    """模拟 main.py 子进程: 按行吐出预置输出, slow 模式下可被 terminate 打断."""

    def __init__(self, lines=None, exit_code=0, slow=False, raw_stream: bytes | None = None):
        self.exit_code = exit_code
        self.terminated = False
        self.slow = slow
        if raw_stream is not None:
            import io

            self.stdout = io.BytesIO(raw_stream)
        else:
            self.stdout = self._stream(lines or [])

    def _stream(self, lines):
        for line in lines:
            if self.slow and self.terminated:
                break
            yield line.encode("utf-8")
            if self.slow:
                time.sleep(0.05)

    def terminate(self):
        self.terminated = True

    def wait(self):
        return self.exit_code

    def poll(self):
        return None


class FakeRunManager(RunManager):
    def __init__(self, store, proc):
        super().__init__(store)
        self.proc = proc

    def _spawn(self, config_path, work_dir):
        return self.proc, None


class RunnerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(data_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _wait_state(self, manager, account_id, states, timeout=5.0):
        deadline = time.time() + timeout
        run = manager.get_run(account_id)
        while time.time() < deadline:
            run = manager.get_run(account_id)
            if run and run.state in states:
                return run
            time.sleep(0.02)
        raise AssertionError(f"等待状态 {states} 超时, 当前 {run.state if run else None}")

    def test_progress_parsing_and_finished_state(self):
        lines = [
            "\x1b[32m2026-10-25 10:00:00 | INFO | 开始学习课程: 大学物理\x1b[0m",
            "2026-10-25 10:00:01 | INFO | 当前章节: 绪论",
            "2026-10-25 10:00:02 | DEBUG | Task success: 大学物理 - 绪论",
            "2026-10-25 10:00:03 | INFO | 当前章节: 力学",
            "2026-10-25 10:00:04 | DEBUG | Task success: 大学物理 - 力学",
            "2026-10-25 10:00:05 | WARNING | 任务重试次数达到上限: 大学物理 - 电磁学",
        ]
        proc = FakePopen(lines, exit_code=0)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".", total=3)

        run = self._wait_state(manager, "acc1", {"finished"})
        self.assertEqual(run.completed, 2)
        self.assertEqual(run.failed, 1)
        self.assertEqual(run.current_course, "大学物理")
        self.assertEqual(run.current_chapter, "力学")
        self.assertEqual(run.exit_code, 0)
        self.assertTrue(run.error is None)
        # ANSI 颜色码应被剥离
        texts = [text for _, text in run.lines_after(0)]
        self.assertTrue(any("开始学习课程: 大学物理" in t for t in texts))
        self.assertFalse(any("\x1b[" in t for t in texts))

    def test_error_state_on_nonzero_exit(self):
        proc = FakePopen(["2026-10-25 10:00:00 | INFO | 登录成功..."], exit_code=1)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        run = self._wait_state(manager, "acc1", {"error"})
        self.assertEqual(run.exit_code, 1)
        self.assertIn("返回码 1", run.error)

    def test_stop_marks_stopped(self):
        lines = [f"2026-10-25 10:00:0{i % 10} | INFO | 心跳 {i}" for i in range(200)]
        proc = FakePopen(lines, slow=True)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        self._wait_state(manager, "acc1", {"running"})
        self.assertTrue(manager.is_running("acc1"))

        self.assertTrue(manager.stop("acc1"))
        run = self._wait_state(manager, "acc1", {"stopped"})
        self.assertTrue(proc.terminated)
        self.assertFalse(manager.is_running("acc1"))

    def test_auto_stop_on_repeated_403(self):
        """连续 3 次 403 风控拦截应自动终止子进程并进入 error 态."""
        lines = [
            "2026-10-25 21:00:00 | INFO | 开始学习课程: 大学物理",
            "2026-10-25 21:00:01 | ERROR | 出现403报错, 尝试修复无效, 正在跳过当前任务点...",
            "2026-10-25 21:00:02 | ERROR | 出现403报错, 尝试修复无效, 正在跳过当前任务点...",
            "2026-10-25 21:00:03 | ERROR | 出现403报错, 尝试修复无效, 正在跳过当前任务点...",
        ] + [f"2026-10-25 21:00:1{i} | INFO | 不应被处理的后续输出 {i}" for i in range(50)]
        proc = FakePopen(lines, slow=True)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        run = self._wait_state(manager, "acc1", {"error"})
        self.assertTrue(run.auto_stopped)
        self.assertTrue(run.needs_attention)
        self.assertFalse(run.diagnosed)
        self.assertIsNone(run.blocked_reason)
        self.assertTrue(proc.terminated)
        self.assertIn("403", run.error)
        self.assertIn("人脸", run.error)
        texts = [text for _, text in run.lines_after(0)]
        # 幂等 guard: 自动停止提示只应出现一次(terminate 窗口期不重复)
        self.assertEqual(sum("自动停止任务" in t for t in texts), 1)
        # 「运行结束」只出现一次, 且绝不能是 running(回归: _check_autostop 曾错位 append)
        self.assertEqual(sum("运行结束" in t for t in texts), 1)
        self.assertFalse(any("运行结束: running" in t for t in texts))
        snap = run.snapshot()
        self.assertIn("blocked_reason", snap)
        self.assertIn("needs_attention", snap)

    def test_progress_bar_parsed_as_status(self):
        """tqdm 进度条不进日志缓冲, 解析为结构化视频进度供表格展示."""
        raw = (
            b"2026-10-25 22:13:22 | INFO | \xe5\xbd\x93\xe5\x89\x8d\xe7\xab\xa0\xe8\x8a\x82: 3.1\n"
            b"ted.mp4:  25%|\xe2\x96\x88\xe2\x96\x88 | 01:07/04:27\r"
            b"ted.mp4:  50%|\xe2\x96\x88\xe2\x96\x88 | 02:14/04:27\r"
            b"other.mp4:  75%|\xe2\x96\x88\xe2\x96\x88 | 03:20/04:27\r"
            b"2026-10-25 22:18:00 | DEBUG | Task success: X - Y\n"
        )
        proc = FakePopen(raw_stream=raw, exit_code=0)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        run = self._wait_state(manager, "acc1", {"finished"})
        # 日志缓冲中不应有任何进度条行
        texts = [text for _, text in run.lines_after(0)]
        self.assertFalse(any("%|" in t for t in texts))
        # 进度条转为视频状态: 同名视频取最后一帧, 多视频并存
        snap = run.snapshot()
        videos = {v["name"]: v for v in snap["videos"]}
        self.assertEqual(videos["ted.mp4"]["percent"], 50)
        self.assertEqual(videos["ted.mp4"]["pos"], "02:14")
        self.assertEqual(videos["ted.mp4"]["total"], "04:27")
        self.assertEqual(videos["other.mp4"]["percent"], 75)
        self.assertEqual(run.completed, 1)

    def test_duplicate_start_rejected(self):
        """同一账号并发/重复启动必须被拒绝, 防止 spawn 出双进程."""
        proc = FakePopen([f"2026-10-25 21:00:{i:02d} | INFO | 心跳 {i}" for i in range(200)], slow=True)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        with self.assertRaises(RuntimeError):
            manager.start("acc1", "config.ini", ".")
        manager.stop("acc1")
        self._wait_state(manager, "acc1", {"stopped"})

    def test_kill_all_terminates_running_processes(self):
        """服务退出时的 atexit 清理应终止所有运行中的子进程."""
        lines = [f"2026-10-25 21:00:{i:02d} | INFO | 心跳 {i}" for i in range(200)]
        procs = [FakePopen(lines, slow=True) for _ in range(2)]
        manager1 = FakeRunManager(self.store, procs[0])
        manager1.start("acc1", "config.ini", ".")
        manager2 = FakeRunManager(self.store, procs[1])
        manager2.start("acc2", "config.ini", ".")
        self._wait_state(manager1, "acc1", {"running"})

        killed = manager1.kill_all()
        self.assertGreaterEqual(killed, 1)
        self.assertTrue(procs[0].terminated)
        run = self._wait_state(manager1, "acc1", {"stopped", "error"})
        self.assertIn(run.state, {"stopped", "error"})

    def test_logs_after_sequence(self):
        proc = FakePopen(["line-a", "line-b"], exit_code=0)
        manager = FakeRunManager(self.store, proc)
        manager.start("acc1", "config.ini", ".")
        self._wait_state(manager, "acc1", {"finished"})
        run = manager.get_run("acc1")
        first = run.lines_after(0)
        self.assertGreaterEqual(len(first), 2)
        mid = first[0][0]
        rest = run.lines_after(mid)
        self.assertEqual(rest[0][0], mid + 1)


if __name__ == "__main__":
    unittest.main()
