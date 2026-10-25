# -*- coding: utf-8 -*-
"""账号与全局设置的 JSON 存储.

所有数据落在项目根目录的 data/ 下:
    data/accounts.json          账号列表(含明文账密, 整个目录不应提交或外传)
    data/tiku.json              全局题库配置
    data/notification.json      全局通知配置
    data/admin.json             管理员口令哈希
    data/accounts/<id>/         每账号工作目录(config.ini / cookies.txt / chaoxing.log)
"""
import json
import os
import threading
import uuid
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
ACCOUNTS_DIR = os.path.join(DATA_DIR, "accounts")

DEFAULT_PARAMS = {
    "speed": 1.0,
    "jobs": 4,
    "notopen_action": "retry",
    "retry_interval": 1.0,
    "work_redo_enabled": False,
    "work_max_retries": 3,
    "add_learning_count": False,
    "target_count": 100,
}


def normalize_cookies(cookie_text: str) -> str:
    """把用户粘贴的 cookie 串规范化为 cookies.txt 的 k=v;k=v 格式."""
    if not cookie_text:
        return ""
    parts = []
    for item in cookie_text.replace("\n", ";").split(";"):
        item = item.strip()
        if item and "=" in item:
            parts.append(item)
    return ";".join(parts)


class Store:
    def __init__(self, data_dir: str | None = None):
        # 统一转绝对路径: 子进程 cwd 会切到账号目录, 相对路径会解析错位
        self.data_dir = os.path.abspath(data_dir or DATA_DIR)
        self.accounts_dir = os.path.join(self.data_dir, "accounts")
        self._lock = threading.RLock()
        os.makedirs(self.accounts_dir, exist_ok=True)

    # ---------- 底层读写 ----------
    def _path(self, name: str) -> str:
        return os.path.join(self.data_dir, name)

    def _read_json(self, name: str, default):
        path = self._path(name)
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, name: str, obj) -> None:
        path = self._path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    # ---------- 账号 ----------
    def list_accounts(self) -> list[dict]:
        with self._lock:
            return self._read_json("accounts.json", {"accounts": []})["accounts"]

    def get_account(self, account_id: str) -> dict | None:
        for account in self.list_accounts():
            if account["id"] == account_id:
                return account
        return None

    def _save_accounts(self, accounts: list[dict]) -> None:
        self._write_json("accounts.json", {"accounts": accounts})

    def create_account(self, label: str, username: str, password: str = "", cookies: str = "",
                       email: str = "") -> dict:
        account = {
            "id": uuid.uuid4().hex[:12],
            "label": label.strip() or username,
            "username": username.strip(),
            "password": password.strip(),
            "email": email.strip(),
            # 预留给后续多用户体系: 账号归属于哪个面板用户
            "owner": None,
            "params": dict(DEFAULT_PARAMS),
            "course_ids": [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        with self._lock:
            accounts = self.list_accounts()
            accounts.append(account)
            self._save_accounts(accounts)
        account_dir = self.account_dir(account["id"])
        os.makedirs(account_dir, exist_ok=True)
        if cookies:
            self.write_cookies(account["id"], cookies)
        return account

    def update_account(self, account_id: str, fields: dict) -> dict | None:
        """可更新字段: label / username / password / email / params / course_ids."""
        allowed = {"label", "username", "password", "email", "params", "course_ids"}
        with self._lock:
            accounts = self.list_accounts()
            for account in accounts:
                if account["id"] == account_id:
                    for key, value in fields.items():
                        if key in allowed and value is not None:
                            account[key] = value
                    self._save_accounts(accounts)
                    return account
        return None

    def delete_account(self, account_id: str) -> bool:
        import shutil

        with self._lock:
            accounts = self.list_accounts()
            remaining = [a for a in accounts if a["id"] != account_id]
            if len(remaining) == len(accounts):
                return False
            self._save_accounts(remaining)
        shutil.rmtree(self.account_dir(account_id), ignore_errors=True)
        return True

    def account_dir(self, account_id: str) -> str:
        path = os.path.join(self.accounts_dir, account_id)
        os.makedirs(path, exist_ok=True)
        return path

    def write_cookies(self, account_id: str, cookie_text: str) -> None:
        normalized = normalize_cookies(cookie_text)
        if not normalized:
            return
        path = os.path.join(self.account_dir(account_id), "cookies.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(normalized)

    # ---------- 全局设置 ----------
    def get_tiku(self) -> dict:
        return self._read_json("tiku.json", {})

    def set_tiku(self, config: dict) -> None:
        with self._lock:
            self._write_json("tiku.json", config)

    def get_notification(self) -> dict:
        return self._read_json("notification.json", {})

    def set_notification(self, config: dict) -> None:
        with self._lock:
            self._write_json("notification.json", config)

    def get_email(self) -> dict:
        return self._read_json("email.json", {})

    def set_email(self, config: dict) -> None:
        with self._lock:
            self._write_json("email.json", config)
