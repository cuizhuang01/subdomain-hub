"""管理员后台接口：总览、用户、域名审核、订单、审计、系统设置。"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import settings_store
from ..deps import _db, current_admin
from ..dns_providers import provider_info
from ..security import days_left, hash_password, now_dt, now_iso
from ..services import (approve_domain, audit, domain_view, get_domain, reject_domain,
                        sync_expired)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview")
def overview(conn=Depends(_db), admin=Depends(current_admin)):
    sync_expired(conn)
    def count(sql, args=()):
        return conn.execute(sql, args).fetchone()["c"]
    today = now_dt().strftime("%Y-%m-%d")
    series = {}
    for i in range(13, -1, -1):
        key = (now_dt() - timedelta(days=i)).strftime("%Y-%m-%d")
        series[key] = 0
    for r in conn.execute(
        "SELECT day, COUNT(*) AS c FROM visits WHERE day>=? GROUP BY day",
        ((now_dt() - timedelta(days=13)).strftime("%Y-%m-%d"),),
    ):
        series[r["day"]] = r["c"]
    return {
        "users": count("SELECT COUNT(*) AS c FROM users"),
        "users_today": count("SELECT COUNT(*) AS c FROM users WHERE created_at>=?", (today,)),
        "domains": count("SELECT COUNT(*) AS c FROM domains"),
        "pending": count("SELECT COUNT(*) AS c FROM domains WHERE status='pending'"),
        "active": count("SELECT COUNT(*) AS c FROM domains WHERE status='active'"),
        "expired": count("SELECT COUNT(*) AS c FROM domains WHERE status='expired'"),
        "hits_today": count("SELECT COUNT(*) AS c FROM visits WHERE day=?", (today,)),
        "hits_total": count("SELECT COUNT(*) AS c FROM visits"),
        "revenue": round(conn.execute(
            "SELECT COALESCE(SUM(amount),0) AS s FROM orders WHERE status='paid'"
        ).fetchone()["s"], 2),
        "visit_series": [{"day": k, "count": v} for k, v in series.items()],
        "recent_domains": [domain_view(conn, dict(r)) for r in conn.execute(
            "SELECT d.*, (SELECT COUNT(*) FROM dns_records x WHERE x.domain_id=d.id) AS dns_count "
            "FROM domains d ORDER BY d.id DESC LIMIT 8")],
        "providers": provider_info(conn),
    }


# ---------------- 用户 ----------------
@router.get("/users")
def users(q: str = "", page: int = 1, size: int = 20, conn=Depends(_db), admin=Depends(current_admin)):
    where, args = [], []
    if q:
        where.append("(email LIKE ? OR name LIKE ?)")
        args += [f"%{q}%"] * 2
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, page), max(1, min(100, size))
    rows = conn.execute(
        f"""SELECT u.*, (SELECT COUNT(*) FROM domains d WHERE d.user_id=u.id) AS domain_count
            FROM users u {clause} ORDER BY u.id DESC LIMIT ? OFFSET ?""",
        args + [size, (page - 1) * size],
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM users u {clause}", args).fetchone()["c"]
    items = [{k: r[k] for k in ("id", "email", "name", "role", "status", "balance",
                                "created_at", "domain_count")} for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


class UserPatchIn(BaseModel):
    role: str | None = None
    status: str | None = None
    balance: float | None = None
    password: str | None = None


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatchIn, conn=Depends(_db), admin=Depends(current_admin)):
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(404, "用户不存在")
    if body.role in ("user", "admin"):
        conn.execute("UPDATE users SET role=? WHERE id=?", (body.role, user_id))
    if body.status in ("active", "banned"):
        conn.execute("UPDATE users SET status=? WHERE id=?", (body.status, user_id))
    if body.balance is not None:
        conn.execute("UPDATE users SET balance=? WHERE id=?", (round(body.balance, 2), user_id))
    if body.password:
        if len(body.password) < 6:
            raise HTTPException(400, "密码至少 6 位")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                     (hash_password(body.password), user_id))
    audit(conn, "user.update", row["email"], str(body.model_dump(exclude_none=True)),
          admin["id"], admin["name"])
    return {"ok": True}


# ---------------- 域名 ----------------
@router.get("/domains")
def all_domains(status: str = "", q: str = "", page: int = 1, size: int = 20,
                conn=Depends(_db), admin=Depends(current_admin)):
    sync_expired(conn)
    where, args = [], []
    if status and status != "all":
        where.append("d.status=?")
        args.append(status)
    if q:
        where.append("(d.fqdn LIKE ? OR u.email LIKE ?)")
        args += [f"%{q}%"] * 2
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, page), max(1, min(100, size))
    rows = conn.execute(
        f"""SELECT d.*, u.email AS owner_email, u.name AS owner_name,
                   (SELECT COUNT(*) FROM dns_records r WHERE r.domain_id=d.id) AS dns_count
            FROM domains d JOIN users u ON u.id=d.user_id {clause}
            ORDER BY CASE d.status WHEN 'pending' THEN 0 ELSE 1 END, d.id DESC
            LIMIT ? OFFSET ?""",
        args + [size, (page - 1) * size],
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) AS c FROM domains d JOIN users u ON u.id=d.user_id {clause}", args
    ).fetchone()["c"]
    items = []
    for r in rows:
        d = domain_view(conn, dict(r))
        d["days_left"] = days_left(r["expires_at"]) if r["expires_at"] else 0
        items.append(d)
    return {"items": items, "total": total, "page": page, "size": size}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


class BulkIn(BaseModel):
    ids: list[int]
    action: str  # approve / reject
    reason: str = "批量审核"


@router.post("/domains/{domain_id}/approve")
def approve(domain_id: int, conn=Depends(_db), admin=Depends(current_admin)):
    try:
        d = approve_domain(conn, domain_id, admin["id"], admin["name"])
    except Exception as e:
        raise HTTPException(400, getattr(e, "message", str(e)))
    return {"ok": True, "domain": domain_view(conn, d)}


@router.post("/domains/{domain_id}/reject")
def reject(domain_id: int, body: RejectIn, conn=Depends(_db), admin=Depends(current_admin)):
    d = reject_domain(conn, domain_id, body.reason.strip(), admin["id"], admin["name"])
    return {"ok": True, "domain": domain_view(conn, d)}


@router.post("/domains/{domain_id}/suspend")
def suspend(domain_id: int, body: RejectIn | None = None, conn=Depends(_db),
            admin=Depends(current_admin)):
    d = get_domain(conn, domain_id)
    conn.execute("UPDATE domains SET status='suspended' WHERE id=?", (domain_id,))
    audit(conn, "domain.suspend", d["fqdn"], (body.reason if body else ""), admin["id"], admin["name"])
    return {"ok": True}


@router.post("/domains/{domain_id}/resume")
def resume(domain_id: int, conn=Depends(_db), admin=Depends(current_admin)):
    d = get_domain(conn, domain_id)
    conn.execute("UPDATE domains SET status='active', expires_at=COALESCE(expires_at, ?) WHERE id=?",
                 (now_iso(), domain_id))
    audit(conn, "domain.resume", d["fqdn"], "", admin["id"], admin["name"])
    return {"ok": True}


@router.delete("/domains/{domain_id}")
def delete_domain(domain_id: int, conn=Depends(_db), admin=Depends(current_admin)):
    d = get_domain(conn, domain_id)
    conn.execute("DELETE FROM domains WHERE id=?", (domain_id,))
    audit(conn, "domain.force_delete", d["fqdn"], "管理员删除", admin["id"], admin["name"])
    return {"ok": True}


@router.post("/domains/bulk")
def bulk(body: BulkIn, conn=Depends(_db), admin=Depends(current_admin)):
    ok, failed = 0, []
    for did in body.ids[:200]:
        try:
            if body.action == "approve":
                approve_domain(conn, did, admin["id"], admin["name"])
            else:
                reject_domain(conn, did, body.reason, admin["id"], admin["name"])
            ok += 1
        except Exception as e:
            failed.append({"id": did, "error": getattr(e, "message", str(e))})
    return {"ok": ok, "failed": failed}


# ---------------- 订单 / 审计 ----------------
@router.get("/orders")
def orders(page: int = 1, size: int = 20, kind: str = "", conn=Depends(_db),
           admin=Depends(current_admin)):
    where, args = [], []
    if kind:
        where.append("o.kind=?")
        args.append(kind)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, page), max(1, min(100, size))
    rows = conn.execute(
        f"""SELECT o.*, u.email AS user_email, d.fqdn AS fqdn FROM orders o
            JOIN users u ON u.id=o.user_id LEFT JOIN domains d ON d.id=o.domain_id
            {clause} ORDER BY o.id DESC LIMIT ? OFFSET ?""",
        args + [size, (page - 1) * size],
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM orders o {clause}", args).fetchone()["c"]
    return {"items": [dict(r) for r in rows], "total": total}


@router.get("/audit")
def audit_logs(page: int = 1, size: int = 30, q: str = "", conn=Depends(_db),
               admin=Depends(current_admin)):
    where, args = [], []
    if q:
        where.append("(action LIKE ? OR target LIKE ? OR detail LIKE ?)")
        args += [f"%{q}%"] * 3
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    page, size = max(1, page), max(1, min(100, size))
    rows = conn.execute(
        f"SELECT * FROM audit_logs {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
        args + [size, (page - 1) * size],
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) AS c FROM audit_logs {clause}", args).fetchone()["c"]
    return {"items": [dict(r) for r in rows], "total": total}


# ---------------- 设置 ----------------
@router.get("/settings")
def get_settings(conn=Depends(_db), admin=Depends(current_admin)):
    data = settings_store.all_public(conn)
    return {"settings": data, "providers": provider_info(conn)}


class SettingsIn(BaseModel):
    site_name: str | None = None
    main_domain: str | None = None
    price_per_year: float | None = None
    default_years: int | None = None
    auto_approve: bool | None = None
    max_domains_per_user: int | None = None
    reserved_words: list[str] | None = None
    dns_provider: str | None = None
    cf_api_token: str | None = None
    cf_zone_id: str | None = None
    aliyun_access_key_id: str | None = None
    aliyun_access_key_secret: str | None = None
    allow_self_service_renew: bool | None = None
    notice: str | None = None


@router.put("/settings")
def update_settings(body: SettingsIn, conn=Depends(_db), admin=Depends(current_admin)):
    data = body.model_dump(exclude_none=True)
    if "main_domain" in data:
        md = data["main_domain"].strip().lower()
        if not md or "." not in md:
            raise HTTPException(400, "主域名格式不正确，例如 example.com")
        data["main_domain"] = md
    if "reserved_words" in data:
        data["reserved_words"] = [w.strip().lower() for w in data["reserved_words"] if w.strip()]
    if "dns_provider" in data and data["dns_provider"] not in ("manual", "cloudflare", "aliyun"):
        raise HTTPException(400, "DNS 服务商不支持")
    if "max_domains_per_user" in data:
        data["max_domains_per_user"] = max(1, min(1000, int(data["max_domains_per_user"])))
    for k, v in data.items():
        if isinstance(v, bool):
            v = "1" if v else "0"
        if isinstance(v, list):
            import json
            v = json.dumps(v, ensure_ascii=False)
        settings_store.set_value(conn, k, v)
    audit(conn, "settings.update", "system",
          ", ".join(data.keys()), admin["id"], admin["name"])
    return {"ok": True, "settings": settings_store.all_public(conn)}
