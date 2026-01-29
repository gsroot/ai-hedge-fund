---
name: portfolio-report
description: |
  predict 순위 결과의 상위 종목을 investor-analysis로 심층 분석하여 투자 리포트 및 포트폴리오를 구성하는 오케스트레이터 스킬.
  세 스킬 조합: predict (순위 산정) → investor-analysis (투자자 관점 분석) → xlsx (엑셀 리포트 생성).
  사용 시점: "투자 리포트 만들어줘", "포트폴리오 구성해줘", "상위 종목 분석 리포트",
  "predict 결과로 투자 분석", "순위표 기반 포트폴리오", "엑셀 투자 리포트",
  "상위 30개 종목 버핏 관점으로 분석", "투자 포트폴리오 엑셀로 만들어줘"
---

# Portfolio Report

predict 순위표의 상위 N개 종목에 대해 선택한 투자자 관점으로 심층 분석 후 포트폴리오를 구성하는 오케스트레이터.

## 인자 (Arguments)

```
/portfolio-report [top-n] [investors] [xlsx]
```

| 인자 | 위치 | 설명 | 기본값 |
|------|------|------|--------|
| `top-n` | `$0` | 분석할 상위 종목 수 | `30` |
| `investors` | `$1` | 투자자 관점 (콤마 구분) | `buffett,lynch,fisher` |
| `xlsx` | `$2` | 엑셀 리포트 생성 여부 | `yes` |

### 인자 해석 규칙

**top-n** (`$0`):
- 숫자만 입력: `30`, `50`, `10`
- "상위 N개" 형태도 허용: `상위 50개` → 50
- 비어있거나 `$0` 그대로이면 기본값 `30`

**investors** (`$1`):
- 콤마 구분 투자자 식별자:
  - `buffett` → warren-buffett-analyst
  - `lynch` → peter-lynch-analyst
  - `fisher` → phil-fisher-analyst
  - `munger` → charlie-munger-analyst
  - `graham` → ben-graham-analyst
  - `wood` → cathie-wood-analyst
  - `burry` → michael-burry-analyst
  - `ackman` → bill-ackman-analyst
  - `druckenmiller` → stanley-druckenmiller-analyst
  - `damodaran` → aswath-damodaran-analyst
  - `pabrai` → mohnish-pabrai-analyst
  - `jhunjhunwala` → rakesh-jhunjhunwala-analyst
  - `all` → 12명 전원
- 한국어도 허용: `버핏,린치,피셔` → `buffett,lynch,fisher`
- 비어있거나 `$1` 그대로이면 기본값 `buffett,lynch,fisher`

**xlsx** (`$2`):
- `yes`, `true`, `1`, `엑셀`, `excel` → 엑셀 생성
- `no`, `false`, `0`, `없이` → 엑셀 미생성
- 비어있거나 `$2` 그대로이면 기본값 `yes`

### 사용 예시

```
/portfolio-report                          → 상위 30개, 버핏/린치/피셔, 엑셀 O
/portfolio-report 50                       → 상위 50개, 버핏/린치/피셔, 엑셀 O
/portfolio-report 20 buffett,munger,graham → 상위 20개, 버핏/멍거/그레이엄, 엑셀 O
/portfolio-report 30 all                   → 상위 30개, 12명 전원, 엑셀 O
/portfolio-report 10 lynch,fisher no       → 상위 10개, 린치/피셔, 엑셀 X
```

---

## 워크플로우

### Phase 1: 종목 선별 (predict)

predict 스킬을 사용하여 순위 산정 실행.

1. predict 스킬에 사용자가 이전에 지정한 인덱스/티커 조건 전달 (없으면 `--index sp500` 기본)
2. 하이브리드 전략으로 전체 종목 분석 실행
3. 결과에서 **상위 N개 종목의 티커 목록**을 추출
4. 각 종목의 predict 점수, 신호, 예상 수익률을 기록

**중요**: predict 결과가 이미 현재 대화에 존재하면 재실행하지 않고 기존 결과를 사용.

Phase 1에서 종목별로 수집하는 데이터:

| 필드 | 출처 | 설명 |
|------|------|------|
| `rank` | predict | 전체 순위 |
| `ticker` | predict | 종목 코드 |
| `company_name` | predict | 회사명 |
| `total_score` | predict | 전략별 최종 점수 |
| `ensemble_score` | predict | 투자자 앙상블 점수 |
| `signal` | predict | strong_buy/buy/hold/weak_sell/sell |
| `predicted_return_1y` | predict | 1년 후 예상 수익률 (%) |
| `market_cap.display` | predict | 시가총액 표시 문자열 |
| `market_cap.category` | predict | mega/large/mid/small |
| `metrics.pe` | predict | P/E |
| `metrics.pb` | predict | P/B |
| `metrics.roe` | predict | ROE (%) |
| `metrics.revenue_growth` | predict | 매출 성장률 (%) |
| `metrics.peg` | predict | PEG |
| `scores.fundamental` | predict | 펀더멘털 점수 |
| `scores.enhanced_momentum` | predict | 모멘텀 점수 |
| `investor_scores` | predict | 5인 투자자 점수 (buffett/lynch/graham/fisher/druckenmiller) |
| `investor_consensus` | predict | 합의도 (level, std, bullish/bearish 리스트) |
| `investor_warnings` | predict | 철학 불일치 경고 |

### Phase 2: 투자자 관점 심층 분석 (investor-analysis)

상위 N개 종목 각각에 대해 선택된 투자자 에이전트 호출.

**호출 방법**: Task 도구로 투자자 에이전트 호출 (예: `warren-buffett-analyst`, `peter-lynch-analyst`)

상세 동작 방식은 [investor-analysis SKILL.md](../investor-analysis/SKILL.md) 참조.

Phase 2에서 종목별 × 투자자별로 수집하는 데이터:

| 필드 | 출처 | 설명 |
|------|------|------|
| `signal` | investor-analysis | bullish/bearish/neutral |
| `confidence` | investor-analysis | 0-100 신뢰도 |
| `reasoning` | investor-analysis | 분석 근거 요약 (1-2문장) |

### Phase 3: 포트폴리오 구성

분석 결과를 종합하여 포트폴리오 구성.

1. **종목 필터링**: 투자자 과반수 이상 bullish인 종목만 포트폴리오에 포함
2. **비중 산정**: 종합 confidence 기반 비례 배분 (confidence 합계 = 100%)
3. **최대 비중 제한**: 단일 종목 최대 15%
4. **최소 비중 제한**: 단일 종목 최소 2% (미만이면 제외)
5. **섹터 분산**: 단일 섹터 최대 35%

Phase 3에서 종목별로 산출하는 데이터:

| 필드 | 산출 방식 | 설명 |
|------|-----------|------|
| `weight` | confidence 비례 배분 → 제한 적용 | 포트폴리오 비중 (%) |
| `combined_signal` | 투자자 과반 신호 | 종합 신호 |
| `combined_confidence` | 투자자 confidence 가중 평균 | 종합 신뢰도 (0-100) |
| `bullish_count` | bullish 투자자 수 | 매수 의견 수 |
| `bearish_count` | bearish 투자자 수 | 매도 의견 수 |
| `consensus_ratio` | bullish_count / 총 투자자 수 | 합의 비율 |
| `sector` | market_cap.category 기반 | 섹터 분류 |

### Phase 4: 엑셀 리포트 생성 (xlsx 스킬, 조건부)

xlsx 인자가 `yes`일 때만 실행. 상세 사양은 [엑셀 리포트 사양](#엑셀-리포트-사양) 참조.

---

## 표준 출력 형식

분석 완료 후 Section 1~8 순서로 콘솔에 리포트 출력.

상세 형식은 [references/output_format_spec.md](references/output_format_spec.md) 참조.

---

## 엑셀 리포트 사양

**호출 방법**: xlsx 스킬 사용 (openpyxl 기반)

상세 사양은 [references/excel_report_spec.md](references/excel_report_spec.md) 참조.

---

## 주의사항

- predict 실행은 종목 수에 따라 수 분 소요될 수 있음
- investor-analysis는 종목당 투자자 수만큼 LLM 호출 발생 → 비용 주의
- 이 스킬은 교육/연구 목적이며 실제 투자 결정의 근거가 될 수 없음
