# -*- coding: utf-8 -*-
"""管理员口令认证: 存储/校验/登录限速."""
import hashlib
import json
import os
import secrets
import time

ENV_PASSWORD = "CHAOXING_ADMIN_PASSWORD"

# 登录失败限速: 每个 IP 连续失败 FAIL_LIMIT 次后锁定 LOCK_SECONDS
FAIL_LIMIT = 5
LOCK_SECONDS = 60


def _hash(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


class AuthManager:
    def __init__(self, data_dir: str):
        self._path = os.path.join(data_dir, "admin.json")
        self._fails: dict[str, list] = {}  # ip -> [连续失败次数, 锁定截止时间戳]

    def _load(self) -> dict | None:
        if not os.path.exists(self._path):
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def is_initialized(self) -> bool:
        """口令已配置: 存在 admin.json, 或通过环境变量预设."""
        return bool(os.environ.get(ENV_PASSWORD)) or self._load() is not None

    def setup(self, password: str) -> None:
        """首次设置口令; 已设置后不允许再走此路径."""
        if self.is_initialized():
            raise PermissionError("管理员口令已设置")
        if len(password) < 6:
            raise ValueError("口令长度至少 6 位")
        salt = secrets.token_hex(16)
        record = {"salt": salt, "hash": _hash(password, salt)}
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(record, f)

    def verify(self, password: str) -> bool:
        env_password = os.environ.get(ENV_PASSWORD)
        if env_password:
            return secrets.compare_digest(password, env_password)
        record = self._load()
        if not record:
            return False
        return secrets.compare_digest(_hash(password, record["salt"]), record["hash"])

    # ---------- 登录限速 ----------
    def check_rate_limit(self, ip: str) -> int:
        """返回 0 表示允许尝试, 否则返回剩余锁定秒数."""
        entry = self._fails.get(ip)
        if not entry:
            return 0
        fails, locked_until = entry
        if locked_until > time.time():
            return int(locked_until - time.time()) + 1
        return 0

    def record_failure(self, ip: str) -> None:
        entry = self._fails.get(ip, [0, 0])
        entry[0] += 1
        if entry[0] >= FAIL_LIMIT:
            entry = [0, time.time() + LOCK_SECONDS]
        self._fails[ip] = entry

    def record_success(self, ip: str) -> None:
        self._fails.pop(ip, None)
