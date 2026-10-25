"""周报生成器：产出可直接发博客/Newsletter 的 Markdown 周报。

内容三块：本周新上榜（有强收款信号的站）/ 本周入库 / 完整榜单 Top N。
文件：data/weekly-YYYY-MM-DD.md
"""
import json
import time
from pathlib import Path

from db import connect, all_scanned
from estimate import signal_tier

OUT_DIR = Path(__file__).parent / "data"
WEEK = 7 * 86400
TOP_N = 20


def run() -> None:
    now = time.time()
    conn = connect()
    fresh = conn.execute(
        "SELECT * FROM sites WHERE last_scan_at >= ? AND scan_status = 'ok'"
        " AND status = 'active' ORDER BY last_scan_at DESC", (now - WEEK,)).fetchall()
    added = conn.execute(
        "SELECT COUNT(*) AS c FROM sites WHERE discovered_at >= ?", (now - WEEK,)).fetchone()["c"]
    top = all_scanned(conn)
    conn.close()

    new_ranked = [r for r in fresh if json.loads(r["payment_channels"])]
    ts = time.strftime("%Y-%m-%d")

    # 同时写 docs/（随静态站一起发布）与 data/（本地存档）
    docs_dir = Path(__file__).parent / "docs"
    docs_dir.mkdir(exist_ok=True)
    path = docs_dir / f"weekly-{ts}.md"
    archive = OUT_DIR / f"weekly-{ts}.md"
    content = f"""# AI 站点情报周报（{ts}）

> 本周新入库 {added} 个站点。收款信号 = 公开支付渠道痕迹，非真实营收。

## 🆕 本周新上榜（检测到收款信号）

"""
    if new_ranked:
        content += "| 站点 | 渠道 | 定价页 | 简介 |\n|---|---|---|---|\n"
        for r in new_ranked:
            channels = ", ".join(json.loads(r["payment_channels"]))
            desc = (r["description"] or r["name"] or "-").replace("|", "/")[:40]
            content += f"| {r['domain']} | {channels} | {'✓' if r['has_pricing'] else '—'} | {desc} |\n"
    else:
        content += "本周暂无新检测到收款信号的站点。\n"

    content += f"\n## 📊 收款信号榜 Top {TOP_N}\n\n"
    ranked = sorted(top, key=lambda r: -r["revenue_signal"])[:TOP_N]
    if ranked:
        content += "| # | 站点 | 信号强度 | 估算月收款$ |\n|---|---|---|---|\n"
        for i, r in enumerate(ranked, 1):
            channels = json.loads(r["payment_channels"])
            weak = json.loads(r["weak_channels"] if "weak_channels" in r.keys() else "[]")
            tier = signal_tier(channels, weak, bool(r["has_pricing"]), r["min_price_usd"])
            content += f"| {i} | {r['domain']} | {tier} | {r['revenue_signal']:.0f} |\n"
    else:
        content += "暂无数据。\n"

    content += "\n---\n*要求下榜请联系我们。数据每周更新。*\n"
    path.write_text(content, encoding="utf-8")
    archive.write_text(content, encoding="utf-8")
    _write_rss()
    print(f"周报已生成：{path}")
    print(f"周报存档：{archive}")


def _write_rss() -> None:
    """从 data/weekly-*.md 生成 docs/feed.xml（RSS 订阅）。"""
    from xml.sax.saxutils import escape
    base = "https://zhangmingjava.github.io/ai-station-intel/"
    items = []
    for f in sorted(OUT_DIR.glob("weekly-*.md"), reverse=True)[:10]:
        ts = f.stem.replace("weekly-", "")
        try:
            import datetime
            dt = datetime.datetime.strptime(ts, "%Y-%m-%d")
            pub = dt.strftime("%a, %d %b %Y 08:00:00 +0800")
        except ValueError:
            pub = ""
        body = escape(f.read_text(encoding="utf-8")[:2000])
        items.append(
            f"<item><title>AI 站点情报周报（{ts}）</title>"
            f"<link>{base}weekly-{ts}.md</link>"
            f"<guid>{base}weekly-{ts}.md</guid>"
            f"<pubDate>{pub}</pubDate>"
            f"<description>{body}</description></item>")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<rss version="2.0"><channel>'
           '<title>AI 站点收款信号榜 · 周报</title>'
           f'<link>{base}</link>'
           '<description>每周新上榜的 AI 工具站与收款信号变化</description>'
           '<language>zh-CN</language>'
           + "".join(items) + "</channel></rss>")
    (Path(__file__).parent / "docs" / "feed.xml").write_text(xml, encoding="utf-8")
    print("RSS 已生成：docs/feed.xml")


if __name__ == "__main__":
    run()
