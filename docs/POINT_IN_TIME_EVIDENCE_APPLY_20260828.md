# Point-in-time evidence gates apply — 2026-08-28

이 문서는 OpenSpec change `point-in-time-evidence-gates`의 구현·증거·차단 상태를
기록한다. 기존 `portfolios/krx_20260827`과 `portfolios/sp500_20260827`은 과거
snapshot으로 보존하며, 새 evidence contract를 통과한 산출물로 소급 표기하지 않는다.

## Provider 준비도

직접 관찰 증거는 `artifacts/evidence/provider_readiness_20260828.json`에 있다. API key
값은 출력하지 않았고, 실패는 숫자 0이나 중립 신호가 아닌 구조화 상태로 기록했다.

| Provider | 역할 | 표본 결과 | 시점·revision 경계 | 순위 영향 |
| --- | --- | --- | --- | --- |
| DART | 기업 기본·재무·공시·주요주주 | `ready`, 삼성전자 기업 표본 1건 | 공시 접수 시각과 정정 전후 vintage를 별도 보존해야 함 | 기업 표본 성공만으로 과거 재무 PIT를 승인하지 않음 |
| KRX Open API | 일별 OHLCV·시총·상장주식수 | `ready`, 2026-08-27 KOSPI 944건 | 요청 거래일 snapshot, 정정 vintage 미제공 | 실제 거래일 정렬 후 가격 근거에만 사용 |
| FinanceDataReader | 수정 OHLCV·현재 상장 목록 | `ready`, 삼성전자 11거래일 | 수정 가격은 바뀔 수 있고 현재 목록은 과거 membership이 아님 | 가격 보조만 허용 |
| PyKRX | OHLCV·valuation·시총·지수 구성 | `empty_sample`, 0건 | 빈 응답을 실제 가격/valuation 0으로 취급하지 않음 | provider 미준비 |
| Naver News | 현재 뉴스 검색 | `auth_failed`, HTTP 401 | 현재 검색 결과에는 과거 결과 집합 vintage가 없음 | 뉴스는 `risk_and_explanation_only` |
| Yahoo chart | S&P 가격 표본 | `ready`, AAPL 11거래일 | 가격은 사용 가능하나 현재 metadata와 수정값은 PIT 재무 근거가 아님 | 가격 보조만 허용 |
| Wikipedia S&P 500 | 현재 구성종목 | `unavailable`, HTTP 403 | 현재 페이지를 과거 전 기간에 소급할 수 없음 | historical membership 미검증 |

판정: 자격 증명은 모두 구성되어 있었지만 7개 표본 중 4개만 성공했다. 따라서
`all_required_ready=false`이며, provider 실패가 관련 factor나 뉴스 점수 0으로
변환되지 않도록 `missing_evidence_requires_prior_or_explanation_only`를 적용한다.

## Requirement 대조

| Requirement | 구현·검증 | 현재 상태 |
| --- | --- | --- |
| Provider readiness before ranking | `provider_readiness.py`가 provider·자격 증명 이름·필드·as-of·revision·quota 인벤토리와 실제 표본 상태를 생성한다. `analyze_stocks.py`는 snapshot 미제공·실패를 `provider_readiness_policy`로 직렬화한다. | `PASS_LOCAL`, live provider 3종 미준비 |
| Point-in-time and OOS factor evidence | `factor_evidence.py`와 backtesting 계약이 timing, duplicate execution, monthly alignment, 비용, IC, coverage, turnover, ablation, holdout, 원시 지표 등급 재계산을 제공한다. | 구현 회귀는 통과했지만 KRX/S&P용 historical membership+vintage 7-factor panel이 없어 `UNVALIDATED` |
| Missing evidence is not neutral evidence | 미제공 evidence는 `prior_only`+7개 `unvalidated`, 불일치는 `invalid_factor_evidence_fallback_to_prior_only`, 전부 contradicted이면 prior 상대 비중과 명시적 `fallback_reason`을 쓴다. | `PASS_LOCAL` |
| News requires independent three-part validation | semantic/predictive/portfolio와 sentiment factor evidence의 교집합만 순위 반영하며 테스트에서 일부 gate 통과를 거부한다. | 독립 gold label·동결 미래 holdout·동일 조건 portfolio 비교가 없어 `risk_and_explanation_only` |
| Reproducible staged analysis and reporting | portfolio-report는 독립 investor 결과와 동일 analysis date, risk snapshot을 요구하며 `predict -> independent_investor_analysis -> risk_snapshot -> portfolio_report`와 evidence provenance를 새 JSON에 직렬화한다. | 구현 회귀 `PASS_LOCAL`; 2026-08-27 기존 산출물은 새 provenance 이전 snapshot이라 재생성 전 `LEGACY_UNVALIDATED` |

## 기존 snapshot 감사

직접 관찰 결과 KRX/S&P의 2026-08-27 predict JSON에는 `factor_weight_policy`,
`provider_readiness_policy`가 없고 portfolio JSON에는 새 `research_provenance`가 없다.
KRX news 결과도 공통 sentiment factor evidence와 세 독립 gate를 모두 통과했다는 증거가
없다. 따라서 이 파일들은 당시 산출물로 보존하되 새 품질 계약을 통과했다고 주장하지
않는다. 새 snapshot 생성은 다음을 모두 만족한 뒤에만 한다.

1. 시장별 historical membership과 재무/공시 vintage를 포함한 월간 7-factor panel
2. 다음 실제 거래일 체결·비용·독립 holdout을 사용한 factor evidence JSON
3. 결과를 보지 않은 gold label, 동결 미래 holdout, 뉴스 미사용 기준 portfolio 비교
4. provider readiness, factor/news policy, analysis independence, risk/constraint provenance

## 검증과 범위

- `uv run python -m unittest discover -s tests -v`: 77개 통과.
- provider unit 회귀는 auth/timeout/quota/schema/empty를 구조화하고 실제 0과 빈
  evidence를 구분한다.
- 금융 회귀는 lookahead, historical membership, filing revision, factor grade 재계산,
  invalid/contradicted fallback, 뉴스 3-part gate, 독립 investor 입력, risk as-of,
  포트폴리오 name/sector/cash 제약을 포함한다.
- `.agents`와 `.claude`의 변경된 금융 스킬 mirror가 동일하고 `git diff --check`가
  통과했다.
- 생성 캐시, `portfolios/krx_20260827`, 대량 스킬 정리와 기타 사용자 dirty work는
  변경 범위에서 제외했다.

## 완료로 보지 않는 것

이번 apply는 실제 거래, 주문, 자금 이동, broker 연결, 성과 보장, 외부 공개를 수행하지
않았다. 7-factor PIT/OOS, 뉴스 독립 검증, 기존 KRX/S&P snapshot 재생성은 아직
미완료다. 현재 허용되는 주장은 provider 상태가 구조화되었고 미검증 증거가 순위 확신으로
승격되지 않는다는 것까지다.

## OpenSpec verification report

| 차원 | 상태 |
| --- | --- |
| Completeness | 7/13 tasks. 5/5 requirements가 구현·계약·테스트에 매핑됨 |
| Correctness | 10개 scenario 중 8개 동작 경로를 회귀로 확인. 독립 뉴스 전체 통과와 새 KRX/S&P 실제 산출물 scenario는 미검증 |
| Coherence | provider 선행 감사, 원시 지표 재등급, 뉴스 교집합 gate, 독립 분석 후 집계라는 4개 design 결정을 따름 |

### CRITICAL — archive 전에 반드시 해결

- Task 2.1: KRX와 S&P 각각 historical membership과 재무/공시 vintage가 있는
  월간 panel을 만들고 lookahead·중복 execution·기간 정렬 검사를 통과한다.
- Task 2.2: 그 panel로 7개 `predict_factor_v1`의 비용 차감 IC, coverage,
  turnover, ablation과 독립 holdout을 재현한다.
- Task 3.1: 결과·미래수익률을 보지 않은 독립 gold label로 `news_event_v2`
  semantic gate를 검증한다.
- Task 3.2: 임계값을 먼저 동결한 미래 holdout과 다음 실제 거래일 체결로 predictive
  gate를 검증한다.
- Task 3.3: 동일 유니버스·제약·비용의 뉴스 미사용 기준 portfolio와 독립 창 2개
  이상을 비교한다. 그 전에는 `risk_and_explanation_only`를 유지한다.
- Task 4.2: 위 검증과 provider 복구 후 KRX/S&P를 새 provenance 계약으로 재생성하고
  제약·as-of·상태·범위·한계를 실제 산출물에서 확인한다.

구현과 design 사이의 추가 WARNING 또는 패턴 불일치는 발견하지 못했다. 6개
CRITICAL gate 때문에 change는 archive할 수 없고, 기존 2026-08-27 결과는
`LEGACY_UNVALIDATED`로 남는다.
