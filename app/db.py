"""SQLite 数据访问层（零 ORM 依赖）。"""
import os
import random
import sqlite3
from datetime import timedelta
import threading
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.environ.get("SDH_DB", os.path.join(DATA_DIR, "app.db"))

_init_lock = threading.Lock()
_init_done = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',          -- user / admin
    status TEXT NOT NULL DEFAULT 'active',      -- active / banned
    balance REAL NOT NULL DEFAULT 0,            -- 账户余额（演示充值）
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prefix TEXT NOT NULL,
    fqdn TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL DEFAULT 'redirect',   -- redirect / dns
    target_url TEXT,
    redirect_type INTEGER NOT NULL DEFAULT 302, -- 301 / 302
    status TEXT NOT NULL DEFAULT 'pending',     -- pending / active / rejected / suspended / expired
    note TEXT,
    reject_reason TEXT,
    hit_count INTEGER NOT NULL DEFAULT 0,
    last_hit_at TEXT,
    auto_renew INTEGER NOT NULL DEFAULT 0,
    expires_at TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT
);

CREATE TABLE IF NOT EXISTS dns_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    type TEXT NOT NULL,                         -- A / AAAA / CNAME / TXT / MX
    name TEXT NOT NULL DEFAULT '@',
    value TEXT NOT NULL,
    ttl INTEGER NOT NULL DEFAULT 600,
    priority INTEGER NOT NULL DEFAULT 10,
    proxied INTEGER NOT NULL DEFAULT 0,
    provider_record_id TEXT,
    sync_status TEXT NOT NULL DEFAULT 'pending',-- pending / synced / failed / manual
    sync_message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL REFERENCES domains(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    ip TEXT,
    country TEXT,
    device TEXT,
    referer TEXT,
    path TEXT,
    ua TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    last_used_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    domain_id INTEGER REFERENCES domains(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,                         -- renew / recharge
    years INTEGER NOT NULL DEFAULT 1,
    amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'paid',        -- paid / pending / cancelled
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    actor_name TEXT,
    action TEXT NOT NULL,
    target TEXT,
    detail TEXT,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visits_domain_day ON visits(domain_id, day);
CREATE INDEX IF NOT EXISTS idx_domains_user ON domains(user_id);
CREATE INDEX IF NOT EXISTS idx_domains_status ON domains(status);
CREATE INDEX IF NOT EXISTS idx_dns_domain ON dns_records(domain_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """建表 + 首次写入种子数据。幂等。"""
    global _init_done
    with _init_lock:
        conn = _connect()
        try:
            conn.executescript(SCHEMA)
            conn.commit()
            _seed(conn)
            conn.commit()
            _init_done = True
        finally:
            conn.close()


def _seed(conn: sqlite3.Connection):
    from .security import hash_password, now_dt, now_iso
    from . import settings_store

    settings_store.bootstrap(conn)

    cur = conn.execute("SELECT COUNT(*) AS c FROM users")
    if cur.fetchone()["c"] > 0:
        return

    now = now_iso()
    conn.execute(
        "INSERT INTO users (email,password_hash,name,role,status,balance,created_at) VALUES (?,?,?,?,?,?,?)",
        ("admin@sdh.local", hash_password("admin123"), "系统管理员", "admin", "active", 0, now),
    )
    conn.execute(
        "INSERT INTO users (email,password_hash,name,role,status,balance,created_at) VALUES (?,?,?,?,?,?,?)",
        ("demo@sdh.local", hash_password("demo1234"), "演示用户", "user", "active", 100, now),
    )
    demo_id = conn.execute("SELECT id FROM users WHERE email='demo@sdh.local'").fetchone()["id"]
    main_domain = settings_store.get(conn, "main_domain")
    conn.execute(
        """INSERT INTO domains (user_id,prefix,fqdn,purpose,target_url,redirect_type,status,note,
                               hit_count,expires_at,created_at,activated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (demo_id, "go", f"go.{main_domain}", "redirect", "https://www.doubao.com", 302,
         "active", "官方演示域名", 0, "2027-11-22T00:00:00+08:00", now, now),
    )
    demo_corp = conn.execute("SELECT id FROM users WHERE email='admin@sdh.local'").fetchone()["id"]
    conn.execute(
        """INSERT INTO domains (user_id,prefix,fqdn,purpose,target_url,redirect_type,status,note,
                               hit_count,expires_at,created_at,activated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (demo_corp, "docs", f"docs.{main_domain}", "dns", None, 302,
         "active", "文档站（解析托管示例）", 0, "2027-11-22T00:00:00+08:00", now, now),
    )
    docs_id = conn.execute("SELECT id FROM domains WHERE prefix='docs'").fetchone()["id"]
    conn.execute(
        """INSERT INTO dns_records (domain_id,type,name,value,ttl,provider_record_id,
                                   sync_status,sync_message,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (docs_id, "A", "@", "203.0.113.10", 600, None, "manual", "本地托管，未同步到 DNS 服务商", now),
    )
    conn.execute(
        """INSERT INTO dns_records (domain_id,type,name,value,ttl,provider_record_id,
                                   sync_status,sync_message,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (docs_id, "CNAME", "www", "docs.example.com", 600, None, "manual", "本地托管，未同步到 DNS 服务商", now),
    )

    # 过去 14 天的演示访问数据，用于让统计图表开箱即有内容
    import random
    random.seed(20261122)
    go_id = conn.execute("SELECT id FROM domains WHERE prefix='go'").fetchone()["id"]
    devices = ["mobile", "mobile", "mobile", "desktop", "desktop", "tablet", "bot"]
    referers = ["https://www.baidu.com/", "https://www.google.com/", "", "",
                "https://weibo.com/", "https://www.doubao.com/"]
    countries = ["CN", "CN", "CN", "CN", "HK", "US", "SG"]
    total = 0
    base = now_dt()
    for days_ago in range(13, -1, -1):
        n = max(0, int(random.gauss(12, 6)))
        for _ in range(n):
            ts = (base - timedelta(days=days_ago, hours=random.randint(0, 23),
                                   minutes=random.randint(0, 59))).replace(microsecond=0)
            conn.execute(
                """INSERT INTO visits (domain_id,ts,day,ip,country,device,referer,path,ua)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (go_id, ts.isoformat(), ts.strftime("%Y-%m-%d"),
                 f"203.0.113.{random.randint(1, 254)}", random.choice(countries),
                 random.choice(devices), random.choice(referers), "/",
                 "Mozilla/5.0 (demo seed)"),
            )
            total += 1
    conn.execute("UPDATE domains SET hit_count=?, last_hit_at=? WHERE id=?",
                 (total, now, go_id))
    conn.execute(
        """INSERT INTO audit_logs (actor_id,actor_name,action,target,detail,ts)
           VALUES (?,?,?,?,?,?)""",
        (None, "system", "bootstrap", "system", "初始化系统与演示数据", now),
    )


def rows_to_dicts(rows):
    return [dict(r) for r in rows]
