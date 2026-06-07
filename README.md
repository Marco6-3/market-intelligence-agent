# market-intelligence-agent

`market-intelligence-agent` 是一个本地 Python CLI 工具，用于按 `watchlist.yaml` 中的股票列表收集行情、新闻、财报日历、SEC filings、A 股快照等信息，并生成 Markdown、JSON 和 sources.csv 溯源文件。

本项目只做信息收集和研究摘要，不做自动交易，也不会输出“买入/卖出”指令。

## 功能范围

- 读取 `watchlist.yaml`。
- 使用 Financial Modeling Prep 获取美股新闻、行情和财报日历。
- 使用 yfinance / Yahoo Finance 获取美股行情快照。yfinance 不需要 API key。
- 在 FMP 不可用时，可使用 Alpha Vantage 或 Finnhub 作为美股新闻/财报日历备用源。
- 使用 SEC EDGAR data APIs 获取美股最近 filings。
- 使用 AKShare 获取 A 股行情快照。
- 如果配置了 `TUSHARE_TOKEN`，额外尝试读取 Tushare A 股日线数据。
- 对新闻增加 `freshness` 分层：`fresh` / `recent` / `stale` / `background` / `unknown`。
- 对新闻增加 `source_quality` 分层：`high` / `medium` / `low` / `unknown`。
- 对 Google News RSS 做 best-effort 真实链接解析，输出 `final_url` 和 `aggregator_url`；Markdown 默认展示 `final_url`。
- 对相似新闻做 cluster 合并，报告只展示代表项，并在 `cluster_sources` 中保留多个来源。
- 对标题型新闻使用 `title_summary:`，并标记 `summary_confidence=low`，避免假装已经读过全文。
- 输出 `## Analyst Review Queue`，每天最多列出 5 个最值得人工复核的 item 或 cluster。
- 对未来 30 天内的财报日历项标记 `earnings_alert=true`；没有可用 key 时输出 `earnings calendar unavailable because ...`。
- 使用本地 `data_cache/` 缓存 API 响应，减少重复请求。
- 单个数据源失败时不会中断整个流程，会在报告和 CLI 输出中记录 warning。
- 输出：
  - `reports/YYYY-MM-DD_daily_brief.md`
  - `reports/YYYY-MM-DD_daily_brief.json`
  - `reports/YYYY-MM-DD_sources.csv`

## 安装

建议使用 Python 3.11+。

```powershell
cd "C:\Users\mingzhe Liu\OneDrive\Desktop\market-intelligence-agent"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
python -m pip install -e .
```

如果你只想安装核心依赖，不需要 A 股源，可以改用：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e .[dev]
```

## 配置

复制示例文件：

```powershell
Copy-Item .env.example .env
Copy-Item watchlist.example.yaml watchlist.yaml
```

编辑 `.env`，填入你要使用的数据源 key：

```dotenv
FMP_API_KEY=
ALPHA_VANTAGE_API_KEY=
FINNHUB_API_KEY=
TUSHARE_TOKEN=
YFINANCE_ENABLED=true
LLM_PROVIDER=moonshot
LLM_BASE_URL=https://api.moonshot.cn/anthropic
LLM_MODEL=kimi-k2.6
LLM_API_KEY=
SEC_USER_AGENT=market-intelligence-agent/0.1 your_email@example.com
CACHE_TTL_SECONDS=21600
```

说明：

- `FMP_API_KEY`：推荐配置，用于美股新闻、行情、财报日历。
- `ALPHA_VANTAGE_API_KEY` / `FINNHUB_API_KEY`：FMP 没有配置或失败时作为备用。
- `TUSHARE_TOKEN`：可选，用于 A 股 Tushare 数据。
- `YFINANCE_ENABLED`：默认 `true`，用于打开 yfinance 美股行情快照；yfinance 不需要 API key。
- `LLM_MODEL`：默认 `kimi-k2.6`。当前 MVP 不会自动调用 LLM，这组配置留给后续研究摘要扩展使用。
- `LLM_API_KEY`：如果要启用后续 LLM 功能，可放 Moonshot/Kimi token；不要写进代码。
- `SEC_USER_AGENT`：SEC EDGAR 建议自动化请求提供明确 User-Agent 和联系邮箱。
- 所有 API key 都只放在 `.env`，不要写进代码。

## watchlist.yaml 示例

```yaml
timezone: Asia/Singapore
keywords:
  - HBM
  - DRAM price
  - NAND price
  - AI data center
  - enterprise SSD
  - memory cycle
stocks:
  - ticker: MU
    name: Micron
    market: US
    aliases: [Micron Technology, 美光]
    themes: [HBM, DRAM, NAND, AI memory]
  - ticker: WDC
    name: Western Digital
    market: US
    aliases: [Western Digital, 西部数据]
    themes: [HDD, NAND, AI storage]
  - ticker: 688008.SH
    name: 澜起科技
    market: CN
    aliases: [Montage Technology, 澜起]
    themes: [DDR5, CXL, AI server]
```

## 运行

校验 watchlist：

```powershell
python -m market_agent validate-watchlist --watchlist watchlist.yaml
```

检查 yfinance 和 LLM 配置：

```powershell
python -m market_agent show-config --env-file .env
```

按 watchlist 生成当天报告：

```powershell
python -m market_agent run --watchlist watchlist.yaml
```

指定日期生成报告：

```powershell
python -m market_agent run --watchlist watchlist.yaml --date 2026-06-01
```

如果没有执行 `pip install -e .`，也可以临时设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH="src"
python -m market_agent run --watchlist watchlist.yaml --date 2026-06-01
```

## 输出 JSON 结构

JSON 报告包含这些顶层字段：

```json
{
  "run_date": "YYYY-MM-DD",
  "timezone": "Asia/Singapore",
  "watchlist": [],
  "market_snapshot": [],
  "news": [],
  "filings": [],
  "earnings_calendar": [],
  "earnings_transcripts": [],
  "theme_mentions": [],
  "alerts": [],
  "analyst_review_queue": [],
  "questions_for_analysis": [],
  "sources": []
}
```

所有采集到的记录都会尽量包含：

- `source_url`
- `final_url`
- `aggregator_url`
- `source_name`
- `published_at`
- `fetched_at`

新闻和聚合后的新闻 item 还会尽量包含：

- `freshness`
- `source_quality`
- `summary_confidence`
- `cluster_id`
- `cluster_size`
- `cluster_sources`
- `core_claim`

`thesis_effect` 使用更细的标签：

- `supports_demand_thesis`
- `supports_pricing_power`
- `weakens_supply_shortage_thesis`
- `increases_competition_risk`
- `valuation_risk`
- `background_only`
- `needs_manual_review`

缺失数据不会被编造。Markdown 中缺失项会显示为 `not available`。

## 测试

```powershell
python -m pytest
```

当前测试覆盖：

- watchlist 数据模型校验。
- 新闻记录的溯源字段。
- 新闻新鲜度、来源质量、旧新闻降级和相似新闻 cluster。
- Markdown 报告中新闻来源字段和 `not available` 输出。
- sources.csv 必要列和扩展溯源列。

## 注意事项

- 免费 API key 可能有频率限制或字段限制，失败时程序会记录 warning 并继续跑其他数据源。
- SEC EDGAR 不需要 API key，但应配置合规的 `SEC_USER_AGENT`。
- A 股 AKShare/Tushare 字段可能随上游库变化，若失败会在 alerts 中记录原因。
- 本工具生成的是研究材料，不是投资建议。
