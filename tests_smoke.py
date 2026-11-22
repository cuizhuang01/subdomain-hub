"""端到端冒烟测试：无需 pytest，直接 python3 tests_smoke.py（服务需已在 8000 端口运行）。"""
import random
import string
import sys

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ok, fail = 0, 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  ✓ {name}")
    else:
        fail += 1
        print(f"  ✗ {name} {extra}")


def main():
    rnd = "".join(random.choice(string.ascii_lowercase) for _ in range(5))
    email = f"u{rnd}@test.local"
    print("== 注册 / 登录 ==")
    r = requests.post(f"{BASE}/api/auth/register", json={"email": email, "password": "pass1234", "name": f"测试{rnd}"})
    check("注册", r.status_code == 200, r.text[:120])
    token = r.json()["token"]
    H = {"Authorization": f"Bearer {token}"}

    check("获取当前用户", requests.get(f"{BASE}/api/auth/me", headers=H).status_code == 200)

    print("== 域名申请 ==")
    prefix = "t" + rnd
    r = requests.get(f"{BASE}/api/domains/check", params={"prefix": prefix})
    check("可用性检测", r.json()["available"] is True, r.text[:100])
    r = requests.post(f"{BASE}/api/domains", headers=H, json={
        "prefix": prefix, "purpose": "redirect", "target_url": "https://example.org/landing", "redirect_type": 302})
    check("创建跳转域名", r.status_code == 200, r.text[:160])
    did = r.json()["id"]
    fqdn = r.json()["fqdn"]

    r = requests.post(f"{BASE}/api/domains", headers=H, json={"prefix": prefix})
    check("重复前缀被拒", r.status_code == 400, r.text[:100])
    r = requests.post(f"{BASE}/api/domains", headers=H, json={"prefix": "api"})
    check("保留词被拒", r.status_code == 400, r.text[:100])

    print("== 网关跳转与统计 ==")
    host = fqdn
    r = requests.get(f"{BASE}/t/{prefix}", allow_redirects=False)
    check("本地测试入口跳转", r.status_code == 302 and "example.org" in r.headers.get("location", ""),
          f"{r.status_code} {r.headers.get('location')}")
    r = requests.get(f"{BASE}/", headers={"Host": host}, allow_redirects=False)
    check("按 Host 跳转 + 路径透传",
          r.status_code == 302 and "/deep/path" not in (r.headers.get("location") or ""),
          f"{r.status_code} {r.headers.get('location')}")
    r = requests.get(f"{BASE}/t/{prefix}/x?y=1", allow_redirects=False)
    check("路径与参数透传", "/x?y=1" in (r.headers.get("location") or ""), r.headers.get("location"))

    stats = requests.get(f"{BASE}/api/domains/{did}/stats?days=7", headers=H).json()
    check("访问统计累计", stats["total"] >= 1, str(stats["total"]))
    check("趋势序列 7 天", len(stats["series"]) == 7)
    visits = requests.get(f"{BASE}/api/domains/{did}/visits", headers=H).json()
    check("访问明细", len(visits["items"]) >= 1)

    print("== 修改 / DNS 托管 ==")
    r = requests.patch(f"{BASE}/api/domains/{did}", headers=H, json={"target_url": "https://example.net/new", "redirect_type": 301})
    check("修改跳转", r.json()["redirect_type"] == 301 and "example.net" in r.json()["target_url"])
    r2 = requests.get(f"{BASE}/t/{prefix}", allow_redirects=False)
    check("301 生效", r2.status_code == 301)

    r = requests.patch(f"{BASE}/api/domains/{did}", headers=H, json={"purpose": "dns"})
    check("切换为 DNS 托管", r.status_code == 200 and r.json()["purpose"] == "dns")
    r = requests.post(f"{BASE}/api/domains/{did}/dns", headers=H,
                      json={"type": "A", "name": "@", "value": "203.0.113.10", "ttl": 600})
    check("添加 A 记录", r.status_code == 200, r.text[:160])
    check("本地托管状态", r.json()["record"]["sync_status"] == "manual", r.json()["record"]["sync_status"])
    r = requests.post(f"{BASE}/api/domains/{did}/dns", headers=H,
                      json={"type": "A", "name": "@", "value": "not-an-ip"})
    check("非法 A 值被拒", r.status_code == 400)
    r = requests.post(f"{BASE}/api/domains/{did}/dns", headers=H,
                      json={"type": "CNAME", "name": "www", "value": "cdn.example.net"})
    check("添加 CNAME", r.status_code == 200)
    r = requests.get(f"{BASE}/t/{prefix}")
    check("DNS 托管页展示", "解析托管" in r.text)

    print("== 续费 ==")
    requests.post(f"{BASE}/api/auth/recharge", headers=H, json={"amount": 100})
    r = requests.post(f"{BASE}/api/domains/{did}/renew", headers=H, json={"years": 2})
    check("续费 2 年", r.status_code == 200 and r.json()["amount"] > 0, r.text[:160])
    r = requests.post(f"{BASE}/api/domains/{did}/renew", headers=H, json={"years": 5})
    check("余额不足拦截", r.status_code == 402 or r.status_code == 400, r.text[:100])

    print("== API Key ==")
    r = requests.post(f"{BASE}/api/keys", headers=H, json={"name": "冒烟测试"})
    check("创建 API Key", r.status_code == 200)
    key = r.json()["key"]
    r = requests.get(f"{BASE}/api/v1/domains", headers={"X-API-Key": key})
    check("v1 列表", r.status_code == 200 and len(r.json()["items"]) >= 1)
    r = requests.post(f"{BASE}/api/v1/domains", headers={"X-API-Key": key},
                      json={"prefix": "a" + rnd, "target_url": "https://example.com"})
    check("v1 创建域名", r.status_code == 200, r.text[:140])
    r = requests.get(f"{BASE}/api/v1/me", headers={"X-API-Key": "bad_key"})
    check("无效 Key 拦截", r.status_code == 401)

    print("== 权限 / 管理端 ==")
    r = requests.get(f"{BASE}/api/admin/overview", headers=H)
    check("普通用户访问后台被拒", r.status_code == 403)
    r = requests.post(f"{BASE}/api/auth/login", json={"email": "admin@sdh.local", "password": "admin123"})
    check("管理员登录", r.status_code == 200)
    AH = {"Authorization": f"Bearer {r.json()['token']}"}
    ov = requests.get(f"{BASE}/api/admin/overview", headers=AH).json()
    check("后台总览字段", all(k in ov for k in ("users", "domains", "pending", "revenue")))
    requests.put(f"{BASE}/api/admin/settings", headers=AH, json={"auto_approve": False})
    r = requests.post(f"{BASE}/api/domains", headers=H, json={"prefix": "p" + rnd})
    check("关闭自动审核后为待审", r.json()["status"] == "pending", r.text[:120])
    pid = r.json()["id"]
    r = requests.post(f"{BASE}/api/admin/domains/{pid}/approve", headers=AH)
    check("管理员审核通过", r.status_code == 200 and r.json()["domain"]["status"] == "active")
    r = requests.put(f"{BASE}/api/admin/settings", headers=AH, json={"auto_approve": True})
    check("恢复自动审核", r.status_code == 200)
    a = requests.get(f"{BASE}/api/admin/audit?size=5", headers=AH).json()
    check("审计日志", a["total"] >= 1)

    print(f"\n结果：{ok} 通过，{fail} 失败")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
