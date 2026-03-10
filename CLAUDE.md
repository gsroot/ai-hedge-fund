# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered hedge fund system that uses legendary investor personas (Buffett, Lynch, Graham, etc.) and multi-factor ensemble analysis to predict stock returns and build portfolios. Educational/research purposes only.

## Core Skills (Slash Commands)

The project's primary functionality lives in Claude Code skills, not traditional source code:

### `/predict` — Stock Return Prediction & Ranking
- **Entry point**: `uv run python .claude/skills/predict/scripts/analyze_stocks.py`
- Multi-factor ensemble model combining 7 factors (Value 25%, Growth 20%, Quality 20%, Momentum 10%, Safety 10%, Sentiment 8%, Insider 7%) with 8 investor style scores
- Supports S&P 500, NASDAQ 100, KOSPI, KOSDAQ, KRX indices
- Strategies: `hybrid` (default, recommended), `fundamental`, `momentum`
- Output: 8-section formatted report (defined in `predict/references/output_format.md`)
- Key scripts in `.claude/skills/predict/scripts/`: `analyze_stocks.py` (CLI), `data_fetcher.py` (data collection), `factor_scoring.py` (7 factors), `investor_scoring.py` (investor styles), `ranking_algorithm.py` (ensemble), `korean_data_fetcher.py` (DART/PyKRX)

### `/portfolio-report` — Investment Portfolio Construction
- Orchestrator: predict (ranking) → investor-analysis (deep analysis) → xlsx (Excel report)
- Calls investor agent subagents (e.g., `warren-buffett-analyst`) via Task tool for each top-N stock
- Portfolio construction: majority bullish filter → confidence-weighted allocation → 15% max single stock, 35% max sector
- Output: Excel report in `portfolios/` directory

### `/investor-analysis` — Investor Perspective Analysis
- 12 investor personas + 5 specialist analysts as subagents (defined in `.claude/agents/`)
- Modes: quick analysis (5 analysts), single investor, ensemble (17 agents parallel), report
- All agents return `{signal, confidence, reasoning}` format

### `/backtesting` — Portfolio Backtesting
- **Entry point**: `uv run python .claude/skills/backtesting/scripts/backtest.py`
- Strategies: `momentum`, `predictor`, `hybrid` (recommended)
- Performance metrics: Sharpe/Sortino Ratio, Max Drawdown, Alpha vs benchmark

## Data Sources

| Data | US Source | Korean Source |
|------|-----------|--------------|
| Financials | Yahoo Finance (free, no API key) | DART (`DART_API_KEY` required) |
| Prices | Yahoo Finance (batch `yf.download`) | PyKRX / FinanceDataReader |
| Market Cap | Yahoo Finance | KRX Open API / PyKRX |
| Index Members | Wikipedia | PyKRX |

Korean stocks are auto-detected by 6-digit numeric ticker codes and routed to Korean data sources.

## Commands

```bash
# Install dependencies
uv sync

# Run predict analysis
uv run python .claude/skills/predict/scripts/analyze_stocks.py --index sp500
uv run python .claude/skills/predict/scripts/analyze_stocks.py --index krx --display 30
uv run python .claude/skills/predict/scripts/analyze_stocks.py --tickers AAPL,MSFT,NVDA

# Run backtesting
uv run python .claude/skills/backtesting/scripts/backtest.py --index nasdaq100 --top 30 --start 2024-06-01 --end 2024-12-31 --rebalance monthly

# Run tests
uv run pytest tests/

# Web app (separate from skills)
cd app/backend && uv run uvicorn main:app --reload
cd app/frontend && pnpm dev
```

## Architecture

```
.claude/
├── agents/           # 17 investor/analyst agent definitions (subagent_type for Task tool)
│   ├── warren-buffett-analyst.md
│   ├── peter-lynch-analyst.md
│   └── ...
└── skills/
    ├── predict/      # Core prediction engine
    │   ├── scripts/  # Python analysis pipeline
    │   └── references/  # Output format specs
    ├── portfolio-report/  # Orchestrator skill
    │   └── references/  # Excel report spec, output format
    ├── investor-analysis/  # Deep analysis skill
    │   └── references/  # Investor personas, frameworks
    ├── backtesting/  # Backtesting engine
    │   └── scripts/
    └── xlsx/         # Excel report generation (openpyxl)

app/                  # Web application (separate from skills)
├── backend/          # FastAPI + SQLAlchemy
└── frontend/         # Vite + React + Tailwind

portfolios/           # Generated Excel portfolio reports
```

## Key Technical Details

- **Package manager**: `uv` (not poetry, despite README saying poetry — use `uv run` for all commands)
- **Python**: >=3.11
- **Cache**: File-based in `.claude/skills/predict/scripts/.cache/{date}/`, key = `md5(f"{type}_{ticker}_{date}_{extra}")[:16].json`
- **DART rate limit**: 100 requests/min sliding window
- **DART year logic**: if month <= 3, use year-1; fallback to year-2 if empty
- **OpenDartReader**: Singleton pattern with thread lock (double-checked locking) for thread safety with `ThreadPoolExecutor`
- **Line length**: 420 (configured in pyproject.toml `[tool.black]`)
- **KRX index** (`--index krx`): KOSPI200 + KOSDAQ150 combined — never run them as separate commands
- Market cap display: Korean stocks use `₩320조`, `₩5,000억` format

## Environment Variables

```
OPENAI_API_KEY=       # Required: at least one LLM key (OpenAI/Anthropic/Groq/DeepSeek)
DART_API_KEY=         # Required for Korean stocks (DART financial data)
FINANCIAL_DATASETS_API_KEY=  # Optional: for non-free tickers via financialdatasets.ai
```
