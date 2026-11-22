"""密码哈希、JWT、API Key、时间工具。"""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
SECRET_FILE = os.path.join(DATA_DIR, ".secret_key")

TZ = timezone(timedelta(hours=8))  # 固定按北京时间展示
JWT_ALGO = "HS256"
TOKEN_TTL_HOURS = int(os.environ.get("SDH_TOKEN_TTL_HOURS", "72"))

PBKDF2_ITER = 260_000


def _secret_key() -> str:
    env = os.environ.get("SDH_SECRET_KEY")
    if env:
        return env
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "r", encoding="utf-8") as f:
            key = f.read().strip()
            if key:
                return key
    key = secrets.token_urlsafe(48)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SECRET_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    return key


SECRET_KEY = _secret_key()


# ---------- 时间 ----------
def now_dt() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now_dt().replace(microsecond=0).isoformat()


def parse_iso(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def days_left(expires_at: str) -> int:
    dt = parse_iso(expires_at)
    if not dt:
        return 0
    return max(0, (dt - now_dt()).days)


# ---------- 密码 ----------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITER)
    return "pbkdf2${}${}${}".format(
        PBKDF2_ITER, base64.b64encode(salt).decode(), base64.b64encode(dk).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ---------- JWT ----------
def create_access_token(user_id: int, role: str) -> str:
    exp = now_dt() + timedelta(hours=TOKEN_TTL_HOURS)
    payload = {"sub": str(user_id), "role": role, "exp": exp, "iat": now_dt()}
    return jwt.encode(payload, SECRET_KEY, algorithm=JWT_ALGO)


def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGO])
    except Exception:
        return None


# ---------- Keys / IDs ----------
def gen_api_key() -> str:
    return "sdh_" + secrets.token_urlsafe(32)


def gen_order_no() -> str:
    return "SD" + now_dt().strftime("%Y%m%d%H%M%S") + secrets.token_hex(3).upper()


def gen_token(n: int = 24) -> str:
    return secrets.token_urlsafe(n)
