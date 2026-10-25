# -*- coding: utf-8 -*-
"""邮件通知: SMTP 配置来自 data/email.json, 事件发生时发给账号绑定的邮箱."""
import smtplib
import threading
from email.header import Header
from email.mime.text import MIMEText

from api.logger import logger


def resolve_cfg(store) -> dict | None:
    """解析邮件通知配置: 通知服务选了 Email 用其字段, 否则回退旧 email.json."""
    n = store.get_notification()
    if str(n.get("provider", "")).strip() == "Email":
        return n
    legacy = store.get_email()
    if legacy.get("host"):
        return legacy
    return None


def _validate(cfg: dict) -> str | None:
    """必填项校验, 返回错误信息或 None."""
    if not str(cfg.get("host", "")).strip():
        return "SMTP 服务器不能为空"
    if not str(cfg.get("username", "")).strip():
        return "用户名不能为空"
    if not str(cfg.get("password", "")).strip():
        return "密码/授权码不能为空"
    try:
        int(cfg.get("port") or 465)
    except (TypeError, ValueError):
        return "端口必须是数字"
    return None


def send_sync(cfg: dict, to: str, subject: str, body: str) -> tuple[bool, str]:
    """同步发送, 供测试连接接口返回真实结果."""
    problem = _validate(cfg)
    if problem:
        return False, problem
    if not to or "@" not in to:
        return False, "收件邮箱无效"
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        sender = str(cfg.get("sender", "")).strip() or str(cfg["username"]).strip()
        msg["From"] = sender
        msg["To"] = to
        port = int(cfg.get("port") or 465)
        use_ssl = cfg.get("ssl", True)
        if isinstance(use_ssl, str):
            use_ssl = use_ssl.strip().lower() in ("true", "1", "yes")
        if use_ssl:
            server = smtplib.SMTP_SSL(str(cfg["host"]).strip(), port, timeout=15)
        else:
            server = smtplib.SMTP(str(cfg["host"]).strip(), port, timeout=15)
            server.starttls()
        with server:
            server.login(str(cfg["username"]).strip(), str(cfg["password"]))
            server.sendmail(sender, [to], msg.as_string())
        return True, "发送成功"
    except Exception as exc:  # noqa: BLE001 - 邮件失败不应影响主流程
        logger.warning(f"邮件发送失败: {exc}")
        return False, f"{type(exc).__name__}: {exc}"


def send_async(store, to: str, subject: str, body: str) -> None:
    """后台线程发送, 不阻塞任务 watcher / 状态轮询."""
    if not to or "@" not in to:
        return

    def worker():
        send_sync(store.get_email(), to, subject, body)

    threading.Thread(target=worker, daemon=True, name="email-notify").start()
