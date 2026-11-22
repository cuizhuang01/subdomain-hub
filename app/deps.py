"""认证与权限依赖。"""
from fastapi import Depends, Header, HTTPException, Request

from .db import get_conn
from .security import decode_token, now_iso


def _db():
    with get_conn() as conn:
        yield conn


def _extract_token(request: Request, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    token = request.cookies.get("sdh_token")
    return token


def current_user(request: Request, conn=Depends(_db),
                 authorization: str | None = Header(default=None)):
    token = _extract_token(request, authorization)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    try:
        uid = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="无效的身份凭证")
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在")
    if user["status"] == "banned":
        raise HTTPException(status_code=403, detail="账号已被封禁，请联系管理员")
    return dict(user)


def current_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def api_key_auth(conn=Depends(_db), x_api_key: str | None = Header(default=None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key")
    row = conn.execute(
        "SELECT k.*, u.name AS user_name, u.status AS user_status FROM api_keys k "
        "JOIN users u ON u.id=k.user_id WHERE k.key=? AND k.status='active'",
        (x_api_key,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="API Key 无效或已停用")
    if row["user_status"] == "banned":
        raise HTTPException(status_code=403, detail="账号已被封禁")
    conn.execute("UPDATE api_keys SET last_used_at=? WHERE id=?", (now_iso(), row["id"]))
    user = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
    return dict(user)
