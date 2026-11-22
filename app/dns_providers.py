"""DNS 服务商适配层：手动 / Cloudflare / 阿里云 DNS。

真实对接需要配置 API 凭据；未配置时自动降级为 manual（仅本地托管记录）。
"""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from . import settings_store


class ProviderError(Exception):
    pass


class BaseProvider:
    name = "manual"
    label = "本地托管（不写入真实 DNS）"

    def __init__(self, conn):
        self.conn = conn

    @property
    def configured(self) -> bool:
        return True

    def create_record(self, fqdn_sub: str, rec: dict) -> dict:
        return {"provider_record_id": None, "status": "manual", "message": "本地托管，未同步到 DNS 服务商"}

    def delete_record(self, record_id: str, fqdn_sub: str) -> dict:
        return {"status": "manual", "message": "本地托管，无需删除远程记录"}


# ---------------- Cloudflare ----------------
class CloudflareProvider(BaseProvider):
    name = "cloudflare"
    label = "Cloudflare"
    API = "https://api.cloudflare.com/client/v4"

    @property
    def configured(self) -> bool:
        return bool(settings_store.get(self.conn, "cf_api_token")) and bool(
            settings_store.get(self.conn, "cf_zone_id")
        )

    def _headers(self):
        return {
            "Authorization": f"Bearer {settings_store.get(self.conn, 'cf_api_token')}",
            "Content-Type": "application/json",
        }

    def create_record(self, fqdn_sub: str, rec: dict) -> dict:
        zone = settings_store.get(self.conn, "cf_zone_id")
        body = {
            "type": rec["type"],
            "name": fqdn_sub,
            "content": rec["value"],
            "ttl": max(60, int(rec.get("ttl") or 600)),
            "proxied": bool(rec.get("proxied")),
        }
        if rec["type"] == "MX":
            body["priority"] = int(rec.get("priority") or 10)
        r = requests.post(f"{self.API}/zones/{zone}/dns_records", headers=self._headers(),
                          json=body, timeout=12)
        data = r.json()
        if r.status_code >= 300 or not data.get("success"):
            errs = data.get("errors") or [{"message": f"HTTP {r.status_code}"}]
            raise ProviderError("; ".join(e.get("message", "") for e in errs))
        return {"provider_record_id": data["result"]["id"], "status": "synced",
                "message": "已同步到 Cloudflare"}

    def delete_record(self, record_id: str, fqdn_sub: str) -> dict:
        zone = settings_store.get(self.conn, "cf_zone_id")
        r = requests.delete(f"{self.API}/zones/{zone}/dns_records/{record_id}",
                            headers=self._headers(), timeout=12)
        if r.status_code >= 300:
            raise ProviderError(f"Cloudflare 删除失败 HTTP {r.status_code}")
        return {"status": "synced", "message": "已从 Cloudflare 删除"}


# ---------------- 阿里云 DNS ----------------
class AliyunProvider(BaseProvider):
    name = "aliyun"
    label = "阿里云 DNS"
    ENDPOINT = "https://alidns.aliyuncs.com/"

    @property
    def configured(self) -> bool:
        return bool(settings_store.get(self.conn, "aliyun_access_key_id")) and bool(
            settings_store.get(self.conn, "aliyun_access_key_secret")
        )

    @staticmethod
    def _percent(s: str) -> str:
        return quote(str(s), safe="~")

    def _sign(self, params: dict, method: str = "GET") -> str:
        cqs = "&".join(
            f"{self._percent(k)}={self._percent(params[k])}"
            for k in sorted(params)
        )
        string_to_sign = f"{method}&{self._percent('/')}&{self._percent(cqs)}"
        secret = settings_store.get(self.conn, "aliyun_access_key_secret") + "&"
        digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        return base64.b64encode(digest).decode()

    def _call(self, action: str, extra: dict) -> dict:
        params = {
            "AccessKeyId": settings_store.get(self.conn, "aliyun_access_key_id"),
            "Action": action,
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureNonce": str(uuid.uuid4()),
            "SignatureVersion": "1.0",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "Version": "2015-01-09",
        }
        params.update(extra)
        params["Signature"] = self._sign(params, "GET")
        r = requests.get(self.ENDPOINT, params=params, timeout=12)
        try:
            data = r.json()
        except Exception:
            raise ProviderError(f"阿里云返回非 JSON：HTTP {r.status_code}")
        if r.status_code >= 300 or "Code" in data:
            raise ProviderError(f"{data.get('Code', r.status_code)}: {data.get('Message', '请求失败')}")
        return data

    def create_record(self, fqdn_sub: str, rec: dict) -> dict:
        zone = settings_store.get(self.conn, "main_domain")
        rr = fqdn_sub[: -(len(zone) + 1)] if fqdn_sub.endswith("." + zone) else fqdn_sub
        extra = {
            "DomainName": zone,
            "RR": rr,
            "Type": rec["type"],
            "Value": rec["value"],
            "TTL": max(600, int(rec.get("ttl") or 600)),
        }
        if rec["type"] == "MX":
            extra["Priority"] = int(rec.get("priority") or 10)
        data = self._call("AddDomainRecord", extra)
        return {"provider_record_id": data.get("RecordId"), "status": "synced",
                "message": "已同步到阿里云 DNS"}

    def delete_record(self, record_id: str, fqdn_sub: str) -> dict:
        self._call("DeleteDomainRecord", {"RecordId": record_id})
        return {"status": "synced", "message": "已从阿里云 DNS 删除"}


PROVIDERS = {
    "manual": BaseProvider,
    "cloudflare": CloudflareProvider,
    "aliyun": AliyunProvider,
}


def get_provider(conn) -> BaseProvider:
    name = settings_store.get(conn, "dns_provider") or "manual"
    cls = PROVIDERS.get(name, BaseProvider)
    p = cls(conn)
    if not p.configured:
        return BaseProvider(conn)
    return p


def provider_info(conn) -> list:
    out = []
    current = settings_store.get(conn, "dns_provider") or "manual"
    for key, cls in PROVIDERS.items():
        inst = cls(conn)
        out.append({
            "key": key, "label": cls.label, "configured": inst.configured,
            "current": key == current,
        })
    return out
