"""域名网关：按 Host 识别二级域名并执行跳转/解析展示，同时记录访问。"""
from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import settings_store
from ..db import get_conn
from ..security import now_dt
from ..services import record_visit

PAGE_TPL = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:flex;align-items:center;
justify-content:center;background:linear-gradient(135deg,#0f172a,#1e293b);font-family:-apple-system,
"PingFang SC",sans-serif;color:#e2e8f0;padding:24px}}
.card{{max-width:520px;width:100%;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);
border-radius:18px;padding:32px;backdrop-filter:blur(12px)}}
h1{{font-size:20px;margin:0 0 12px}}p{{color:#94a3b8;font-size:14px;line-height:1.8;margin:6px 0}}
.code{{display:inline-block;background:rgba(56,189,248,.12);color:#7dd3fc;border-radius:8px;
padding:4px 10px;font-family:ui-monospace,Menlo,monospace;font-size:13px;margin:6px 0}}
.btn{{display:inline-block;margin-top:18px;padding:10px 18px;border-radius:10px;background:#38bdf8;
color:#082f49;text-decoration:none;font-size:14px;font-weight:600}}
.foot{{margin-top:22px;font-size:12px;color:#64748b}}
</style></head><body><div class="card"><h1>{title}</h1><p>{body}</p>
{extra}<div class="foot">{site} · {time}</div></div></body></html>"""


def _page(title: str, body: str, extra: str = "", site: str = "二级域名分发平台") -> HTMLResponse:
    return HTMLResponse(PAGE_TPL.format(title=title, body=body, extra=extra, site=site,
                                        time=now_dt().strftime("%Y-%m-%d %H:%M")), status_code=200)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _extract_prefix(host: str, main_domain: str) -> str:
    """从 Host 中解析二级域名前缀；返回空字符串表示不是受管子域。"""
    host = (host or "").split(":")[0].strip().lower()
    if not host:
        return ""
    if host.endswith("." + main_domain):
        return host[: -(len(main_domain) + 1)]
    # 本地调试：abc.localhost
    if host.endswith(".localhost"):
        return host[: -len(".localhost")]
    return ""


def install_gateway(app):
    @app.middleware("http")
    async def gateway(request: Request, call_next):
        path = request.url.path
        if path.startswith(("/api/", "/static/", "/admin", "/docs", "/openapi.json", "/health")):
            return await call_next(request)

        with get_conn() as conn:
            main_domain = settings_store.get(conn, "main_domain").lower()
            site_name = settings_store.get(conn, "site_name")
            prefix = _extract_prefix(request.headers.get("host", ""), main_domain)

            # /t/{prefix} 手工测试入口（本地无法配置通配 DNS 时使用）
            if path.startswith("/t/") and not prefix:
                prefix = path.split("/")[2] if len(path.split("/")) > 2 else ""
                prefix = prefix.lower()

            if not prefix:
                return await call_next(request)

            prefix = prefix.split("/")[0].strip().lower()
            d = conn.execute("SELECT * FROM domains WHERE prefix=?", (prefix,)).fetchone()
            if not d:
                return _page("域名未分配", f"前缀 <span class='code'>{prefix}</span> 尚未被任何用户注册。",
                             f"<a class='btn' href='/'>前往申请</a>", site_name)
            d = dict(d)
            ip = _client_ip(request)
            ua = request.headers.get("user-agent", "")
            referer = request.headers.get("referer", "")
            country = request.headers.get("cf-ipcountry", "") or ""

            if d["status"] in ("pending", "rejected"):
                return _page("域名待审核", f"<span class='code'>{d['fqdn']}</span> 正在审核中，暂未开放访问。",
                             "", site_name)
            if d["status"] == "suspended":
                return _page("域名已停用", f"<span class='code'>{d['fqdn']}</span> 因违规或欠费被暂停使用。",
                             "", site_name)
            if d["status"] == "expired":
                return _page("域名已到期", f"<span class='code'>{d['fqdn']}</span> 已过期，请联系域名持有人续费。",
                             "", site_name)

            if d["purpose"] == "dns":
                recs = conn.execute(
                    "SELECT type,name,value FROM dns_records WHERE domain_id=? ORDER BY id", (d["id"],)
                ).fetchall()
                rows = "".join(
                    f"<p><span class='code'>{r['type']}</span> {r['name']} → {r['value']}</p>" for r in recs
                ) or "<p>该域名尚无解析记录。</p>"
                record_visit(conn, d["id"], ip, ua, referer, path, country)
                return _page("DNS 托管域名",
                             f"<span class='code'>{d['fqdn']}</span> 由本平台提供 DNS 解析托管。当前记录：",
                             rows, site_name)

            target = (d["target_url"] or "").strip()
            if not target:
                return _page("尚未配置跳转",
                             f"<span class='code'>{d['fqdn']}</span> 已激活，但持有人尚未设置跳转地址。",
                             "", site_name)

            record_visit(conn, d["id"], ip, ua, referer, path, country)
            suffix = "" if path in ("/", "") else path
            qs = request.url.query
            url = target + suffix + (("?" + qs) if qs else "")
            return RedirectResponse(url, status_code=d["redirect_type"] or 302)

    return app
