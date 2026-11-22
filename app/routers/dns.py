"""DNS 解析记录管理（支持本地托管与 Cloudflare / 阿里云同步）。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import _db, current_user
from ..dns_providers import ProviderError, get_provider, provider_info
from ..security import now_iso
from ..services import DOMAIN_RE, IP_RE, get_domain

router = APIRouter(prefix="/api/domains/{domain_id}/dns", tags=["dns"])

TYPES = {"A", "AAAA", "CNAME", "TXT", "MX"}


class RecordIn(BaseModel):
    type: str
    name: str = "@"
    value: str = Field(min_length=1, max_length=1024)
    ttl: int = Field(default=600, ge=60, le=86400)
    priority: int = Field(default=10, ge=1, le=65535)
    proxied: bool = False


def _validate(rec: RecordIn):
    t = rec.type.upper()
    if t not in TYPES:
        raise HTTPException(400, "记录类型仅支持 A / AAAA / CNAME / TXT / MX")
    name = (rec.name or "@").strip().lower() or "@"
    if name != "@" and not DOMAIN_RE.match(name + ".x") and not name.replace("-", "").isalnum():
        raise HTTPException(400, "主机记录格式不正确（示例 @ 或 www）")
    val = rec.value.strip()
    if t == "A" and not IP_RE.match(val):
        raise HTTPException(400, "A 记录的值为 IPv4 地址，例如 1.2.3.4")
    if t == "AAAA" and ":" not in val:
        raise HTTPException(400, "AAAA 记录的值为 IPv6 地址")
    if t in ("CNAME", "MX") and not DOMAIN_RE.match(val.rstrip(".")):
        raise HTTPException(400, f"{t} 记录的值必须为域名，例如 cdn.example.net")
    return t, name, val


def _owned(conn, domain_id: int, user: dict) -> dict:
    d = get_domain(conn, domain_id)
    if d["user_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "无权操作该域名")
    return d


def _fqdn(d: dict, name: str) -> str:
    return d["fqdn"] if name == "@" else f"{name}.{d['fqdn']}"


@router.get("")
def list_records(domain_id: int, user=Depends(current_user), conn=Depends(_db)):
    _owned(conn, domain_id, user)
    rows = conn.execute(
        "SELECT * FROM dns_records WHERE domain_id=? ORDER BY id DESC", (domain_id,)
    ).fetchall()
    return {"items": [dict(r) for r in rows], "providers": provider_info(conn)}


@router.post("")
def add_record(domain_id: int, body: RecordIn, user=Depends(current_user), conn=Depends(_db)):
    d = _owned(conn, domain_id, user)
    if d["status"] != "active":
        raise HTTPException(400, "仅激活状态的域名可配置解析")
    if d["purpose"] != "dns":
        raise HTTPException(400, "该域名用途为「跳转分发」，如需解析托管请先切换用途")
    t, name, val = _validate(body)
    fqdn = _fqdn(d, name)
    dup = conn.execute(
        "SELECT id FROM dns_records WHERE domain_id=? AND type=? AND name=? AND value=?",
        (domain_id, t, name, val),
    ).fetchone()
    if dup:
        raise HTTPException(400, "已存在相同的解析记录")

    rec = {"type": t, "value": val, "ttl": body.ttl, "priority": body.priority,
           "proxied": 1 if body.proxied else 0}
    prov = get_provider(conn)
    try:
        result = prov.create_record(fqdn, rec)
        status, msg, prid = result["status"], result["message"], result.get("provider_record_id")
    except ProviderError as e:
        status, msg, prid = "failed", f"同步失败：{e}", None
    except Exception as e:  # 网络异常
        status, msg, prid = "failed", f"同步异常：{e}", None

    conn.execute(
        """INSERT INTO dns_records (domain_id,type,name,value,ttl,priority,proxied,
                                   provider_record_id,sync_status,sync_message,created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (domain_id, t, name, val, body.ttl, body.priority, rec["proxied"], prid, status, msg, now_iso()),
    )
    rid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    row = dict(conn.execute("SELECT * FROM dns_records WHERE id=?", (rid,)).fetchone())
    return {"record": row, "provider": prov.name, "message": msg}


@router.patch("/{record_id}")
def update_record(domain_id: int, record_id: int, body: RecordIn,
                  user=Depends(current_user), conn=Depends(_db)):
    d = _owned(conn, domain_id, user)
    row = conn.execute("SELECT * FROM dns_records WHERE id=? AND domain_id=?",
                       (record_id, domain_id)).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在")
    old = dict(row)
    t, name, val = _validate(body)
    prov = get_provider(conn)
    if old["provider_record_id"]:
        try:
            prov.delete_record(old["provider_record_id"], _fqdn(d, old["name"]))
        except Exception:
            pass
    try:
        result = prov.create_record(_fqdn(d, name),
                                    {"type": t, "value": val, "ttl": body.ttl,
                                     "priority": body.priority, "proxied": body.proxied})
        status, msg, prid = result["status"], result["message"], result.get("provider_record_id")
    except Exception as e:
        status, msg, prid = "failed", f"同步失败：{e}", None
    conn.execute(
        """UPDATE dns_records SET type=?,name=?,value=?,ttl=?,priority=?,proxied=?,
           provider_record_id=?,sync_status=?,sync_message=? WHERE id=?""",
        (t, name, val, body.ttl, body.priority, 1 if body.proxied else 0, prid, status, msg, record_id),
    )
    return {"record": dict(conn.execute("SELECT * FROM dns_records WHERE id=?", (record_id,)).fetchone()),
            "message": msg}


@router.delete("/{record_id}")
def delete_record(domain_id: int, record_id: int, user=Depends(current_user), conn=Depends(_db)):
    d = _owned(conn, domain_id, user)
    row = conn.execute("SELECT * FROM dns_records WHERE id=? AND domain_id=?",
                       (record_id, domain_id)).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在")
    if row["provider_record_id"]:
        try:
            get_provider(conn).delete_record(row["provider_record_id"], _fqdn(d, row["name"]))
        except Exception:
            pass
    conn.execute("DELETE FROM dns_records WHERE id=?", (record_id,))
    return {"ok": True}


@router.post("/{record_id}/sync")
def resync(domain_id: int, record_id: int, user=Depends(current_user), conn=Depends(_db)):
    d = _owned(conn, domain_id, user)
    row = conn.execute("SELECT * FROM dns_records WHERE id=? AND domain_id=?",
                       (record_id, domain_id)).fetchone()
    if not row:
        raise HTTPException(404, "记录不存在")
    prov = get_provider(conn)
    try:
        res = prov.create_record(_fqdn(d, row["name"]),
                                 {"type": row["type"], "value": row["value"], "ttl": row["ttl"],
                                  "priority": row["priority"], "proxied": bool(row["proxied"])})
        conn.execute(
            "UPDATE dns_records SET provider_record_id=?, sync_status=?, sync_message=? WHERE id=?",
            (res.get("provider_record_id"), res["status"], res["message"], record_id),
        )
        return {"ok": True, "message": res["message"], "provider": prov.name}
    except Exception as e:
        conn.execute("UPDATE dns_records SET sync_status='failed', sync_message=? WHERE id=?",
                     (f"同步失败：{e}", record_id))
        raise HTTPException(400, f"同步失败：{e}")
