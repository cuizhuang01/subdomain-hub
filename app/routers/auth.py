"""认证相关接口：注册、登录、当前用户、改密码、充值。"""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .. import settings_store
from ..deps import _db, current_user
from ..security import (create_access_token, gen_order_no, hash_password, now_iso,
                        verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6, max_length=64)
    name: str = Field(min_length=1, max_length=32)


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=64)


class RechargeIn(BaseModel):
    amount: float = Field(gt=0, le=10000)


def _public_user(u: dict) -> dict:
    return {k: u[k] for k in ("id", "email", "name", "role", "status", "balance", "created_at")}


@router.post("/register")
def register(body: RegisterIn, conn=Depends(_db)):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "邮箱格式不正确")
    if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(400, "该邮箱已注册")
    conn.execute(
        "INSERT INTO users (email,password_hash,name,role,status,balance,created_at) VALUES (?,?,?,?,?,?,?)",
        (email, hash_password(body.password), body.name.strip(), "user", "active", 0, now_iso()),
    )
    uid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    user = dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    token = create_access_token(user["id"], user["role"])
    return {"token": token, "user": _public_user(user)}


@router.post("/login")
def login(body: LoginIn, response: Response, conn=Depends(_db)):
    email = body.email.strip().lower()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "邮箱或密码错误")
    if row["status"] == "banned":
        raise HTTPException(403, "账号已被封禁")
    user = dict(row)
    token = create_access_token(user["id"], user["role"])
    response.set_cookie("sdh_token", token, httponly=True, samesite="lax", max_age=72 * 3600)
    return {"token": token, "user": _public_user(user)}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("sdh_token")
    return {"ok": True}


@router.get("/me")
def me(user=Depends(current_user)):
    return _public_user(user)


@router.post("/password")
def change_password(body: PasswordIn, user=Depends(current_user), conn=Depends(_db)):
    if not verify_password(body.old_password, user["password_hash"]):
        raise HTTPException(400, "原密码不正确")
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (hash_password(body.new_password), user["id"]))
    return {"ok": True}


@router.post("/recharge")
def recharge(body: RechargeIn, user=Depends(current_user), conn=Depends(_db)):
    """演示环境的模拟充值（生产环境应接入支付网关回调）。"""
    amount = round(body.amount, 2)
    conn.execute("UPDATE users SET balance=balance+? WHERE id=?", (amount, user["id"]))
    conn.execute(
        """INSERT INTO orders (order_no,user_id,domain_id,kind,years,amount,status,created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (gen_order_no(), user["id"], None, "recharge", 0, amount, "paid", now_iso()),
    )
    bal = conn.execute("SELECT balance FROM users WHERE id=?", (user["id"],)).fetchone()["balance"]
    return {"ok": True, "balance": bal, "demo": True}


@router.get("/public-config")
def public_config(conn=Depends(_db)):
    return {
        "site_name": settings_store.get(conn, "site_name"),
        "main_domain": settings_store.get(conn, "main_domain"),
        "price_per_year": settings_store.get_float(conn, "price_per_year"),
        "notice": settings_store.get(conn, "notice"),
        "dns_provider": settings_store.get(conn, "dns_provider"),
        "auto_approve": settings_store.get_bool(conn, "auto_approve", True),
        "max_domains_per_user": settings_store.get_int(conn, "max_domains_per_user", 10),
        "default_years": settings_store.get_int(conn, "default_years", 1),
    }
