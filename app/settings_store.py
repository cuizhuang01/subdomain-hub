"""系统设置：数据库存储 + 默认值 + 类型转换。"""
import json
import sqlite3

DEFAULTS = {
    "site_name": "云子域 · 二级域名分发平台",
    "main_domain": "example.com",
    "price_per_year": "20",
    "default_years": "1",
    "auto_approve": "1",
    "max_domains_per_user": "10",
    "reserved_words": json.dumps(
        ["www", "admin", "api", "mail", "smtp", "ftp", "ns", "dns", "root", "system",
         "support", "help", "blog", "shop", "app", "cdn", "static", "test", "dev",
         "status", "docs", "web", "host", "cloud", "user", "login", "pay", "order"],
        ensure_ascii=False,
    ),
    "dns_provider": "manual",  # manual / cloudflare / aliyun
    "cf_api_token": "",
    "cf_zone_id": "",
    "aliyun_access_key_id": "",
    "aliyun_access_key_secret": "",
    "aliyun_region": "cn-hangzhou",
    "allow_self_service_renew": "1",
    "notice": "欢迎使用二级域名分发平台。请勿使用域名从事违法违规活动。",
}

SECRET_KEYS = {"cf_api_token", "aliyun_access_key_id", "aliyun_access_key_secret"}


def bootstrap(conn: sqlite3.Connection):
    existing = {r["key"] for r in conn.execute("SELECT key FROM settings")}
    for k, v in DEFAULTS.items():
        if k not in existing:
            conn.execute("INSERT INTO settings (key,value) VALUES (?,?)", (k, v))
    conn.commit()


def get(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return DEFAULTS.get(key, default)
    return row["value"]


def get_int(conn, key: str, default: int = 0) -> int:
    try:
        return int(float(get(conn, key)))
    except (TypeError, ValueError):
        return default


def get_float(conn, key: str, default: float = 0.0) -> float:
    try:
        return float(get(conn, key))
    except (TypeError, ValueError):
        return default


def get_bool(conn, key: str, default: bool = False) -> bool:
    v = get(conn, key)
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def get_json(conn, key: str, default=None):
    try:
        return json.loads(get(conn, key))
    except Exception:
        return default if default is not None else []


def set_value(conn, key: str, value):
    conn.execute(
        "INSERT INTO settings (key,value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def all_public(conn) -> dict:
    """返回给前端的设置（密钥打码）。"""
    out = {}
    for r in conn.execute("SELECT key,value FROM settings"):
        k, v = r["key"], r["value"]
        if k in SECRET_KEYS and v:
            out[k] = v[:4] + "****" + v[-4:] if len(v) > 8 else "****"
            out[k + "__set"] = True
        else:
            out[k] = v
    return out
