# -*- coding: utf-8 -*-
"""web.store 单元测试: 账号 CRUD 与设置读写."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.store import DEFAULT_PARAMS, Store, normalize_cookies  # noqa: E402


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(data_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_account_crud(self):
        account = self.store.create_account("张三", "13800000000", password="pw")
        self.assertEqual(self.store.list_accounts()[0]["id"], account["id"])
        self.assertEqual(account["params"], DEFAULT_PARAMS)
        self.assertIsNone(account["owner"])  # 多用户体系预留字段

        updated = self.store.update_account(account["id"], {"label": "李四", "course_ids": ["100"]})
        self.assertEqual(updated["label"], "李四")
        self.assertEqual(updated["course_ids"], ["100"])

        self.assertTrue(self.store.delete_account(account["id"]))
        self.assertEqual(self.store.list_accounts(), [])
        self.assertFalse(self.store.delete_account(account["id"]))

    def test_password_update_ignores_empty(self):
        account = self.store.create_account("张三", "138", password="pw")
        self.store.update_account(account["id"], {"password": None})
        self.assertEqual(self.store.get_account(account["id"])["password"], "pw")

    def test_cookies_written_normalized(self):
        account = self.store.create_account("张三", "138", cookies="a=1; b=2\n c=3")
        cookies_path = os.path.join(self.store.account_dir(account["id"]), "cookies.txt")
        with open(cookies_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertEqual(content, "a=1;b=2;c=3")
        self.assertEqual(normalize_cookies("uid=1;"), "uid=1")
        self.assertEqual(normalize_cookies(""), "")

    def test_email_settings_and_account_field(self):
        self.store.set_email({"host": "smtp.qq.com", "port": 465, "ssl": True,
                              "username": "a@b.com", "password": "x"})
        cfg = self.store.get_email()
        self.assertEqual(cfg["host"], "smtp.qq.com")
        self.assertEqual(cfg["port"], 465)

        account = self.store.create_account("张三", "13800000000", password="pw", email="owner@example.com")
        self.assertEqual(account["email"], "owner@example.com")
        self.store.update_account(account["id"], {"email": "new@example.com"})
        self.assertEqual(self.store.get_account(account["id"])["email"], "new@example.com")

    def test_settings_roundtrip(self):
        self.store.set_tiku({"provider": "AI", "key": "k"})
        self.store.set_notification({"provider": "ServerChan", "url": "https://x"})
        self.assertEqual(self.store.get_tiku()["provider"], "AI")
        self.assertEqual(self.store.get_notification()["url"], "https://x")


if __name__ == "__main__":
    unittest.main()
