"""用户维度统计汇总。"""
from datetime import timedelta

from fastapi import APIRouter, Depends

from ..deps import _db, current_user
from ..security import now_dt
from ..services import sync_expired

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def overview(days: int = 14, user=Depends(current_user), conn=Depends(_db)):
    sync_expired(conn)
    days = max(1, min(365, days))
    uid = user["id"]
    today = now_dt().strftime("%Y-%m-%d")
    start = (now_dt() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    total_hits = conn.execute(
        "SELECT COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id WHERE d.user_id=?",
        (uid,),
    ).fetchone()["c"]
    today_hits = conn.execute(
        "SELECT COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id WHERE d.user_id=? AND v.day=?",
        (uid, today),
    ).fetchone()["c"]
    period_hits = conn.execute(
        "SELECT COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id WHERE d.user_id=? AND v.day>=?",
        (uid, start),
    ).fetchone()["c"]

    series = {}
    for i in range(days):
        series[(now_dt() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")] = 0
    for r in conn.execute(
        "SELECT v.day AS day, COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id "
        "WHERE d.user_id=? AND v.day>=? GROUP BY v.day", (uid, start),
    ):
        series[r["day"]] = r["c"]

    domain_total = conn.execute("SELECT COUNT(*) AS c FROM domains WHERE user_id=?", (uid,)).fetchone()["c"]
    domain_active = conn.execute(
        "SELECT COUNT(*) AS c FROM domains WHERE user_id=? AND status='active'", (uid,)).fetchone()["c"]
    domain_pending = conn.execute(
        "SELECT COUNT(*) AS c FROM domains WHERE user_id=? AND status='pending'", (uid,)).fetchone()["c"]
    expiring = conn.execute(
        "SELECT COUNT(*) AS c FROM domains WHERE user_id=? AND status='active' AND expires_at IS NOT NULL "
        "AND expires_at <= ?", (uid, (now_dt() + timedelta(days=15)).replace(microsecond=0).isoformat()),
    ).fetchone()["c"]

    top = conn.execute(
        """SELECT d.fqdn AS name, COUNT(v.id) AS count FROM domains d
           LEFT JOIN visits v ON v.domain_id=d.id
           WHERE d.user_id=? GROUP BY d.id ORDER BY count DESC, d.id DESC LIMIT 8""",
        (uid,),
    ).fetchall()

    def group(col_join):
        return [{"name": r["v"] or "直接访问", "count": r["c"]} for r in conn.execute(
            f"SELECT {col_join} AS v, COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id "
            f"WHERE d.user_id=? AND v.day>=? GROUP BY v ORDER BY c DESC LIMIT 8",
            (uid, start))]

    devices = [{"name": {"mobile": "移动端", "desktop": "桌面端", "tablet": "平板",
                         "bot": "爬虫", "unknown": "未知"}.get(r["v"], r["v"] or "未知"), "count": r["c"]}
               for r in conn.execute(
        "SELECT v.device AS v, COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id "
        "WHERE d.user_id=? AND v.day>=? GROUP BY v ORDER BY c DESC LIMIT 6", (uid, start))]
    referers = [{"name": (r["v"] or "直接访问")[:40], "count": r["c"]} for r in conn.execute(
        "SELECT v.referer AS v, COUNT(*) AS c FROM visits v JOIN domains d ON d.id=v.domain_id "
        "WHERE d.user_id=? AND v.day>=? GROUP BY v ORDER BY c DESC LIMIT 6", (uid, start))]

    return {
        "domain_total": domain_total, "domain_active": domain_active, "domain_pending": domain_pending,
        "expiring_soon": expiring,
        "today_hits": today_hits, "total_hits": total_hits, "period_hits": period_hits,
        "series": [{"day": k, "count": v} for k, v in series.items()],
        "top_domains": [{"name": r["name"], "count": r["count"]} for r in top],
        "devices": devices, "referers": referers,
    }
