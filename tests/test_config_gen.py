# -*- coding: utf-8 -*-
"""web.config_gen 单元测试: 参数校验与 config.ini 生成."""
import configparser
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.config_gen import (  # noqa: E402
    ConfigError,
    build_sections,
    sanitize_params,
    validate_tiku,
    write_config,
)

ACCOUNT = {"id": "a1", "username": "13800000000", "password": "pw"}


class SanitizeParamsTestCase(unittest.TestCase):
    def test_defaults_and_coercion(self):
        params = sanitize_params({"speed": "1.5", "jobs": "2"})
        self.assertEqual(params["speed"], 1.5)
        self.assertEqual(params["jobs"], 2)
        self.assertEqual(params["notopen_action"], "retry")
        self.assertFalse(params["work_redo_enabled"])

    def test_speed_out_of_range(self):
        with self.assertRaises(ConfigError):
            sanitize_params({"speed": 3.0})
        with self.assertRaises(ConfigError):
            sanitize_params({"speed": 0.5})

    def test_jobs_out_of_range(self):
        with self.assertRaises(ConfigError):
            sanitize_params({"jobs": 0})

    def test_invalid_notopen_action(self):
        with self.assertRaises(ConfigError):
            sanitize_params({"notopen_action": "ask"})


class ValidateTikuTestCase(unittest.TestCase):
    def test_empty_provider_ok(self):
        self.assertEqual(validate_tiku({}), [])
        self.assertEqual(validate_tiku({"provider": "  "}), [])

    def test_provider_chain_ok(self):
        self.assertEqual(
            validate_tiku({"provider": "TikuGo, TikuYanxi"}), ["TikuGo", "TikuYanxi"]
        )

    def test_tiku_manual_rejected(self):
        with self.assertRaises(ConfigError):
            validate_tiku({"provider": "TikuManual"})

    def test_unknown_provider_rejected(self):
        with self.assertRaises(ConfigError):
            validate_tiku({"provider": "TikuNotFound"})


class BuildSectionsTestCase(unittest.TestCase):
    def setUp(self):
        self.params = sanitize_params({})
        self.tiku = {"provider": "AI", "endpoint": "https://x/v1", "key": "k", "model": "m"}

    def test_common_section_fixed_values(self):
        sections = build_sections(ACCOUNT, ["100", "200"], self.params, self.tiku, {})
        common = sections["common"]
        # cookies 优先 + Web 端预检, 是子进程无交互运行的前提
        self.assertEqual(common["use_cookies"], "true")
        self.assertEqual(common["course_list"], "100,200")
        self.assertEqual(common["username"], "13800000000")

    def test_tiku_section_disables_llm_check(self):
        sections = build_sections(ACCOUNT, [], self.params, self.tiku, {})
        self.assertEqual(sections["tiku"]["check_llm_connection"], "false")
        self.assertEqual(sections["tiku"]["provider"], "AI")

    def test_sections_skipped_when_provider_empty(self):
        sections = build_sections(ACCOUNT, [], self.params, {}, {"provider": "ServerChan"})
        self.assertNotIn("tiku", sections)
        self.assertIn("notification", sections)

    def test_write_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.ini")
            write_config(path, ACCOUNT, ["100"], self.params, self.tiku, {})
            parser = configparser.ConfigParser()
            parser.read(path, encoding="utf8")
            self.assertEqual(parser["common"]["use_cookies"], "true")
            self.assertEqual(parser["tiku"]["check_llm_connection"], "false")
            self.assertEqual(parser["common"]["course_list"], "100")


if __name__ == "__main__":
    unittest.main()
