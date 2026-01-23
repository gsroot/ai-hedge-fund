# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI Hedge Fund는 LLM 기반 멀티 에이전트 투자 시뮬레이션 시스템입니다. 실제 거래를 수행하지 않으며, 교육 및 연구 목적으로 설계되었습니다. 16개 이상의 투자자 페르소나 에이전트(워렌 버핏, 마이클 버리, 캐시 우드 등)가 LangGraph를 통해 조율됩니다.

## Build & Run Commands

```bash
# 의존성 설치
poetry install

# 메인 분석 실행
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-03-01

# 로컬 Ollama 사용
poetry run python src/main.py --ticker AAPL --ollama

# 백테스팅
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA

# 웹 앱 실행
cd app/backend && poetry run uvicorn main:app --reload
cd app/frontend && npm run dev

# 린팅 및 테스트
black src/                # 420자 라인 길이 사용
isort src/
flake8 src/
pytest tests/
```

## Architecture

```
사용자 입력 (티커, 날짜)
        │
        ▼
┌──────────────────────────────────────┐
│       LangGraph DAG 워크플로우        │
├──────────────────────────────────────┤
│  투자자 에이전트 (16개, 병렬 실행)     │
│  - Warren Buffett, Michael Burry     │
│  - Cathie Wood, Charlie Munger 등    │
├──────────────────────────────────────┤
│  분석 에이전트 (6개)                  │
│  - Technical, Fundamentals           │
│  - Sentiment, Valuation              │
│  - News Sentiment, Growth            │
├──────────────────────────────────────┤
│  Risk Manager → Portfolio Manager    │
│  (신호 집계)     (최종 결정)          │
└──────────────────────────────────────┘
        │
        ▼
   거래 신호 출력 (bullish/bearish/neutral + 신뢰도)
```

## Key Directories

- `src/agents/`: 21개 에이전트 구현체. 새 에이전트 추가 시 기존 패턴(signal 반환, state 읽기) 참조
- `src/llm/models.py`: LLM 제공자 추상화 (OpenAI, Anthropic, Groq, DeepSeek, Ollama 등 13개+)
- `src/graph/state.py`: `AgentState` TypedDict - 에이전트 간 상태 전달
- `src/tools/api.py`: Financial Datasets API 연동 (가격, 메트릭, 뉴스, 내부자 거래)
- `src/backtesting/`: 백테스팅 엔진, 포트폴리오 추적, 성과 지표
- `app/backend/`: FastAPI REST API (routes/, services/, repositories/)
- `app/frontend/`: React/Vite 웹 UI

## Code Conventions

- **라인 길이 420자**: pyproject.toml의 Black 설정 - 표준 길이로 재포맷하지 말 것
- **에이전트 패턴**: 각 에이전트는 `AgentState`를 받아 신호(bullish/bearish/neutral + confidence)를 반환
- **상태 비저장**: 에이전트는 제공된 state만 사용, 공유 상태 없음
- **LLM 추상화**: 새 LLM 제공자 추가 시 `src/llm/models.py`의 `ModelProvider` enum과 JSON 설정 파일 수정

## Environment Setup

필수 환경 변수 (`.env.example` 참조):
- `FINANCIAL_DATASETS_API_KEY`: 금융 데이터 API (AAPL, GOOGL, MSFT, NVDA, TSLA는 무료)
- LLM API 키: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY` 등 중 하나 이상
- Ollama: `OLLAMA_BASE_URL`, `OLLAMA_HOST` (로컬 모델 사용 시)
