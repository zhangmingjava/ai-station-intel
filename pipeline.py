"""统一入口：python pipeline.py <command> [--limit N]

  discover   收割发现源（HN + GitHub awesome-lists + ProductHunt + 导航站）
  scan       对未探测站点跑收款信号探测（默认每次 20 个）
  backfill   DataForSEO 回填月流量（需环境变量，免费替代见 README）
  classify   LLM 站点打标（需 LLM_API_KEY，可选）
  estimate   计算营收估算/信号分级
  report     生成 Markdown + CSV 榜单
  weekly     生成博客/Newsletter 周报
  site       生成静态榜单页 site/index.html（可直接部署）
  all        discover -> scan -> estimate -> report -> weekly -> site
             （backfill/classify 需凭据，按需单独跑）

环境变量可写在本目录 .env 文件（KEY=VALUE 每行一条），启动时自动加载。
"""
import argparse
from pathlib import Path

import db
import discovery
import signals
import estimate
import report
import traffic
import classify
import weekly
import site_gen


def load_dotenv() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            import os
            os.environ.setdefault(key.strip(), value.strip())


def cmd_scan(limit: int) -> None:
    conn = db.connect()
    rows = db.pending_sites(conn, limit)
    print(f"待探测 {len(rows)} 个站点")
    for row in rows:
        print(f"  扫描 {row['domain']} ...", flush=True)
        result = signals.scan_site(row["domain"])
        db.save_scan(conn, row["domain"], {
            "status": result.status,
            "channels": result.channels,
            "weak_channels": result.weak_channels,
            "has_pricing": result.has_pricing,
            "min_price_usd": result.min_price_usd,
        })
        tier = estimate.signal_tier(result.channels, result.weak_channels,
                                    result.has_pricing, result.min_price_usd)
        print(f"    -> {result.status}, 强: {result.channels or '无'}"
              f", 弱: {result.weak_channels or '无'}, 信号: {tier}")
    conn.close()


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="AI 站点收款信号情报管道")
    parser.add_argument("command",
                        choices=["discover", "scan", "backfill", "classify",
                                 "estimate", "report", "weekly", "site", "all"])
    parser.add_argument("--limit", type=int, default=20, help="scan/classify 每批数量")
    parser.add_argument("--no-harvest", action="store_true", help="discover 时只导入种子")
    args = parser.parse_args()

    if args.command in ("discover", "all"):
        discovery.run(harvest=not args.no_harvest)
    if args.command in ("scan", "all"):
        cmd_scan(args.limit)
    if args.command == "backfill":
        traffic.run()
    if args.command == "classify":
        classify.run(args.limit)
    if args.command in ("estimate", "all"):
        estimate.run()
    if args.command in ("report", "all"):
        report.run()
    if args.command in ("weekly", "all"):
        weekly.run()
    if args.command in ("site", "all"):
        site_gen.run()


if __name__ == "__main__":
    main()
