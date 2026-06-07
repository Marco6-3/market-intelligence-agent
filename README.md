# AI Hard-Tech Market Intelligence Agent

这是一个面向个人投研的 AI 硬科技产业链情报采集器。它每天围绕 watchlist 抓取行情、新闻、SEC filings、财报日历、主题变化，并生成 Markdown、JSON、CSV，方便继续交给 ChatGPT 做深度分析。

它不是交易机器人，不输出买入/卖出建议，不给目标价，也不编造缺失数据。数据缺失会写 `not available`，标题级新闻和 Google News RSS 聚合链接会降低 confidence。

## 覆盖方向

- AI 算力芯片、AI ASIC、AI 网络芯片
- 半导体制造、设备、检测、先进封装、EUV
- 存储、HBM、DRAM、NAND、HDD、SSD
- AI 云基础设施、云厂商 capex、数据中心需求
- 机器人、Physical AI、工业自动化、医疗机器人、仓储机器人

当前示例 watchlist 暂不包含 A 股。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

`requirements.txt` 会以 editable 模式安装当前项目，因此安装后可以直接使用 `python -m market_agent ...`。

## .env 配置

复制 `.env.example` 为 `.env`，按需填写：

```env
FMP_API_KEY=
ALPHA_VANTAGE_API_KEY=
FINNHUB_API_KEY=
SEC_USER_AGENT=market-intelligence-agent your_email@example.com
```

说明：

- `SEC_USER_AGENT` 建议填写真实邮箱，SEC EDGAR 需要 User-Agent。
- API key 只从 `.env` 读取，不要写进代码。
- 没有 API key 时会尽量使用 yfinance、SEC EDGAR、Google News RSS、IR RSS 等公开 fallback。

## 运行

验证 watchlist：

```powershell
python -m market_agent validate-watchlist --watchlist watchlist.example.yaml
```

生成 daily 报告：

```powershell
python -m market_agent run --watchlist watchlist.example.yaml
python -m market_agent run --watchlist watchlist.example.yaml --scope daily
python -m market_agent run --watchlist watchlist.example.yaml --date 2026-06-03
```

生成 weekly 或 all 范围报告：

```powershell
python -m market_agent run --watchlist watchlist.example.yaml --scope weekly
python -m market_agent run --watchlist watchlist.example.yaml --scope all
python -m market_agent run --watchlist watchlist.example.yaml --scope daily --max-news-per-ticker 3
```

默认 `scope=daily`，使用 `daily_core_stocks`。`weekly` 会合并 `daily_core_stocks` 和 `weekly_extended_stocks`。

## 数据源说明

- SEC EDGAR：官方 filings 来源。
- yfinance：非官方行情数据源，仅用于个人研究上下文。
- Google News RSS：公开 fallback 聚合源；系统会尽量解析 `canonical_url`，解析失败时保留 `aggregator_url` 并降低 confidence。
- FMP / Alpha Vantage / Finnhub：配置 API key 后用于增强新闻和财报日历。
- 公司 IR RSS：可在 watchlist 的 `ir_news_urls` 中配置。

所有请求都带 timeout；单个数据源失败会记录 warning，不应导致整个 pipeline 崩溃。

## 输出文件

运行后生成：

- `reports/YYYY-MM-DD_daily_brief.md`
- `reports/YYYY-MM-DD_daily_brief.json`
- `reports/YYYY-MM-DD_sources.csv`

Markdown 报告包含：

- Executive Summary
- Critical Alerts
- Analyst Triage
- What Changed Since Last Report
- Category Summary
- Watchlist Snapshot Table
- High Materiality Items
- Per-Ticker Detail
- Theme Tracker
- Missing Data / Weak Claims
- Questions for ChatGPT Analysis
- Source Notes

JSON 中每条 item 包含 `source_url`、`source_name`、`published_at`、`fetched_at`、`freshness`、`content_depth`、`materiality_score`、`score_breakdown`、`related_themes`、`matched_terms` 等字段，便于调试和追溯。

## 如何交给 ChatGPT 分析

把 Markdown、JSON、CSV 一起上传给 ChatGPT，然后让它重点判断：

- 哪些信息是真正重要的，哪些只是噪音；
- 哪些类别今天动量更强；
- 行情、filings、新闻、主题信号之间是否矛盾；
- 哪些结论因为数据缺失、过旧、或只有标题而证据较弱；
- 哪些公司需要回到官方来源继续验证。

## 测试

```powershell
pytest
```

建议在修改后至少运行：

```powershell
python -m market_agent validate-watchlist --watchlist watchlist.example.yaml
python -m market_agent run --watchlist watchlist.example.yaml --scope daily
pytest
```
