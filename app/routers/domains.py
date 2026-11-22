"""用户端域名管理接口。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import settings_store
from ..deps import _db, current_user
from ..security import now_iso
from ..services import (BizError, check_available, create_domain, domain_stats, domain_view,
                        get_domain, recent_visits, renew_domain, sync_expired, URL_RE)

router = APIRouter(prefix="/api/domains", tags=["domains"])


class DomainCreateIn(BaseModel):
    prefix: str = Field(min_length=3, max_length=32)
    purpose: str = "redirect"
    target_url: str = ""
    redirect_type: int = 302
    note: str = ""


class DomainUpdateIn(BaseModel):
    target_url: str | None = None
    redirect_type: int | None = None
    note: str | None = None
    auto_renew: bool | None = None
    purpose: str | None = None


class RenewIn(BaseModel):
    years: int = Field(default=1, ge=1, le=10)
    pay_with_balance: bool = True


@router.get("/check")
def check(prefix: str = Query(...), conn=Depends(_db)):
    return check_available(conn, prefix)


@router.get("")
def list_domains(status: str = "", q: str = "", page: int = 1, size: int = 20,
                 user=Depends(current_user), conn=Depends(_db)):
    sync_expired(conn)
    where = ["d.user_id=?"]
    args = [user["id"]]
    if status and status != "all":
        where.append("d.status=?")
        args.append(status)
    if q:
        where.append("(d.prefix LIKE ? OR d.fqdn LIKE ? OR d.target_url LIKE ?)")
        args += [f"%{q}%"] * 3
    sql = ("SELECT d.*, (SELECT COUNT(*) FROM dns_records r WHERE r.domain_id=d.id) AS dns_count "
           "FROM domains d WHERE " + " AND ".join(where) +
           " ORDER BY d.id DESC LIMIT ? OFFSET ?")
    page = max(1, page)
    size = max(1, min(100, size))
    rows = conn.execute(sql, args + [size, (page - 1) * size]).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) AS c FROM domains d WHERE " + " AND ".join(where), args
    ).fetchone()["c"]
    items = [domain_view(conn, dict(r)) for r in rows]
    return {"items": items, "total": total, "page": page, "size": size}


@router.post("")
def create(body: DomainCreateIn, user=Depends(current_user), conn=Depends(_db)):
    if body.purpose == "redirect" and body.target_url.strip():
        if not URL_RE.match(body.target_url.strip()):
            raise HTTPException(400, "跳转地址必须以 http:// 或 https:// 开头")
    try:
        d = create_domain(conn, user["id"], body.prefix, body.purpose,
                          body.target_url.strip(), body.redirect_type, body.note.strip(),
                          user["name"])
    except BizError as e:
        raise HTTPException(e.code, e.message)
    return domain_view(conn, d)


@router.get("/{domain_id}")
def detail(domain_id: int, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权访问该域名")
    sync_expired(conn)
    return domain_view(conn, get_domain(conn, domain_id))


@router.patch("/{domain_id}")
def update(domain_id: int, body: DomainUpdateIn, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权修改该域名")
    fields = {}
    if body.target_url is not None:
        val = body.target_url.strip()
        if val and not URL_RE.match(val):
            raise HTTPException(400, "跳转地址必须以 http:// 或 https:// 开头")
        fields["target_url"] = val or None
    if body.redirect_type is not None:
        fields["redirect_type"] = 301 if body.redirect_type == 301 else 302
    if body.note is not None:
        fields["note"] = body.note.strip()
    if body.auto_renew is not None:
        fields["auto_renew"] = 1 if body.auto_renew else 0
    if body.purpose is not None:
        if body.purpose not in ("redirect", "dns"):
            raise HTTPException(400, "用途只能是 redirect 或 dns")
        fields["purpose"] = body.purpose
    if d["status"] == "pending" and fields:
        raise HTTPException(400, "待审核域名暂不可修改，请先等待审核")
    for k, v in fields.items():
        conn.execute(f"UPDATE domains SET {k}=? WHERE id=?", (v, domain_id))
    return domain_view(conn, get_domain(conn, domain_id))


@router.post("/{domain_id}/renew")
def renew(domain_id: int, body: RenewIn, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权操作该域名")
    if d["status"] in ("pending", "rejected"):
        raise HTTPException(400, "该域名尚未通过审核，无法续费")
    try:
        res = renew_domain(conn, domain_id, body.years, body.pay_with_balance,
                           user["id"], user["name"])
    except BizError as e:
        raise HTTPException(e.code, e.message)
    return {"domain": domain_view(conn, res["domain"]), "amount": res["amount"],
            "years": res["years"], "balance": conn.execute(
                "SELECT balance FROM users WHERE id=?", (user["id"],)).fetchone()["balance"]}


@router.delete("/{domain_id}")
def remove(domain_id: int, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权删除该域名")
    conn.execute("DELETE FROM domains WHERE id=?", (domain_id,))
    return {"ok": True}


@router.get("/{domain_id}/stats")
def stats(domain_id: int, days: int = 30, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权查看统计")
    return domain_stats(conn, domain_id, days)


@router.get("/{domain_id}/visits")
def visits(domain_id: int, limit: int = 30, user=Depends(current_user), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权查看访问记录")
    return {"items": recent_visits(conn, domain_id, min(200, max(1, limit)))}
