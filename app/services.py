"""核心业务逻辑：申请、审批、续费、过期、访问统计、审计。"""
import json
import re
import sqlite3
from datetime import timedelta
from typing import Optional

from . import settings_store
from .security import days_left, gen_order_no, now_dt, now_iso, parse_iso

PREFIX_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{1,30})[a-z0-9]$")
URL_RE = re.compile(r"^(https?://)[^\s<>\"']+$", re.IGNORECASE)
IP_RE = re.compile(r"^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$")
DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")


class BizError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


# ---------------- 审计 ----------------
def audit(conn, action: str, target: str = "", detail: str = "", actor_id=None, actor_name="system"):
    conn.execute(
        "INSERT INTO audit_logs (actor_id,actor_name,action,target,detail,ts) VALUES (?,?,?,?,?,?)",
        (actor_id, actor_name, action, target, detail, now_iso()),
    )


# ---------------- 前缀校验 ----------------
def normalize_prefix(prefix: str) -> str:
    p = (prefix or "").strip().lower()
    if p.endswith("."):
        p = p[:-1]
    return p


def validate_prefix(conn, prefix: str) -> str:
    p = normalize_prefix(prefix)
    if not p:
        raise BizError("域名前缀不能为空")
    if len(p) < 3 or len(p) > 32:
        raise BizError("前缀长度需为 3-32 个字符")
    if not PREFIX_RE.match(p):
        raise BizError("只能使用小写字母、数字和连字符，且不能以连字符开头或结尾")
    if p.isdigit():
        raise BizError("前缀不能为纯数字，避免与 IP 混淆")
    reserved = {w.lower() for w in settings_store.get_json(conn, "reserved_words", [])}
    if p in reserved:
        raise BizError(f"“{p}” 为系统保留词，请更换")
    return p


def fqdn_of(conn, prefix: str) -> str:
    return f"{prefix}.{settings_store.get(conn, 'main_domain')}"


def check_available(conn, prefix: str) -> dict:
    try:
        p = validate_prefix(conn, prefix)
    except BizError as e:
        return {"available": False, "prefix": normalize_prefix(prefix), "reason": e.message}
    row = conn.execute("SELECT id, status FROM domains WHERE prefix=?", (p,)).fetchone()
    if row:
        return {"available": False, "prefix": p, "fqdn": fqdn_of(conn, p),
                "reason": "该前缀已被占用"}
    return {"available": True, "prefix": p, "fqdn": fqdn_of(conn, p), "reason": ""}


# ---------------- 申请 ----------------
def create_domain(conn, user_id: int, prefix: str, purpose: str = "redirect",
                  target_url: str = "", redirect_type: int = 302,
                  note: str = "", actor_name: str = "") -> dict:
    p = validate_prefix(conn, prefix)
    purpose = purpose if purpose in ("redirect", "dns") else "redirect"
    if purpose == "redirect":
        target_url = (target_url or "").strip()
    else:
        target_url = (target_url or "").strip() or None

    row = conn.execute("SELECT id FROM domains WHERE prefix=?", (p,)).fetchone()
    if row:
        raise BizError("该前缀已被占用，请更换")

    # 进行中(pending)数量限制
    limit = settings_store.get_int(conn, "max_domains_per_user", 10)
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM domains WHERE user_id=? AND status IN ('pending','active')",
        (user_id,),
    ).fetchone()["c"]
    if total >= limit:
        raise BizError(f"每个账号最多同时持有 {limit} 个域名")

    auto = settings_store.get_bool(conn, "auto_approve", True)
    years = settings_store.get_int(conn, "default_years", 1) or 1
    now = now_iso()
    status = "active" if auto else "pending"
    expires = (now_dt() + timedelta(days=365 * years)).replace(microsecond=0).isoformat() if auto else None

    conn.execute(
        """INSERT INTO domains (user_id,prefix,fqdn,purpose,target_url,redirect_type,status,note,
                               expires_at,created_at,activated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, p, fqdn_of(conn, p), purpose, target_url, 301 if redirect_type == 301 else 302,
         status, note, expires, now, now if auto else None),
    )
    did = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    audit(conn, "domain.create", fqdn_of(conn, p), f"用途={purpose}", user_id, actor_name)
    return get_domain(conn, did)


def get_domain(conn, domain_id: int) -> dict:
    row = conn.execute("SELECT * FROM domains WHERE id=?", (domain_id,)).fetchone()
    if not row:
        raise BizError("域名不存在", 404)
    return dict(row)


# ---------------- 审批 ----------------
def approve_domain(conn, domain_id: int, actor_id=None, actor_name="admin") -> dict:
    d = get_domain(conn, domain_id)
    if d["status"] == "active":
        raise BizError("该域名已是激活状态")
    years = settings_store.get_int(conn, "default_years", 1) or 1
    now = now_iso()
    expires = (now_dt() + timedelta(days=365 * years)).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE domains SET status='active', expires_at=?, activated_at=?, reject_reason=NULL WHERE id=?",
        (expires, now, domain_id),
    )
    audit(conn, "domain.approve", d["fqdn"], "审核通过", actor_id, actor_name)
    return get_domain(conn, domain_id)


def reject_domain(conn, domain_id: int, reason: str, actor_id=None, actor_name="admin") -> dict:
    d = get_domain(conn, domain_id)
    conn.execute("UPDATE domains SET status='rejected', reject_reason=? WHERE id=?", (reason, domain_id))
    audit(conn, "domain.reject", d["fqdn"], reason, actor_id, actor_name)
    return get_domain(conn, domain_id)


# ---------------- 续费 ----------------
def renew_domain(conn, domain_id: int, years: int = 1, pay_with_balance: bool = True,
                 actor_id=None, actor_name="") -> dict:
    d = get_domain(conn, domain_id)
    if d["status"] not in ("active", "expired", "suspended"):
        raise BizError("当前状态不可续费")
    years = max(1, min(10, int(years)))
    price = settings_store.get_float(conn, "price_per_year", 20.0)
    amount = round(price * years, 2)

    if pay_with_balance:
        u = conn.execute("SELECT balance FROM users WHERE id=?", (d["user_id"],)).fetchone()
        if u["balance"] < amount:
            raise BizError(f"余额不足，需 {amount:.2f} 元，当前 {u['balance']:.2f} 元", 402)
        conn.execute("UPDATE users SET balance=balance-? WHERE id=?", (amount, d["user_id"]))

    base = parse_iso(d["expires_at"]) if d["expires_at"] else now_dt()
    base = max(base, now_dt())
    new_exp = (base + timedelta(days=365 * years)).replace(microsecond=0).isoformat()
    conn.execute(
        "UPDATE domains SET expires_at=?, status='active' WHERE id=?", (new_exp, domain_id)
    )
    conn.execute(
        """INSERT INTO orders (order_no,user_id,domain_id,kind,years,amount,status,created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (gen_order_no(), d["user_id"], domain_id, "renew", years, amount, "paid", now_iso()),
    )
    audit(conn, "domain.renew", d["fqdn"], f"{years}年 ￥{amount}", actor_id, actor_name)
    return {"domain": get_domain(conn, domain_id), "amount": amount, "years": years}


# ---------------- 状态维护 ----------------
def sync_expired(conn) -> int:
    """把到期域名置为 expired（惰性执行，每次请求前调用代价极低）。"""
    now = now_iso()
    rows = conn.execute(
        "SELECT id, fqdn FROM domains WHERE status='active' AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    ).fetchall()
    for r in rows:
        conn.execute("UPDATE domains SET status='expired' WHERE id=?", (r["id"],))
        audit(conn, "domain.expired", r["fqdn"], "到期自动停用")
    return len(rows)


# ---------------- 访问记录与统计 ----------------
def detect_device(ua: str) -> str:
    ua = (ua or "").lower()
    if "bot" in ua or "spider" in ua or "crawler" in ua:
        return "bot"
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobile" in ua or "android" in ua or "iphone" in ua:
        return "mobile"
    if ua:
        return "desktop"
    return "unknown"


def record_visit(conn, domain_id: int, ip: str, ua: str, referer: str, path: str, country: str = ""):
    now = now_dt()
    conn.execute(
        """INSERT INTO visits (domain_id,ts,day,ip,country,device,referer,path,ua)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (domain_id, now.replace(microsecond=0).isoformat(), now.strftime("%Y-%m-%d"),
         ip, country, detect_device(ua), referer, path, (ua or "")[:300]),
    )
    conn.execute(
        "UPDATE domains SET hit_count=hit_count+1, last_hit_at=? WHERE id=?",
        (now.replace(microsecond=0).isoformat(), domain_id),
    )


def domain_stats(conn, domain_id: int, days: int = 30) -> dict:
    days = max(1, min(365, days))
    start = (now_dt() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    series = {}
    for i in range(days):
        key = (now_dt() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        series[key] = 0
    for r in conn.execute(
        "SELECT day, COUNT(*) AS c FROM visits WHERE domain_id=? AND day>=? GROUP BY day",
        (domain_id, start),
    ):
        series[r["day"]] = r["c"]

    total = conn.execute("SELECT COUNT(*) AS c FROM visits WHERE domain_id=?", (domain_id,)).fetchone()["c"]
    today = conn.execute(
        "SELECT COUNT(*) AS c FROM visits WHERE domain_id=? AND day=?",
        (domain_id, now_dt().strftime("%Y-%m-%d")),
    ).fetchone()["c"]

    def group(col):
        return [
            {"name": r["v"] or "未知", "count": r["c"]}
            for r in conn.execute(
                f"SELECT {col} AS v, COUNT(*) AS c FROM visits WHERE domain_id=? AND day>=? "
                f"GROUP BY v ORDER BY c DESC LIMIT 8",
                (domain_id, start),
            )
        ]

    devices = group("device")
    refs = group("referer")
    countries = group("country")
    return {
        "domain_id": domain_id,
        "days": days,
        "total": total,
        "today": today,
        "series": [{"day": k, "count": v} for k, v in series.items()],
        "devices": devices,
        "referers": refs,
        "countries": countries,
    }


def recent_visits(conn, domain_id: int, limit: int = 30) -> list:
    rows = conn.execute(
        "SELECT ts,ip,country,device,referer,path,ua FROM visits WHERE domain_id=? "
        "ORDER BY id DESC LIMIT ?", (domain_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------- 域名摘要 ----------------
def domain_view(conn, d: dict) -> dict:
    out = dict(d)
    out["days_left"] = days_left(d["expires_at"]) if d["expires_at"] else 0
    out["dns_count"] = conn.execute(
        "SELECT COUNT(*) AS c FROM dns_records WHERE domain_id=?", (d["id"],)
    ).fetchone()["c"]
    out["redirect_type"] = d["redirect_type"]
    return out
