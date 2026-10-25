# -*- coding: utf-8 -*-
"""按账号生成独立的 config.ini, 供 main.py 子进程使用."""
import configparser
import io

# api/answer.py PROVIDER_REGISTRY 中的全部题库
KNOWN_PROVIDERS = ["TikuYanxi", "TikuLike", "TikuAdapter", "AI", "SiliconFlow", "TikuGo", "TikuManual"]
# Web 平台不支持的 provider(子进程无终端, 交互式答题会卡死)
FORBIDDEN_PROVIDERS = ["TikuManual"]

VALID_NOTOPEN_ACTION = {"retry", "continue"}


class ConfigError(ValueError):
    """配置校验失败, message 直接展示给前端."""


def validate_tiku(tiku: dict) -> list[str]:
    """校验全局题库配置, 返回 provider 链; 不合法时抛 ConfigError."""
    provider_raw = (tiku or {}).get("provider", "")
    providers = [p.strip() for p in provider_raw.split(",") if p.strip()]
    if not providers:
        return []
    unknown = [p for p in providers if p not in KNOWN_PROVIDERS]
    if unknown:
        raise ConfigError(f"未知题库 provider: {', '.join(unknown)}")
    forbidden = [p for p in providers if p in FORBIDDEN_PROVIDERS]
    if forbidden:
        raise ConfigError(
            f"题库 {', '.join(forbidden)} 是命令行手动输入模式, Web 平台不支持; "
            "请在设置页更换题库"
        )
    return providers


def sanitize_params(params: dict) -> dict:
    """校验并裁剪刷课参数([common] 节), 非法值直接抛 ConfigError."""
    p = dict(params or {})

    speed = float(p.get("speed", 1.0))
    if not 1.0 <= speed <= 2.0:
        raise ConfigError("倍速 speed 需在 1~2 之间")
    p["speed"] = speed

    jobs = int(p.get("jobs", 4))
    if jobs < 1 or jobs > 16:
        raise ConfigError("并发章节数 jobs 需在 1~16 之间")
    p["jobs"] = jobs

    action = str(p.get("notopen_action", "retry"))
    if action not in VALID_NOTOPEN_ACTION:
        raise ConfigError("notopen_action 仅支持 retry / continue")
    p["notopen_action"] = action

    interval = float(p.get("retry_interval", 1.0))
    if interval <= 0:
        raise ConfigError("重试间隔 retry_interval 需大于 0")
    p["retry_interval"] = interval

    p["work_redo_enabled"] = bool(p.get("work_redo_enabled", False))
    p["work_max_retries"] = max(1, int(p.get("work_max_retries", 3)))
    p["add_learning_count"] = bool(p.get("add_learning_count", False))
    p["target_count"] = max(1, int(p.get("target_count", 100)))
    return p


# 各题库在 init_tiku/_init_tiku 中直接下标读取的键, 缺失会 KeyError 崩溃
TIKU_COMMON_DEFAULTS = {
    "submit": "false",
    "cover_rate": "0.9",
    "true_list": "正确,对,√,是",
    "false_list": "错误,错,×,否,不对,不正确",
}
TIKU_PROVIDER_DEFAULTS = {
    "AI": {"endpoint": "", "key": "", "model": "", "http_proxy": "", "min_interval_seconds": "3"},
    "SiliconFlow": {"siliconflow_key": ""},
    "TikuAdapter": {"url": ""},
    "TikuYanxi": {"tokens": ""},
    "TikuLike": {"tokens": ""},
}


def _bool_str(value) -> str:
    return "true" if value else "false"


def build_sections(account: dict, course_ids: list[str], params: dict,
                   tiku: dict, notification: dict) -> dict[str, dict]:
    """组装 {section: {key: str_value}}, 数值/布尔全部转为 ini 字符串."""
    common = {
        "use_cookies": "true",
        "username": account.get("username", ""),
        "password": account.get("password", ""),
        "course_list": ",".join(course_ids),
        "speed": str(params["speed"]),
        "jobs": str(params["jobs"]),
        "notopen_action": params["notopen_action"],
        "retry_interval": str(params["retry_interval"]),
        "work_redo_enabled": _bool_str(params["work_redo_enabled"]),
        "work_max_retries": str(params["work_max_retries"]),
        "add_learning_count": _bool_str(params["add_learning_count"]),
        "target_count": str(params["target_count"]),
    }

    sections = {"common": common}

    if tiku and tiku.get("provider", "").strip():
        tiku_section = {}
        for key, value in tiku.items():
            if isinstance(value, bool):
                value = _bool_str(value)
            if str(value).strip() != "":
                tiku_section[key] = str(value)
        # 题库代码直接下标读取这些键, 缺失会 KeyError, 补上模板默认值
        for key, value in TIKU_COMMON_DEFAULTS.items():
            tiku_section.setdefault(key, value)
        providers = [p.strip() for p in tiku["provider"].split(",") if p.strip()]
        for provider in providers:
            for key, value in TIKU_PROVIDER_DEFAULTS.get(provider, {}).items():
                tiku_section.setdefault(key, value)
        # 交互式的连接检查确认由 Web 端预检代替, 禁用子进程内路径
        tiku_section["check_llm_connection"] = "false"
        sections["tiku"] = tiku_section

    if notification and notification.get("provider", "").strip():
        # Email 由 Web 平台自身发送(web/emailer), 子进程的通知模块不认识该 provider
        if str(notification.get("provider")).strip() != "Email":
            sections["notification"] = {
                k: str(v) for k, v in notification.items() if str(v).strip() != ""
            }

    return sections


def render_ini(sections: dict[str, dict]) -> str:
    parser = configparser.ConfigParser()
    for name, values in sections.items():
        parser[name] = {k: v for k, v in values.items()}
    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def write_config(path: str, account: dict, course_ids: list[str], params: dict,
                 tiku: dict, notification: dict) -> str:
    sections = build_sections(account, course_ids, params, tiku, notification)
    content = render_ini(sections)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path
