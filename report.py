"""榜单输出：生成 Markdown 榜单（可直接发博客/Newsletter）与 CSV。"""
import csv
import json
import time
from pathlib import Path

from db import connect, all_scanned
from estimate import signal_tier

OUT_DIR = Path(__file__).parent / "data"


def run() -> None:
    conn = connect()
    rows = all_scanned(conn)
    rows.sort(key=lambda r: (-(r["revenue_signal"] or 0), -len(json.loads(r["payment_channels"]))))
    conn.close()
    if not rows:
        print("库中还没有已探测的站点，先运行 scan。")
        return

    ts = time.strftime("%Y-%m-%d")
    md_path = OUT_DIR / f"rank-{ts}.md"
    csv_path = OUT_DIR / f"rank-{ts}.csv"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# 收款信号榜单（{ts}）\n\n")
        f.write("> 信号 = 公开支付渠道痕迹 + 定价页探测，非真实营收。要求下榜请联系我们。\n\n")
        f.write("| # | 站点 | 收款渠道 | 有定价页 | 最低价$ | 信号强度 | 估算月收款$ |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for i, r in enumerate(rows, 1):
            channels = json.loads(r["payment_channels"])
            weak = json.loads(r["weak_channels"] if "weak_channels" in r.keys() else "[]")
            tier = signal_tier(channels, weak, bool(r["has_pricing"]), r["min_price_usd"])
            shown = ", ".join(channels)
            if not shown and weak:
                shown = ", ".join(weak) + "（弱）"
            shown = shown or "-"
            f.write(f"| {i} | {r['domain']} | {shown} "
                    f"| {'✓' if r['has_pricing'] else '—'} "
                    f"| {r['min_price_usd']:.0f} | {tier} | {r['revenue_signal']:.0f} |\n")

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "domain", "channels", "has_pricing", "min_price_usd",
                         "visits_monthly", "revenue_signal"])
        for i, r in enumerate(rows, 1):
            writer.writerow([i, r["domain"], "|".join(json.loads(r["payment_channels"])),
                             r["has_pricing"], r["min_price_usd"],
                             r["visits_monthly"], r["revenue_signal"]])

    print(f"榜单已生成：\n  {md_path}\n  {csv_path}")


if __name__ == "__main__":
    run()
