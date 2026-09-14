# CLAUDE.md

이 문서는 Claude Code에서 이 저장소를 사용할 때의 진입 안내다.
공통 금융 안전·데이터·Git 계약은 [AGENTS.md](AGENTS.md)를 따른다.
현재 작업 상태는 [.agent-os/manifest.json](.agent-os/manifest.json)에서 확인한다.

## 실행 구조

실제 분석 기능은 `.claude/skills`에 있고 Codex용 대응본은 `.agents/skills`에 있다.
데이터 수집과 수치 계산은 Python 스크립트가, 뉴스 분류·독립 투자자 분석·최종 판단은
해당 스킬을 실행하는 모델이 담당한다. 금융 스크립트에 별도의 LLM API를 추가하지 않는다.

| 스킬 | 기준 문서 |
|---|---|
| predict | [.claude/skills/predict/SKILL.md](.claude/skills/predict/SKILL.md) |
| investor-analysis | [.claude/skills/investor-analysis/SKILL.md](.claude/skills/investor-analysis/SKILL.md) |
| portfolio-report | [.claude/skills/portfolio-report/SKILL.md](.claude/skills/portfolio-report/SKILL.md) |
| backtesting | [.claude/skills/backtesting/SKILL.md](.claude/skills/backtesting/SKILL.md) |

포트폴리오 순서는 `predict -> independent investor-analysis -> risk snapshot -> portfolio-report`다.
새 추천은 `--decision-json`으로 종목·ETF·현금을 판단한다. 과거 confidence 기반 자동 비중
계산은 기존 보고서 재현에만 사용한다. 자세한 제약은 각 스킬의 최신 참조 문서를 읽는다.

Claude 에이전트를 사용할 때는 `.claude/agents`의 페르소나와 명시적 모델 설정을 유지한다.
과거 에이전트 설명이 공통 금융 계약이나 현재 스킬의 데이터·뉴스 계약과 충돌하면 현재 계약을
적용한다. 다른 투자자의 결론과 최종 비중을 각 관점의 입력에 넣지 않는다.

## Codex 모델과의 구분

Codex는 [.codex/config.toml](.codex/config.toml)의 `gpt-6-astra`/`xhigh` 기본값을 사용한다.
이 설정은 Claude 모델을 바꾸지 않는다. Claude에서 `gpt-6-astra`를 모델 식별자로 지정하지 않는다.
마이그레이션 근거는 [docs/GPT_6_ASTRA_MIGRATION.md](docs/GPT_6_ASTRA_MIGRATION.md)에 있다.

## 명령

Python 3.11 이상과 uv를 사용하며 프로젝트 루트에서 실행한다.

```powershell
uv sync --frozen
uv run python .claude/skills/predict/scripts/analyze_stocks.py --index sp500 --display 30 --output results.json
uv run python .claude/skills/predict/scripts/analyze_stocks.py --index krx --display 30 --output krx_results.json
uv run python -m unittest discover -s tests -p "test_*.py" -q
git diff --check
```

한국 재무자료의 `DART_API_KEY` 등 데이터 공급자 키는 로컬 `.env`에서 읽는다.
기존 프로세스 변수는 덮어쓰지 않는다. 스킬 흐름 자체에는 별도 LLM API 키가 필요하지 않다.
키와 유료 원문은 출력하거나 커밋하지 않는다.

공통 금융 스킬 변경은 Codex·Claude 대응본에 함께 반영하고 플랫폼 전용 호출 방식은 유지한다.
`app/`는 삭제된 `src/`에 의존하는 레거시 코드다. 현재 실행 경로로 안내하지 않는다.
