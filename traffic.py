"""流量数据回填：DataForSEO Labs bulk_traffic_metrics（月度自然流量估算）。

凭据：环境变量 DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD（https://app.dataforseo.com）
计费按次按 target 数计，脚本默认每批 100 个域名，只回填 visits_monthly=0 的站点。
"""
import base64
import json
import os

import requests

from db import connect

API_URL = "https://api.dataforseo.com/v3/dataforseo_labs/google/bulk_traffic_metrics/live"
BATCH = 100


def _auth() -> str | None:
    login, pwd = os.environ.get("DATAFORSEO_LOGIN"), os.environ.get("DATAFORSEO_PASSWORD")
    if not (login and pwd):
        return None
    return base64.b64encode(f"{login}:{pwd}".encode()).decode()


def fetch_traffic(domains: list[str]) -> dict[str, int]:
    """返回 {domain: 月度自然流量估算}。失败/无凭据返回空表。"""
    auth = _auth()
    if not auth:
        print("[dataforseo] 未设置 DATAFORSEO_LOGIN/PASSWORD，跳过（免费替代：手动录入）")
        return {}
    try:
        resp = requests.post(
            API_URL,
            json=[{"targets": domains, "location_name": "United States"}],
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
            timeout=60)
        resp.raise_for_status()
        items = resp.json()["tasks"][0]["result"][0]["items"]
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"[dataforseo] 请求失败: {e}")
        return {}
    out = {}
    for item in items:
        domain = str(item.get("target", "")).lower().removeprefix("www.")
        metrics = (item.get("metrics") or {}).get("organic") or {}
        traffic = int(metrics.get("traffic") or 0)
        if domain and traffic:
            out[domain] = traffic
    return out


def run() -> None:
    conn = connect()
    rows = conn.execute(
        "SELECT domain FROM sites WHERE visits_monthly = 0 AND scan_status = 'ok'"
        " AND status = 'active' LIMIT ?", (BATCH,)).fetchall()
    if not rows:
        print("[dataforseo] 没有待回填的站点")
        return
    domains = [r["domain"] for r in rows]
    traffic = fetch_traffic(domains)
    for domain, visits in traffic.items():
        conn.execute("UPDATE sites SET visits_monthly = ? WHERE domain = ?", (visits, domain))
    conn.commit()
    conn.close()
    print(f"[dataforseo] 请求 {len(domains)} 个，回填 {len(traffic)} 个站点的月流量估算")


if __name__ == "__main__":
    run()
