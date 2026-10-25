# -*- coding: utf-8 -*-
"""全新部署场景的人脸二维码流程: 无 course_ids/无课程缓存也能定位课程."""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402
import web.api as api_mod  # noqa: E404


COURSES = [
    {"courseId": "111", "clazzId": "a1", "cpi": "c1", "title": "课A", "teacher": "t"},
    {"courseId": "222", "clazzId": "a2", "cpi": "c2", "title": "课B", "teacher": "t"},
]


class FaceQrFreshDeployTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = app_module.create_app(data_dir=self.tmp.name)
        self.client = self.app.test_client()
        self.client.post("/api/auth/setup", json={"password": "x" * 8})
        # 全新部署: 添加账号, 不启动任务(course_ids 为空, 无 courses.json)
        acc = self.client.post(
            "/api/accounts", json={"label": "new", "username": "13800000000", "password": "pw"}
        ).get_json()["account"]
        self.account_id = acc["id"]
        self._orig_cli = api_mod._run_cli
        self.calls = []

        def fake_cli(cli_args, account_dir, timeout):
            self.calls.append(cli_args[0])
            if cli_args[0] == "courses":
                return {"ok": True, "courses": COURSES}
            if cli_args[0] == "face-qr":
                return {"ok": True, "chapter": "1.1", "qr_base64": "abcd",
                        "status_tokens": {"uuid": "u"}}
            raise AssertionError(f"unexpected cli: {cli_args}")

        api_mod._run_cli = fake_cli

    def tearDown(self):
        api_mod._run_cli = self._orig_cli
        self.tmp.cleanup()

    def test_face_qr_without_cache_or_course_ids(self):
        r = self.client.post(f"/api/accounts/{self.account_id}/face-qr", json={})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertTrue(body.get("ok"))
        self.assertEqual(body.get("chapter"), "1.1")
        # courses 缓存缺失时自动拉取一次, 再执行 face-qr
        self.assertEqual(self.calls, ["courses", "face-qr"])

    def test_face_qr_prefers_requested_course(self):
        self.client.post(f"/api/accounts/{self.account_id}/face-qr", json={"course_id": "222"})
        self.assertEqual(self.calls, ["courses", "face-qr"])


if __name__ == "__main__":
    unittest.main()
