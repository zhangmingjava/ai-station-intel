# AI 站点收款信号情报管道（MVP）

对标 columbus.tools 收入榜的最小可行数据管道：**发现站点 → 探测收款信号 → 分级 → 出榜 → 周报 → 静态页**。
当前为 A 档（纯静态爬虫）实现，零 API 成本即可运行；接了凭据的模块（流量/打标/ProductHunt）自动增强。

## 用法

```bash
pip install -r requirements.txt
cp .env.example .env        # 按需填凭据，不填也能跑

python pipeline.py discover            # 收割发现源（HN + GitHub + ProductHunt + 导航站）
python pipeline.py scan --limit 50     # 对未探测站点跑收款信号探测
python pipeline.py backfill            # DataForSEO 回填月流量（需凭据，可选）
python pipeline.py classify --limit 50 # LLM 打分类/简介（需 LLM_API_KEY，可选）
python pipeline.py estimate            # 信号分级 + 营收估算
python pipeline.py report              # data/rank-*.md 与 .csv
python pipeline.py weekly              # data/weekly-*.md（博客/Newsletter 直接可用）
python pipeline.py site                # docs/index.html 静态榜单页（GitHub Pages 直接用）
python pipeline.py all                 # 依序执行（不含 backfill/classify）
```

## 文件

| 文件 | 职责 |
|---|---|
| `pipeline.py` | 统一 CLI 入口，自动加载 .env |
| `discovery.py` | 站点发现：HN Algolia API、GitHub awesome-lists、ProductHunt API（需 token）、导航站收割、seeds.txt |
| `signals.py` | 收款信号探测：强/弱双层指纹 + 定价页价格提取 |
| `traffic.py` | DataForSEO bulk_traffic_metrics 回填月流量（需凭据） |
| `classify.py` | OpenAI 兼容接口打标（默认智谱 glm-4-flash，可换 DeepSeek/OpenAI） |
| `estimate.py` | 估算模型：访问量 × 转化率(2%) × 最低客单价；信号 A/B/C/C-/D 分级 |
| `report.py` / `weekly.py` | 榜单 CSV/MD 与周报 |
| `site_gen.py` | 静态榜单页（自包含单 HTML，无构建步骤） |

## 信号分级口径

- **A**：强渠道指纹 + 定价页 + 提取到价格 —— 可认定在收款
- **B / C**：有强渠道指纹，定价信息不全
- **C-**：仅弱信号（页面文字提及渠道名），置信度低，不上主榜
- **D**：未检测到（含 JS 动态渲染结账页的站——静态爬虫的已知盲区）

强指纹示例：`js.stripe.com`、`pk_live_*`、`checkout.stripe.com`、`cdn.paddle.com`、`creem.io`、`dodopayments` 等。

## 已知局限（实测结论）

1. **目录站全部反爬**：gptdemo / topai.tools / toolify 的 robots.txt 禁抓，theresanaiforthat 返回 403。
   主力发现源应转向：HN Algolia API（已接入）、ProductHunt API（需 token）、GitHub awesome-lists（已接入）、X 监控。
   注意：本机在大陆网络下 raw.githubusercontent.com 可能连接重置，GitHub Actions 环境正常。
2. **JS 渲染结账页探测不到**（如 jenni.ai）：静态爬虫上限如此，升级路径是
   无头浏览器抽查（成本高，只扫 A/B 候选）或点击流数据（SimilarWeb/DataForSEO，即对标站的 B 档方案）。
3. 价格提取有误报（如 $1 试用档），上主榜前需人工抽检或 LLM 复核。
4. HN 源混入非产品站已过滤（平台子域黑名单），但新源仍建议每周人工扫一眼新入库列表。

## 部署

**数据管道（推荐 GitHub Actions，免费）**：仓库里已带 `.github/workflows/pipeline.yml`——
每周一自动跑 `pipeline.py all` 并把 data/、docs/ 的更新 commit 回仓库。
只需：把本项目推到 GitHub 私有/公开仓库 → 在 Settings→Secrets 配置
`DATAFORSEO_LOGIN`、`DATAFORSEO_PASSWORD`、`PH_ACCESS_TOKEN`、`LLM_API_KEY`（可选）→ 完成。

**静态榜单页**：`docs/index.html` 是自包含单页，三种任选：
- GitHub Pages：仓库 Settings→Pages→Branch 选 main + `/docs` 目录（推荐，零配置）
- Cloudflare Pages / Vercel：直接把 `docs/` 目录作为一个项目部署
- 自有服务器：任意静态托管

**本机/VPS cron 替代方案**：`0 10 * * 1 cd /path/to/ai-station-intel && python pipeline.py all --limit 50 >> cron.log 2>&1`

**这还不是完整商业站**：当前部署的是"数据管道 + 公开静态页"。付费墙、会员系统、
API/MCP 属于前端产品阶段（Next.js + Stripe/LemonSqueezy + Supabase），建议等静态页有第一批
自然流量、周报发出 4 期之后再投入开发——先用零成本阶段验证数据质量和选题方向。

## 合规红线

- 只读公开页面、遵守 robots.txt、同站请求间隔 1 秒、UA 标明身份
- 输出一律标注"信号，非真实营收"，榜单页必须保留"要求下榜"入口

## 下一步（按优先级）

1. 内容层启动：把 weekly-*.md 作为第一期博客周报/Newsletter 发出，开始访谈系列
2. 站点规模：配 ProductHunt token + 加更多 awesome-lists，目标入库 500+
3. 数据质量：配 DataForSEO 凭据跑 backfill，让估算出金额；A/B 候选站无头浏览器复查
4. 前端产品：付费墙 + 会员（Next.js），等前 3 步有反馈后再动工
