# -*- coding: utf-8 -*-
"""api.captcha 单元测试: 提交结果判定与图片获取的容错."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.captcha import CxCaptcha  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = b"img"


class CaptchaTestCase(unittest.TestCase):
    def setUp(self):
        # 显式传 ocr=None 禁用 OCR, 不触发 ddddocr 加载
        self.solver = CxCaptcha(user_agent="ua", cookies="a=1", ocr=None)

    def test_submit_success_is_3xx_without_redirect_following(self):
        """核心回归: 服务端 302 表示通关成功(即使 requests 平时不跟随也应判成功)."""
        captured = {}

        def fake_get(api, params=None, **kwargs):
            captured["allow_redirects"] = kwargs.get("allow_redirects")
            return FakeResponse(302)

        self.solver.s.get = fake_get
        self.assertTrue(self.solver.submitCaptcha("abcd"))
        self.assertFalse(captured["allow_redirects"])  # 必须显式禁止跟随重定向

    def test_submit_failure_is_200(self):
        self.solver.s.get = lambda api, params=None, **kwargs: FakeResponse(200)
        self.assertFalse(self.solver.submitCaptcha("wrong"))

    def test_get_captcha_accepts_image_content_type(self):
        def fake_get(api, params=None, **kwargs):
            return FakeResponse(200, {"Content-Type": "image/png"})

        self.solver.s.get = fake_get
        self.assertEqual(self.solver.getCaptcha(), b"img")

    def test_get_captcha_rejects_non_image(self):
        self.solver.s.get = lambda api, params=None, **kwargs: FakeResponse(200, {"Content-Type": "text/html"})
        self.assertIsNone(self.solver.getCaptcha())

    def test_get_captcha_404_marks_unavailable(self):
        """验证码接口 404(已下线)时应标记 unavailable, 供上层跳过重试."""
        self.assertFalse(self.solver.unavailable)
        self.solver.s.get = lambda api, params=None, **kwargs: FakeResponse(404, {"Content-Type": "text/html"})
        self.assertIsNone(self.solver.getCaptcha())
        self.assertTrue(self.solver.unavailable)

    def test_get_captcha_200_keeps_available(self):
        def fake_get(api, params=None, **kwargs):
            return FakeResponse(200, {"Content-Type": "image/png"})

        self.solver.s.get = fake_get
        self.assertEqual(self.solver.getCaptcha(), b"img")
        self.assertFalse(self.solver.unavailable)


if __name__ == "__main__":
    unittest.main()
