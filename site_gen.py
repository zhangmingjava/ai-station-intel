"""静态榜单页生成器：产出 docs/index.html，GitHub Pages 选 docs/ 目录即可直接访问。

自包含单页（无构建、无依赖），每次数据更新后重新运行覆盖。
"""
import html
import json
import time
from pathlib import Path

from db import connect, all_scanned
from estimate import signal_tier

OUT_DIR = Path(__file__).parent / "docs"
TIER_ORDER = {"A": 0, "B": 1, "C": 2, "C-": 3, "D": 4}


def _tier_prefix(tier: str) -> str:
    return tier.split("（")[0]


def run() -> None:
    conn = connect()
    rows = all_scanned(conn)
    conn.close()
    ranked = sorted(rows, key=lambda r: (TIER_ORDER.get(_tier_prefix(
        signal_tier(json.loads(r["payment_channels"]),
                    json.loads(r["weak_channels"] if "weak_channels" in r.keys() else "[]"),
                    bool(r["has_pricing"]), r["min_price_usd"])), 9),
        -r["revenue_signal"]))

    def row_html(i: int, r) -> str:
        channels = json.loads(r["payment_channels"])
        weak = json.loads(r["weak_channels"] if "weak_channels" in r.keys() else "[]")
        tier = signal_tier(channels, weak, bool(r["has_pricing"]), r["min_price_usd"])
        shown = ", ".join(c.capitalize() for c in channels)
        if not shown and weak:
            shown = ", ".join(c.capitalize() for c in weak) + "（弱信号）"
        shown = html.escape(shown) or "—"
        desc = html.escape((r["description"] or r["name"] or "")[:60])
        prefix = _tier_prefix(tier)
        cls = {"A": "tier-a", "B": "tier-b", "C": "tier-c"}.get(prefix, "tier-d")
        return (f"<tr class='{cls}'><td>{i}</td>"
                f"<td><a href='https://{html.escape(r['domain'])}' target='_blank' rel='noopener'>"
                f"{html.escape(r['domain'])}</a><br><small>{desc}</small></td>"
                f"<td>{shown}</td><td>{'✓' if r['has_pricing'] else '—'}</td>"
                f"<td>{tier}</td><td>{r['revenue_signal']:,.0f}</td></tr>")

    ts = time.strftime("%Y-%m-%d")
    body_rows = "\n".join(row_html(i, r) for i, r in enumerate(ranked, 1)) or \
        "<tr><td colspan='6'>数据探测中，敬请期待</td></tr>"
    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 站点收款信号榜</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:#0d1117; color:#e6edf3; line-height:1.6; }}
main {{ max-width:1080px; margin:0 auto; padding:48px 20px; }}
h1 {{ font-size:1.9rem; margin:0 0 8px; }}
.sub {{ color:#8b949e; margin-bottom:32px; }}
table {{ width:100%; border-collapse:collapse; font-size:.92rem; }}
th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #21262d; vertical-align:top; }}
th {{ color:#8b949e; font-weight:500; position:sticky; top:0; background:#0d1117; }}
tr:hover {{ background:#161b22; }}
a {{ color:#58a6ff; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
small {{ color:#8b949e; }}
.tier-a td:first-child {{ box-shadow:inset 3px 0 0 #3fb950; }}
.tier-b td:first-child {{ box-shadow:inset 3px 0 0 #d29922; }}
.tier-c td:first-child {{ box-shadow:inset 3px 0 0 #58a6ff; }}
.tier-d td:first-child {{ box-shadow:inset 3px 0 0 #30363d; }}
footer {{ margin-top:40px; color:#8b949e; font-size:.85rem; border-top:1px solid #21262d; padding-top:20px; }}
.badge {{ display:inline-block; background:#21262d; border-radius:20px; padding:2px 12px;
  font-size:.8rem; color:#8b949e; margin-right:8px; }}
</style></head><body><main>
<h1>AI 站点收款信号榜</h1>
<div class="sub">持续追踪 AI 工具站的公开收款信号与流量表现 · 每周更新</div>
<div style="margin-bottom:24px">
  <span class="badge">已收录 {len(rows)} 站</span>
  <span class="badge">更新于 {ts}</span>
</div>
<table><thead><tr>
<th>#</th><th>站点</th><th>收款渠道</th><th>定价页</th><th>信号强度</th><th>估算月收款 $</th>
</tr></thead><tbody>
{body_rows}
</tbody></table>
<footer>
<p><strong>数据口径说明：</strong>"收款信号"来自对站点公开页面支付渠道痕迹（Stripe / Paddle /
Creem / Dodo 等）与定价页的自动探测，估算金额基于公开信号与行业基准推算，
<strong>不代表任何站点的真实营收</strong>。</p>
<p>如果你的站点希望下榜，或信息有误需要更正，请通过 <a href="mailto:hello@example.com">hello@example.com</a> 联系我们，无条件立即处理。</p>
<p>© {time.strftime("%Y")} AI Station Intel · 数据每周自动更新</p>
</footer>
</main></body></html>"""

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"静态页已生成：{out}")


if __name__ == "__main__":
    run()
