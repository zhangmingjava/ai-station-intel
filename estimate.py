"""营收信号估算模型。

公式：估算月收款 = 月访问量 × 付款转化率 × 最低客单价
- 转化率默认 2%（工具站行业基准 1%–3%，可通过参数调）
- 无访问量数据时给出信号强度分级（不改写 revenue_signal）
流量数据留了 adapter 接口：接 SimilarWeb / DataForSEO 后在 get_visits 里实现。
"""
import json

from db import connect, all_scanned

CONVERSION_RATE = 0.02


def get_visits(domain: str) -> int:
    """流量数据源适配点。当前返回 DB 里手动录入的值；接入 DataForSEO/
    SimilarWeb API 后在此返回实时估算。"""
    conn = connect()
    row = conn.execute("SELECT visits_monthly FROM sites WHERE domain = ?", (domain,)).fetchone()
    conn.close()
    return row["visits_monthly"] if row else 0


def signal_tier(channels: list[str], weak: list[str], has_pricing: bool, min_price: float) -> str:
    if channels and has_pricing and min_price > 0:
        return "A（渠道+定价页+价格）"
    if channels and has_pricing:
        return "B（渠道+定价页）"
    if channels:
        return "C（仅强渠道信号）"
    if weak and has_pricing:
        return "C-（弱提及+定价页）"
    if weak:
        return "C-（仅弱提及）"
    return "D（未检测到收款信号）"


def estimate_visits_based(channels: list[str], min_price: float, visits: int) -> float:
    if not channels or min_price <= 0 or visits <= 0:
        return 0.0
    return round(visits * CONVERSION_RATE * min_price, 2)


def run() -> None:
    conn = connect()
    rows = all_scanned(conn)
    print(f"{'域名':<32} {'渠道':<28} {'信号强度':<18} {'最低价$':>8} {'月访问':>10} {'估算月收款$':>12}")
    print("-" * 115)
    for row in rows:
        channels = json.loads(row["payment_channels"])
        weak = json.loads(row["weak_channels"] if "weak_channels" in row.keys() else "[]")
        visits = row["visits_monthly"] or get_visits(row["domain"])
        revenue = estimate_visits_based(channels, row["min_price_usd"], visits)
        if revenue and revenue != row["revenue_signal"]:
            conn.execute("UPDATE sites SET revenue_signal = ? WHERE id = ?",
                         (revenue, row["id"]))
        tier = signal_tier(channels, weak, bool(row["has_pricing"]), row["min_price_usd"])
        shown = ",".join(channels) or (",".join(weak) + "（弱）") or "-"
        print(f"{row['domain']:<32} {shown:<28} "
              f"{tier:<18} {row['min_price_usd']:>8.0f} {visits:>10,} {revenue:>12,.0f}")
    conn.commit()
    conn.close()
