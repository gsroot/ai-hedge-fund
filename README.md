# AI Hedge Fund

현재 자료와 독립 투자자 분석을 바탕으로 종목·ETF·현금 비중을 판단하는 교육·연구용 프로젝트다.
사용자의 자금 사용 조건 안에서 장기 복리 의사결정을 개선하는 것을 목표로 하며, 실제 거래나
자금 이동을 실행하거나 수익을 보장하지 않는다.

## 실행 구조

주요 기능은 Codex가 실행하는 [.agents/skills](.agents/skills)에 있다.
Python 스크립트가 데이터 수집·점수 계산·제약 검사·보고서 생성을 담당하고,
현재 세션 모델이 뉴스 분류·독립 투자자 분석·최종 투자 판단을 수행한다.

| 단계 | 역할 | 진입점 |
|---|---|---|
| predict | 후보의 상대 순위를 산정한다 | [predict](.agents/skills/predict/SKILL.md) |
| investor-analysis | 관점별로 후보를 독립 분석한다 | [investor-analysis](.agents/skills/investor-analysis/SKILL.md) |
| risk snapshot | 같은 기준일의 가격으로 위험을 계산한다 | [build_risk_snapshot.py](.agents/skills/portfolio-report/scripts/build_risk_snapshot.py) |
| portfolio-report | 종목·ETF·현금 비중을 판단하고 검증한다 | [portfolio-report](.agents/skills/portfolio-report/SKILL.md) |
| backtesting | 과거 전략과 구성 이후 결정을 평가한다 | [backtesting](.agents/skills/backtesting/SKILL.md) |

점수와 confidence는 예상 수익률이나 성공 확률이 아니다. 새 추천은 `--decision-json` 경로로
선택 근거·가격 가정·대안·사용자 제약·재검토 조건을 보존한다. 기존 점수 배분 보고서는
[legacy 계약](.agents/skills/portfolio-report/references/legacy_allocation.md)으로 재현할 수 있다.

## GPT-6 Astra로 사용하기

프로젝트 기본값은 [.codex/config.toml](.codex/config.toml)에 설정되어 있다.

```toml
model = "gpt-6-astra"
model_reasoning_effort = "xhigh"
```

`xhigh`는 마이그레이션 전 사용하던 추론 수준을 유지한 값이며, 최적 비용·속도로 검증한
설정은 아니다. 새 Codex 작업에서 이 프로젝트를 열고 실제 모델과 추론 선택을 확인한다.
프로젝트를 신뢰해야 프로젝트 설정이 로드되며, 명시적 세션 설정이 기본값보다 우선할 수 있다.
파일 변경만으로 이미 실행 중인 세션의 모델이 바뀌었다고 간주하지 않는다.
[공식 Codex 설정 참조](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)

Codex의 기존 인증을 사용한다. 스킬의 Python 코드는 별도의 OpenAI API 호출을 하지 않으므로
이 분석 흐름 때문에 `OPENAI_API_KEY`를 추가할 필요는 없다. Claude Code용
[.claude/skills](.claude/skills)와 에이전트의 기존 모델 선택은 별도로 유지한다.

호환성 판단과 레거시 경계는 [Astra 마이그레이션 기록](docs/GPT_6_ASTRA_MIGRATION.md)을 참고한다.

## 설치와 데이터 설정

Python 3.11 이상과 uv를 사용한다. 저장소 루트에서 의존성을 설치한다.

```powershell
uv sync --frozen
```

데이터 공급자 키가 필요하면 `.env.example`을 참고해 로컬 `.env`를 만든다.
기존 `.env`를 덮어쓰지 않는다. 한국 재무 데이터에는 `DART_API_KEY`가 필요하며
나머지 공급자 키는 사용하는 데이터 경로에 따라 다르다. 각 스킬의 데이터 계약을 따른다.
프로세스 환경변수는 `.env`보다 우선한다. 키·인증 정보·유료 응답 원문은 커밋하지 않는다.

## 사용 예시

Codex 대화에서는 다음과 같이 요청한다.

- `$predict S&P 500 전체 종목의 상대 순위를 분석해줘`
- `$investor-analysis 삼성전자를 버핏 관점에서 분석해줘`
- `$portfolio-report 현재 자료와 내 자금 사용 조건으로 주식·ETF·현금 비중을 추천해줘`

데이터 수집·계산 CLI를 직접 실행할 수도 있다.

```powershell
uv run python .agents/skills/predict/scripts/analyze_stocks.py --index sp500 --display 30 --output results.json
uv run python .agents/skills/predict/scripts/analyze_stocks.py --index krx --display 30 --output krx_results.json
uv run python .agents/skills/investor-analysis/scripts/data_fetcher.py --ticker AAPL
```

포트폴리오 생성·스냅샷·사후 평가의 입력과 명령은
[portfolio-report](.agents/skills/portfolio-report/SKILL.md)에 정의되어 있다.
분석 기준일·provider·실패 또는 대체 원천·불확실성을 함께 기록한다.
최신 데이터를 과거에 알려진 자료처럼 사용하지 않는다.

## 로컬 검증

테스트는 unittest 기반이며 금융 provider 응답을 모의 처리한다.

```powershell
uv run python -m unittest discover -s tests -p "test_*.py" -q
openspec validate migrate-to-gpt-6-astra --strict
git diff --check
```

검증 기록은 [OpenSpec verification](openspec/changes/migrate-to-gpt-6-astra/verification.md)에 있다.
로컬 테스트 통과는 모델의 투자 판단 품질, 실제 provider 접근, OOS 초과성과를 입증하지 않는다.

## 레거시 웹앱

`src/`는 `b6d7ac8`에서 제거되었다. [app/](app/README.md)는 여전히 해당 모듈을 참조하는
레거시 코드이므로 현재 체크아웃에서 완전한 웹 실행 경로로 제공하지 않는다.
그곳의 GPT-4.1 모델 선택기는 현재 Codex 금융 스킬의 모델을 제어하지 않는다.
웹앱 복원이 필요하면 별도 변경에서 누락된 엔진과 Astra Responses 통합을 함께 검증해야 한다.

## 프로젝트 계약

[AGENTS.md](AGENTS.md)와 [.agent-os/manifest.json](.agent-os/manifest.json)을 먼저 확인한다.
여러 세션의 작업은 OpenSpec change의 tasks와 검증 근거로 관리한다.
기존 연구 스냅샷, 사용자의 변경과 미해결 데이터·성과 검증 게이트를 보존한다.
