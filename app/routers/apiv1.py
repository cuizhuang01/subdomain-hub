"""API Key 管理 + 开放 API（X-API-Key 认证）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import _db, api_key_auth, current_user
from ..security import gen_api_key, now_iso
from ..services import (BizError, check_available, create_domain, domain_stats, domain_view,
                        get_domain, sync_expired, URL_RE)

router = APIRouter(tags=["openapi"])


# ---------------- Key 管理（登录态） ----------------
@router.get("/api/keys")
def list_keys(user=Depends(current_user), conn=Depends(_db)):
    rows = conn.execute(
        "SELECT id,name,key,status,last_used_at,created_at FROM api_keys WHERE user_id=? ORDER BY id DESC",
        (user["id"],),
    ).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        d["key_masked"] = d["key"][:10] + "…" + d["key"][-6:]
        items.append(d)
    return {"items": items}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)


@router.post("/api/keys")
def create_key(body: KeyIn, user=Depends(current_user), conn=Depends(_db)):
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM api_keys WHERE user_id=? AND status='active'", (user["id"],)
    ).fetchone()["c"]
    if count >= 10:
        raise HTTPException(400, "最多创建 10 个有效 API Key")
    key = gen_api_key()
    conn.execute("INSERT INTO api_keys (user_id,name,key,status,created_at) VALUES (?,?,?,?,?)",
                 (user["id"], body.name.strip(), key, "active", now_iso()))
    rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return {"id": rid, "name": body.name.strip(), "key": key,
            "notice": "请立即保存，密钥仅本次完整展示"}


@router.delete("/api/keys/{key_id}")
def delete_key(key_id: int, user=Depends(current_user), conn=Depends(_db)):
    row = conn.execute("SELECT * FROM api_keys WHERE id=?", (key_id,)).fetchone()
    if not row or (row["user_id"] != user["id"] and user["role"] != "admin"):
        raise HTTPException(404, "密钥不存在")
    conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    return {"ok": True}


# ---------------- 开放 API v1 ----------------
v1 = APIRouter(prefix="/api/v1", tags=["openapi"], dependencies=[Depends(api_key_auth)])


def _u(user=Depends(api_key_auth)):
    return user


@v1.get("/domains")
def v1_list(user=Depends(api_key_auth), conn=Depends(_db)):
    sync_expired(conn)
    rows = conn.execute("SELECT * FROM domains WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    return {"items": [domain_view(conn, dict(r)) for r in rows]}


class V1CreateIn(BaseModel):
    prefix: str
    purpose: str = "redirect"
    target_url: str = ""
    redirect_type: int = 302


@v1.post("/domains")
def v1_create(body: V1CreateIn, user=Depends(api_key_auth), conn=Depends(_db)):
    if body.target_url and not URL_RE.match(body.target_url.strip()):
        raise HTTPException(400, "target_url 必须以 http(s):// 开头")
    try:
        d = create_domain(conn, user["id"], body.prefix, body.purpose,
                          body.target_url.strip(), body.redirect_type, "API 创建", user["name"])
    except BizError as e:
        raise HTTPException(e.code, e.message)
    return domain_view(conn, d)


class V1PatchIn(BaseModel):
    target_url: str | None = None
    redirect_type: int | None = None


@v1.patch("/domains/{domain_id}")
def v1_patch(domain_id: int, body: V1PatchIn, user=Depends(api_key_auth), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"]:
        raise HTTPException(403, "无权操作")
    if body.target_url is not None:
        if body.target_url and not URL_RE.match(body.target_url.strip()):
            raise HTTPException(400, "target_url 必须以 http(s):// 开头")
        conn.execute("UPDATE domains SET target_url=? WHERE id=?",
                     (body.target_url.strip() or None, domain_id))
    if body.redirect_type in (301, 302):
        conn.execute("UPDATE domains SET redirect_type=? WHERE id=?", (body.redirect_type, domain_id))
    return domain_view(conn, get_domain(conn, domain_id))


@v1.get("/domains/{domain_id}/stats")
def v1_stats(domain_id: int, days: int = 30, user=Depends(api_key_auth), conn=Depends(_db)):
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"]:
        raise HTTPException(403, "无权查看")
    return domain_stats(conn, domain_id, days)


@v1.get("/me")
def v1_me(user=Depends(api_key_auth)):
    return {"id": user["id"], "email": user["email"], "name": user["name"], "balance": user["balance"]}


@v1.get("/check")
def v1_check(prefix: str, conn=Depends(_db), user=Depends(api_key_auth)):
    return check_available(conn, prefix)


router.include_router(v1)
