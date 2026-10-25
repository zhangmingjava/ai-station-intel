"""静态榜单页生成器：产出 docs/index.html（GitHub Pages 直接部署）。

版面：Hero + 数据总览 + 本周新上榜卡片墙 + 可筛选信号表 + 观察名单（折叠）+ 方法论。
自包含单页，无构建无依赖；数据更新后重跑覆盖。
"""
import html
import json
import time
from pathlib import Path

from db import connect, all_scanned
from estimate import signal_tier

OUT_DIR = Path(__file__).parent / "docs"
WEEK = 14 * 86400  # "新上榜"窗口

# 渠道徽标配色（品牌色近似）
CHANNEL_COLORS = {
    "stripe": "#635bff", "paddle": "#ff4f00", "creem": "#00d09c", "dodo": "#2d7ff9",
    "gumroad": "#ff90e8", "lemonsqueezy": "#7c3aed", "paypal": "#009cde", "polar": "#38bdf8",
}
TIER_BADGE = {"A": ("已验证收款", "#3fb950"), "B": ("收款信号强", "#d29922"),
              "C": ("收款信号", "#58a6ff"), "C-": ("观察中", "#8b949e"), "D": ("", "")}


def _favicon(domain: str) -> str:
    return f"https://www.google.com/s2/favicons?domain={domain}&sz=64"


def _channel_badges(channels: list[str], weak: list[str]) -> str:
    out = []
    for c in channels:
        color = CHANNEL_COLORS.get(c, "#8b949e")
        out.append(f'<span class="ch" style="border-color:{color};color:{color}">'
                   f'{html.escape(c.capitalize())}</span>')
    for c in weak:
        color = CHANNEL_COLORS.get(c, "#8b949e")
        out.append(f'<span class="ch ch-weak" style="border-color:{color};color:{color}">'
                   f'{html.escape(c.capitalize())}?</span>')
    return "".join(out)


def _tier_badge(tier: str) -> str:
    prefix = tier.split("（")[0]
    label, color = TIER_BADGE.get(prefix, ("", "#8b949e"))
    if not label:
        return ""
    return f'<span class="tier" style="background:{color}22;color:{color};border:1px solid {color}55">{label}</span>'


def run() -> None:
    conn = connect()
    rows = all_scanned(conn)
    total_in_db = conn.execute("SELECT COUNT(*) c FROM sites WHERE status='active'").fetchone()["c"]
    conn.close()

    now = time.time()
    parsed = []
    for r in rows:
        channels = json.loads(r["payment_channels"])
        weak = json.loads(r["weak_channels"] if "weak_channels" in r.keys() else "[]")
        tier = signal_tier(channels, weak, bool(r["has_pricing"]), r["min_price_usd"])
        prefix = tier.split("（")[0]
        parsed.append({
            "domain": r["domain"], "name": r["name"] or "", "desc": r["description"] or "",
            "channels": channels, "weak": weak, "tier": tier, "prefix": prefix,
            "has_pricing": bool(r["has_pricing"]), "min_price": r["min_price_usd"],
            "revenue": r["revenue_signal"] or 0,
            "recent": (now - (r["last_scan_at"] or 0)) < WEEK,
        })

    strong = [p for p in parsed if p["channels"]]
    weakish = [p for p in parsed if not p["channels"] and p["weak"]]
    featured = sorted([p for p in strong + weakish if p["recent"]],
                      key=lambda p: (p["prefix"] not in ("A", "B"), -p["revenue"]))[:12]
    strong.sort(key=lambda p: (["A", "B", "C"].index(p["prefix"])
                               if p["prefix"] in ("A", "B", "C") else 9, -p["revenue"]))
    weakish.sort(key=lambda p: -p["revenue"])

    fmt_int = lambda n: f"{n:,.0f}"

    def card(p) -> str:
        desc = html.escape((p["desc"] or p["name"] or "").strip())
        price = f'<div class="price">最低 ${p["min_price"]:.0f}/月</div>' if p["min_price"] else ""
        return (f'<a class="card" href="https://{html.escape(p["domain"])}" target="_blank" rel="noopener">'
                f'<div class="card-head"><img src="{_favicon(p["domain"])}" alt="" width="20" height="20">'
                f'<b>{html.escape(p["domain"])}</b></div>'
                f'{f"<p>{desc}</p>" if desc else ""}'
                f'<div class="card-foot">{_channel_badges(p["channels"], p["weak"])}{price}</div></a>')

    def table_row(p) -> str:
        rev = fmt_int(p["revenue"]) if p["revenue"] else "—"
        price = f'${p["min_price"]:.0f}' if p["min_price"] else "—"
        desc = html.escape((p["desc"] or p["name"] or "").strip()[:70])
        data_attrs = (f'data-tier="{p["prefix"]}" '
                      f'data-ch="{" ".join(p["channels"] + p["weak"])}" '
                      f'data-text="{html.escape(p["domain"] + " " + p["desc"] + " " + p["name"]).lower()}"')
        return (f'<tr {data_attrs}><td><img src="{_favicon(p["domain"])}" alt="" width="16" height="16"> '
                f'<a href="https://{html.escape(p["domain"])}" target="_blank" rel="noopener">'
                f'{html.escape(p["domain"])}</a>{"<small>" + desc + "</small>" if desc else ""}</td>'
                f'<td>{_channel_badges(p["channels"], [])}</td>'
                f'<td>{"✓" if p["has_pricing"] else "—"}</td>'
                f'<td>{price}</td><td>{_tier_badge(p["tier"])}</td><td class="num">{rev}</td></tr>')

    ts = time.strftime("%Y-%m-%d")
    ch_options = "".join(f'<button class="fbtn" data-ch="{c}">{html.escape(c.capitalize())}</button>'
                         for c in CHANNEL_COLORS)
    page = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI 站点收款信号榜 · 谁在悄悄赚钱</title>
<meta name="description" content="每周自动扫描 AI 工具站的公开收款信号（Stripe/Paddle/Creem/Dodo）与定价页，发现正在赚钱的新站点，给独立开发者找可复制的变现样本。">
<style>
:root {{ color-scheme: dark; --bg:#0a0e14; --card:#11161f; --line:#1e2633; --fg:#e6edf3; --muted:#8b949e; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); line-height:1.65;
  font-family:system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
main {{ max-width:1120px; margin:0 auto; padding:0 20px 60px; }}
a {{ color:#58a6ff; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
small {{ color:var(--muted); display:block; margin-top:2px; font-size:.8rem; }}

.hero {{ text-align:center; padding:64px 0 40px;
  background:radial-gradient(ellipse 60% 80% at 50% -20%, rgba(88,166,255,.18), transparent); }}
.hero h1 {{ font-size:2.4rem; margin:0 0 12px; letter-spacing:.5px; }}
.hero h1 em {{ font-style:normal; background:linear-gradient(90deg,#58a6ff,#3fb950);
  -webkit-background-clip:text; background-clip:text; color:transparent; }}
.hero p {{ color:var(--muted); max-width:560px; margin:0 auto 28px; }}
.cta {{ display:flex; gap:12px; justify-content:center; flex-wrap:wrap; }}
.btn {{ padding:10px 22px; border-radius:10px; font-weight:600; font-size:.95rem; }}
.btn-pri {{ background:linear-gradient(90deg,#1f6feb,#388bfd); color:#fff !important; }}
.btn-sec {{ border:1px solid var(--line); color:var(--fg) !important; }}
.btn:hover {{ transform:translateY(-1px); text-decoration:none !important; }}

.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin:36px 0 8px; }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 20px; }}
.stat b {{ font-size:1.7rem; display:block; }}
.stat span {{ color:var(--muted); font-size:.85rem; }}

h2 {{ font-size:1.35rem; margin:56px 0 6px; }}
h2 + .sub2 {{ color:var(--muted); margin:0 0 20px; font-size:.9rem; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:14px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px;
  color:var(--fg) !important; display:flex; flex-direction:column; gap:8px; transition:.15s; }}
.card:hover {{ border-color:#388bfd; text-decoration:none !important; transform:translateY(-2px); }}
.card-head {{ display:flex; align-items:center; gap:8px; }}
.card p {{ margin:0; color:var(--muted); font-size:.85rem; flex:1; }}
.card-foot {{ display:flex; align-items:center; gap:6px; flex-wrap:wrap; }}
.price {{ margin-left:auto; color:#3fb950; font-size:.82rem; font-weight:600; }}

.ch {{ border:1px solid; border-radius:20px; padding:1px 10px; font-size:.75rem; font-weight:600; }}
.ch-weak {{ opacity:.55; border-style:dashed; }}
.tier {{ border-radius:6px; padding:2px 10px; font-size:.78rem; white-space:nowrap; }}

.filters {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:18px 0 14px; }}
#q {{ background:var(--card); border:1px solid var(--line); color:var(--fg);
  border-radius:10px; padding:9px 14px; width:240px; font-size:.9rem; outline:none; }}
#q:focus {{ border-color:#388bfd; }}
.fbtn {{ background:var(--card); border:1px solid var(--line); color:var(--muted); border-radius:20px;
  padding:6px 14px; font-size:.82rem; cursor:pointer; }}
.fbtn:hover, .fbtn.on {{ border-color:#388bfd; color:#58a6ff; }}
.clear {{ color:var(--muted); background:none; border:none; cursor:pointer; font-size:.82rem; }}

table {{ width:100%; border-collapse:collapse; font-size:.9rem; background:var(--card);
  border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
th,td {{ padding:12px 14px; text-align:left; border-bottom:1px solid var(--line); vertical-align:middle; }}
th {{ color:var(--muted); font-weight:500; font-size:.82rem; }}
tr:hover td {{ background:#151c28; }}
td.num {{ text-align:right; font-variant-numeric:tabular-nums; color:#3fb950; font-weight:600; }}
img {{ vertical-align:-3px; border-radius:4px; }}

details {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:16px 20px; margin-top:24px; }}
summary {{ cursor:pointer; font-weight:600; }}
details p, details li {{ color:var(--muted); font-size:.9rem; }}
footer {{ margin-top:48px; padding-top:24px; border-top:1px solid var(--line);
  color:var(--muted); font-size:.85rem; display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
.empty {{ color:var(--muted); text-align:center; padding:32px; display:none; }}
@media (max-width:640px) {{ .hero h1 {{ font-size:1.7rem; }} td small {{ display:none; }} }}
</style></head><body><main>

<div class="hero">
  <h1>谁在<em>悄悄赚钱</em>？</h1>
  <p>每周自动扫描 {total_in_db}+ 个 AI 工具站的公开收款信号（Stripe / Paddle / Creem / Dodo…）与定价页，
     给独立开发者找出<b>正在产生收入的站点</b>——可复制的变现样本，不用猜。</p>
  <div class="cta">
    <a class="btn btn-pri" href="#rank">查看信号榜</a>
    <a class="btn btn-sec" href="mailto:hello@example.com?subject=订阅周报">每周报告发我 📬</a>
  </div>
</div>

<div class="stats">
  <div class="stat"><b>{total_in_db}</b><span>收录站点</span></div>
  <div class="stat"><b style="color:#3fb950">{len(strong)}</b><span>检测到收款信号</span></div>
  <div class="stat"><b style="color:#d29922">{sum(1 for p in parsed if p['has_pricing'])}</b><span>有公开定价页</span></div>
  <div class="stat"><b>{ts}</b><span>最近更新</span></div>
</div>

<h2>🔥 最新发现</h2>
<div class="sub2">近期扫描中新检测到收款信号的站点——它们可能刚开启变现，是最佳观察窗口</div>
<div class="grid">{''.join(card(p) for p in featured) or '<p style="color:var(--muted)">本周暂无新发现，下周见。</p>'}</div>

<h2 id="rank">📊 收款信号榜</h2>
<div class="sub2">按信号强度排序。信号 = 站点公开页面上的支付渠道痕迹与定价页，非真实营收。</div>
<div class="filters">
  <input id="q" placeholder="搜索域名 / 关键词…">
  <button class="fbtn on" data-tier="all">全部</button>
  <button class="fbtn" data-tier="A">已验证收款</button>
  <button class="fbtn" data-tier="B">信号强</button>
  <button class="fbtn" data-tier="C">有信号</button>
  <span style="color:var(--muted)">渠道:</span>{ch_options}
  <button class="clear" id="clr">重置</button>
</div>
<table><thead><tr>
<th>站点</th><th>收款渠道</th><th>定价页</th><th>最低价</th><th>信号</th><th style="text-align:right">估算月收款 $</th>
</tr></thead><tbody>
{''.join(table_row(p) for p in strong)}
</tbody></table>
<div class="empty" id="empty">没有匹配的站点</div>

<details><summary>👀 观察名单（仅页面提及支付渠道，尚未确认） —— {len(weakish)} 个</summary>
<table style="margin-top:14px"><tbody>
{''.join(table_row(p) for p in weakish) or '<tr><td>暂无</td></tr>'}
</tbody></table></details>

<details><summary>📐 数据口径与常见问题</summary>
<ul>
<li><b>什么是"收款信号"？</b> 站点公开页面嵌入的支付渠道指纹（如 js.stripe.com、pk_live 公钥）、
    外链支付页（checkout.stripe.com 等）与定价页探测的结果。<b>不等于真实营收</b>。</li>
<li><b>估算金额怎么算？</b> 月访问量 × 行业基准转化率(2%) × 最低定价。"—"表示流量数据待接入。</li>
<li><b>数据多久更新？</b> 每周一自动全量重扫，站点库持续扩张（HN / ProductHunt / awesome-lists）。</li>
<li><b>想上/下榜？</b> 信号来自公开页面；希望移除请邮件 hello@example.com，无条件 24h 内处理。</li>
</ul></details>

<footer>
<div>🔦 AI 站点收款信号榜 · 数据每周自动更新</div>
<div><a href="https://github.com/zhangmingjava/ai-station-intel">GitHub 开源</a>
 · <a href="weekly-{ts}.md">本周报告</a></div>
</footer>

<script>
const q = document.getElementById('q');
const rows = [...document.querySelectorAll('tbody tr')];
let tier = 'all', ch = '';
function apply() {{
  let n = 0;
  for (const tr of rows) {{
    const okT = tier === 'all' || tr.dataset.tier === tier;
    const okC = !ch || tr.dataset.ch.split(' ').includes(ch);
    const okQ = !q.value || tr.dataset.text.includes(q.value.toLowerCase());
    const show = okT && okC && okQ;
    tr.style.display = show ? '' : 'none';
    if (show) n++;
  }}
  document.getElementById('empty').style.display = n ? 'none' : 'block';
}}
document.querySelectorAll('[data-tier]').forEach(b => b.onclick = () => {{
  document.querySelectorAll('[data-tier]').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); tier = b.dataset.tier; apply();
}});
document.querySelectorAll('[data-ch]').forEach(b => b.onclick = () => {{
  const on = b.classList.toggle('on'); ch = on ? b.dataset.ch : ''; apply();
}});
q.oninput = apply;
document.getElementById('clr').onclick = () => {{
  q.value = ''; tier = 'all'; ch = '';
  document.querySelectorAll('[data-tier]').forEach(x => x.classList.toggle('on', x.dataset.tier === 'all'));
  document.querySelectorAll('[data-ch]').forEach(x => x.classList.remove('on'));
  apply();
}};
</script>
</main></body></html>"""

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / "index.html"
    out.write_text(page, encoding="utf-8")
    print(f"静态页已生成：{out}（收录 {total_in_db}，强信号 {len(strong)}，观察 {len(weakish)}）")


if __name__ == "__main__":
    run()
