# -*- coding: utf-8 -*-
"""课程列表缓存行为测试: 二次请求不再拉起子进程, refresh=1 强制刷新."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import web.api as api_mod  # noqa: E402


class CoursesCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app_module.create_app(data_dir=self.tmp.name)
        self.client = self.app.test_client()
        self.client.post("/api/auth/setup", json={"password": "x" * 8})
        account = self.client.post(
            "/api/accounts", json={"label": "t", "username": "13800000000", "password": "pw"}
        ).get_json()["account"]
        self.account_id = account["id"]
        self.calls = []
        self._orig_cli = api_mod._run_cli

        def fake_cli(cli_args, account_dir, timeout):
            self.calls.append(cli_args[0])
            return {"ok": True, "courses": [
                {"courseId": "1", "clazzId": "2", "cpi": "3", "title": "课程", "teacher": "老师"},
            ]}

        api_mod._run_cli = fake_cli
        api_mod._courses_cache.clear()

    def tearDown(self):
        api_mod._run_cli = self._orig_cli
        api_mod._courses_cache.clear()
        self.tmp.cleanup()

    def test_cache_hit_and_refresh(self):
        r1 = self.client.get(f"/api/accounts/{self.account_id}/courses")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(self.calls, ["courses"])

        # 缓存命中: 不再调用子进程
        r2 = self.client.get(f"/api/accounts/{self.account_id}/courses")
        self.assertEqual(self.calls, ["courses"])
        self.assertEqual(r2.get_json()["courses"], r1.get_json()["courses"])

        # refresh=1 强制重新拉取
        r3 = self.client.get(f"/api/accounts/{self.account_id}/courses?refresh=1")
        self.assertEqual(self.calls, ["courses", "courses"])
        self.assertEqual(r3.status_code, 200)

        # 结果落盘, 服务重启后仍可快速回显
        cache_file = os.path.join(self.tmp.name, "accounts", self.account_id, "courses.json")
        self.assertTrue(os.path.exists(cache_file))

    def test_stale_file_served_after_restart(self):
        self.client.get(f"/api/accounts/{self.account_id}/courses")
        api_mod._courses_cache.clear()  # 模拟服务重启(内存缓存丢失)
        r = self.client.get(f"/api/accounts/{self.account_id}/courses")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()["courses"]), 1)
        self.assertEqual(self.calls, ["courses"])  # 用落盘数据, 没有再拉子进程


if __name__ == "__main__":
    unittest.main()
