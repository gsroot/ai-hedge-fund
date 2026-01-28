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

상위 N개 종목 각각에 대해 investor-analysis 스킬 호출.

1. 선택된 투자자 에이전트들을 **병렬로** Task 도구를 통해 호출
2. 각 투자자별 `{signal, confidence, reasoning}` 수집
3. 투자자별 가중 평균으로 종합 신호 계산

**병렬 실행 전략**:
- 종목 수가 10개 이하: 모든 종목 × 투자자 조합을 한 번에 병렬 실행
- 종목 수가 10개 초과: 5개씩 배치로 나눠 순차 배치 내 병렬 실행

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

predict 실행 및 investor-analysis 완료 후 결과를 항상 아래 형식으로 출력.

### Section 1: 헤더

```
══════════════════════════════════════════════════════════════════════════════════════════════
📋 AI Hedge Fund 포트폴리오 리포트
══════════════════════════════════════════════════════════════════════════════════════════════
분석 일자    : 2025-01-28
분석 대상    : S&P 500 상위 30개 종목
분석 전략    : 하이브리드 (펀더멘털 70% + 모멘텀 30%)
투자자 관점  : Warren Buffett, Peter Lynch, Phil Fisher
데이터 소스  : Yahoo Finance (predict) + LLM (investor-analysis)
══════════════════════════════════════════════════════════════════════════════════════════════
```

### Section 2: 포트폴리오 구성표

포트폴리오에 편입된 종목만 표시 (투자자 과반 bullish 필터 통과).

```
══════════════════════════════════════════════════════════════════════════════════════════════
📊 포트폴리오 구성
══════════════════════════════════════════════════════════════════════════════════════════════
#   종목                     비중     시총       종합신호       신뢰도   예상수익률   P/E    ROE      합의
─────────────────────────────────────────────────────────────────────────────────────────────
1   NVDA(NVIDIA)             12.5%    $3,400B   🟢 강력매수     92%     +22.6%      68.5   115.0%   3/3
2   META(Meta Platforms)     10.3%    $1,660B   🟢 강력매수     88%     +20.0%      23.1   28.0%    3/3
3   GOOGL(Alphabet)           8.7%    $2,250B   🔵 매수         82%     +17.0%      21.5   25.0%    2/3
4   MSFT(Microsoft)           8.2%    $3,100B   🔵 매수         78%     +15.5%      34.2   38.0%    2/3
...
─────────────────────────────────────────────────────────────────────────────────────────────
    합계                    100.0%                              avg 81%  avg +16.2%
```

열 설명:
- **비중**: 포트폴리오 배분 비율 (합계 100%)
- **종합신호**: 투자자들의 가중 종합 판단
- **신뢰도**: 투자자 confidence 가중 평균
- **예상수익률**: predict 1년 후 예상 수익률
- **합의**: bullish 투자자 수 / 총 투자자 수

### Section 3: 투자자별 종목 분석 매트릭스

종목 × 투자자 교차 테이블. 각 셀에 신호와 신뢰도 표시.

```
══════════════════════════════════════════════════════════════════════════════════════════════
👥 투자자별 종목 분석 매트릭스
══════════════════════════════════════════════════════════════════════════════════════════════
종목                     W.Buffett        P.Lynch          P.Fisher
─────────────────────────────────────────────────────────────────────────────────────────────
NVDA(NVIDIA)             🟢 bullish(92)   🟢 bullish(88)   🟢 bullish(95)
META(Meta Platforms)     🟢 bullish(90)   🟢 bullish(85)   🟢 bullish(82)
GOOGL(Alphabet)          🟢 bullish(85)   🔵 neutral(60)   🟢 bullish(80)
AAPL(Apple)              🟢 bullish(88)   🔵 neutral(55)   🔵 neutral(65)
TSLA(Tesla)              🔴 bearish(70)   🔵 neutral(50)   🟢 bullish(75)
...
```

### Section 4: 투자자별 핵심 분석 근거

각 투자자가 상위 종목들에 대해 제시한 핵심 근거 요약.

```
══════════════════════════════════════════════════════════════════════════════════════════════
💬 투자자별 핵심 분석 근거 (상위 5개 종목)
══════════════════════════════════════════════════════════════════════════════════════════════

▸ NVDA (NVIDIA) — 종합: 🟢 강력매수 (신뢰도 92%)
  Warren Buffett  : 🟢 (92%) 압도적 ROE 115%, 데이터센터 독점적 moat, 잉여현금흐름 우수
  Peter Lynch     : 🟢 (88%) PEG 1.2로 성장 대비 합리적 가격, AI 수혜 성장 스토리 명확
  Phil Fisher     : 🟢 (95%) R&D 투자 27%, CUDA 생태계 진입장벽, 경영진 비전 탁월

▸ META (Meta Platforms) — 종합: 🟢 강력매수 (신뢰도 88%)
  Warren Buffett  : 🟢 (90%) 강한 네트워크 효과 moat, P/E 23 적정, 광고 독점력
  Peter Lynch     : 🟢 (85%) PEG 1.1, 리얼스 성장 모멘텀, 내부자 보유 지속
  Phil Fisher     : 🟢 (82%) AI 인프라 R&D 적극 투자, 장기 성장 경로 명확

▸ GOOGL (Alphabet) — 종합: 🔵 매수 (신뢰도 82%)
  Warren Buffett  : 🟢 (85%) 검색 moat 견고, 클라우드 성장, FCF 마진 25%+
  Peter Lynch     : 🔵 (60%) PEG 1.5로 다소 비쌈, 성장률 둔화 우려
  Phil Fisher     : 🟢 (80%) AI/클라우드 R&D 리더, 경영진 기술력 우수
...
```

### Section 5: 포트폴리오 요약 통계

```
══════════════════════════════════════════════════════════════════════════════════════════════
📈 포트폴리오 요약
══════════════════════════════════════════════════════════════════════════════════════════════
편입 종목 수         : 18개 / 분석 30개 (60.0% 편입률)
평균 신뢰도          : 81%
평균 예상 수익률     : +16.2%
강력매수 비중        : 45.3%
매수 비중            : 54.7%

투자자 합의 분포:
  만장일치 (3/3)     : 10개 (55.6%) — NVDA, META, MSFT 외 7개
  다수 합의 (2/3)    : 8개 (44.4%) — GOOGL, AAPL, AMZN 외 5개

시가총액 분포:
  메가캡 (>$200B)    : 62.5% — NVDA 12.5%, META 10.3%, MSFT 8.2% 외
  대형주 ($10-200B)  : 30.8% — AMD 5.2%, CRM 4.8% 외
  중형주 ($2-10B)    :  6.7% — ...

섹터 분포:
  Technology         : 34.2% (제한 35% 내)
  Communication      : 18.5%
  Healthcare         : 12.3%
  Consumer Disc.     : 10.8%
  Financial          :  9.5%
  기타               : 14.7%
```

### Section 6: 비편입 종목 사유

분석 대상이었으나 포트폴리오에 편입되지 않은 종목과 그 사유.

```
══════════════════════════════════════════════════════════════════════════════════════════════
🚫 비편입 종목 (12개)
══════════════════════════════════════════════════════════════════════════════════════════════
종목                     순위   점수    사유
─────────────────────────────────────────────────────────────────────────────────────────────
TSLA(Tesla)              8      7.20   투자자 과반 미달 (1/3 bullish)
INTC(Intel)              15     5.85   투자자 과반 미달 (0/3 bullish)
BA(Boeing)               22     4.30   투자자 과반 미달 (0/3 bullish)
...
```

### Section 7: 경고 및 리스크

```
══════════════════════════════════════════════════════════════════════════════════════════════
⚠️ 리스크 및 경고
══════════════════════════════════════════════════════════════════════════════════════════════
포트폴리오 집중도:
  상위 5종목 비중     : 48.4% (과집중 주의)
  최대 단일 종목      : NVDA 12.5% (제한 15% 내)
  최대 섹터 비중      : Technology 34.2% (제한 35% 내)

투자 철학 불일치 경고:
  TSLA(Tesla)  : Lynch 높은 점수 + 메가캡($800B+) → 10배주 불가능
  XOM(Exxon)   : Buffett 높은 점수 + 원자재/에너지 → 철학 충돌

투자자 의견 분산 종목 (낮은 합의):
  TSLA : Buffett 🔴 bearish vs Fisher 🟢 bullish (의견 극단 분산)
```

### Section 8: 푸터

```
══════════════════════════════════════════════════════════════════════════════════════════════
💡 이 리포트는 교육/연구 목적이며 실제 투자 결정의 근거가 될 수 없습니다.
   predict: Yahoo Finance | investor-analysis: LLM 기반 정성 분석
   엑셀 리포트: portfolios/sp500_20250128_buffett_lynch_fisher.xlsx
══════════════════════════════════════════════════════════════════════════════════════════════
```

## 출력 규칙

1. **항상 Section 1~8 순서를 지킴** (해당 데이터가 없는 섹션은 생략)
2. **신호 표기 통일**: 포트폴리오 테이블에서는 `🟢 강력매수` / `🔵 매수`, 매트릭스에서는 `🟢 bullish(90)` / `🔵 neutral(60)` / `🔴 bearish(70)`
3. **숫자 포맷**: 비중 `12.5%`, 수익률 `+22.6%`/`-5.2%`, P/E `68.5`, ROE `115.0%`, 신뢰도 `92%`, 시총 `$3,400B`/`₩320조`
4. **N/A 처리**: 데이터 없으면 `N/A` 표시
5. **구분선**: `═` (섹션 구분), `─` (테이블 헤더 아래)
6. **합의 표기**: `3/3` (bullish 수 / 총 투자자 수)
7. **한국 종목**: 시총 `₩` 접두사 + 조/억 단위, 종목명 한글 표시
8. **Section 4 분석 근거**: 종목당 투자자별 1-2문장으로 핵심만. 포트폴리오 편입 상위 5개 종목만 상세 표시

---

## 엑셀 리포트 사양

### 파일 경로 및 파일명

```
portfolios/{index}_{YYYYMMDD}_{investors}.xlsx
```

| 구성 요소 | 규칙 | 예시 |
|-----------|------|------|
| `{index}` | 분석 인덱스 (소문자) | `sp500`, `nasdaq100`, `krx` |
| `{YYYYMMDD}` | 분석 일자 | `20250128` |
| `{investors}` | 투자자 식별자 (`_` 구분, 알파벳순) | `buffett_fisher_lynch` |

예시:
- `portfolios/sp500_20250128_buffett_fisher_lynch.xlsx`
- `portfolios/nasdaq100_20250128_all.xlsx`
- `portfolios/krx_20250128_buffett_graham_munger.xlsx`
- 특정 종목 분석: `portfolios/custom_20250128_buffett_fisher_lynch.xlsx`

`portfolios/` 디렉터리가 없으면 자동 생성.

### 시트 구성 (6개)

#### 시트 1: Summary

포트폴리오 전체 요약 정보를 한 눈에 볼 수 있는 대시보드.

| 행 | A열 (항목) | B열 (값) |
|----|-----------|---------|
| 1 | **AI Hedge Fund 포트폴리오 리포트** | *(병합 셀, 제목)* |
| 3 | 분석 일자 | 2025-01-28 |
| 4 | 분석 대상 | S&P 500 상위 30개 |
| 5 | 분석 전략 | 하이브리드 |
| 6 | 투자자 관점 | W.Buffett, P.Lynch, P.Fisher |
| 8 | **포트폴리오 통계** | |
| 9 | 편입 종목 수 | 18 / 30 (60.0%) |
| 10 | 평균 신뢰도 | 81% |
| 11 | 평균 예상 수익률 | +16.2% |
| 12 | 강력매수 비중 | 45.3% |
| 14 | **시가총액 분포** | |
| 15 | 메가캡 (>$200B) | 62.5% |
| 16 | 대형주 ($10-200B) | 30.8% |
| 17 | 중형주 ($2-10B) | 6.7% |
| 19 | **섹터 분포** | |
| 20~ | (섹터명) | (비중%) |

- A15:B20+ 영역에 **섹터 분포 파이 차트** 삽입 (오른쪽 D~J열 영역)

#### 시트 2: Portfolio

포트폴리오 편입 종목의 비중 배분표.

| 열 | 헤더 | 포맷 | 설명 |
|----|------|------|------|
| A | # | 정수 | 포트폴리오 내 순번 |
| B | Ticker | 텍스트 | 종목 코드 |
| C | Company | 텍스트 | 회사명 |
| D | Weight | 0.0% | 포트폴리오 비중 |
| E | Signal | 텍스트 | 종합 신호 (strong_buy/buy) |
| F | Confidence | 정수 | 종합 신뢰도 (0-100) |
| G | Expected Return | +0.0% | 1년 후 예상 수익률 |
| H | Market Cap | 텍스트 | 시가총액 |
| I | P/E | 0.0 | 주가수익비율 |
| J | ROE | 0.0% | 자기자본이익률 |
| K | PEG | 0.0 | Price/Earnings to Growth |
| L | Consensus | 텍스트 | 합의 (예: "3/3") |
| M | Sector | 텍스트 | 섹터 |

- 마지막 행: **합계/평균 행** (Weight 합계 100%, Confidence/Return은 가중평균)
- Weight 열 기준 **내림차순 정렬**

#### 시트 3: Ranking

predict 상위 N개 전체 순위표 (편입/비편입 모두 포함).

| 열 | 헤더 | 포맷 | 설명 |
|----|------|------|------|
| A | Rank | 정수 | 전체 순위 |
| B | Ticker | 텍스트 | 종목 코드 |
| C | Company | 텍스트 | 회사명 |
| D | Total Score | 0.00 | 전략별 최종 점수 |
| E | Fundamental | 0.0 | 펀더멘털 점수 |
| F | Momentum | 0.0 | 모멘텀 점수 |
| G | Ensemble | 0.0 | 앙상블 점수 |
| H | Signal | 텍스트 | predict 신호 |
| I | Expected Return | +0.0% | 예상 수익률 |
| J | Market Cap | 텍스트 | 시가총액 |
| K | P/E | 0.0 | |
| L | P/B | 0.0 | |
| M | ROE | 0.0% | |
| N | Rev Growth | 0.0% | 매출 성장률 |
| O | PEG | 0.0 | |
| P | In Portfolio | Yes/No | 포트폴리오 편입 여부 |

- P열이 "Yes"인 행은 연한 초록 배경
- P열이 "No"인 행은 배경색 없음

#### 시트 4: Investor Matrix

종목(행) × 투자자(열) 교차 테이블. 각 셀에 signal과 confidence.

| 열 | 헤더 |
|----|------|
| A | Ticker |
| B | Company |
| C~ | (투자자 이름) — 셀 값: `bullish(92)` / `neutral(60)` / `bearish(70)` |
| 마지막 열 | Combined Signal |
| 마지막 열+1 | Combined Confidence |

- bullish 셀: 연한 초록 배경 (#E2EFDA)
- bearish 셀: 연한 빨간 배경 (#FCE4EC)
- neutral 셀: 연한 회색 배경 (#F5F5F5)

#### 시트 5: Investor Detail

투자자별 상세 분석 근거. 종목 × 투자자별 reasoning 텍스트.

| 열 | 헤더 | 설명 |
|----|------|------|
| A | Ticker | 종목 코드 |
| B | Company | 회사명 |
| C | Investor | 투자자 이름 |
| D | Signal | bullish/neutral/bearish |
| E | Confidence | 0-100 |
| F | Reasoning | 분석 근거 (1-2문장) |

- 종목별로 행이 투자자 수만큼 반복 (예: 30종목 × 3투자자 = 90행)
- A열은 같은 종목이면 병합하지 않되, 종목 변경 시 **상단 테두리** 추가

#### 시트 6: Risk Analysis

포트폴리오 리스크 지표.

| 행 | A열 (항목) | B열 (값) |
|----|-----------|---------|
| 1 | **리스크 분석** | *(제목)* |
| 3 | **집중도 지표** | |
| 4 | 상위 1종목 비중 | 12.5% |
| 5 | 상위 3종목 비중 | 31.5% |
| 6 | 상위 5종목 비중 | 48.4% |
| 7 | 상위 10종목 비중 | 72.1% |
| 8 | HHI (허핀달 지수) | 0.042 |
| 10 | **섹터 집중도** | |
| 11 | 최대 섹터 | Technology (34.2%) |
| 12 | 상위 3섹터 비중 | 65.0% |
| 14 | **투자자 합의 품질** | |
| 15 | 만장일치 비율 | 55.6% |
| 16 | 의견 분산 종목 수 | 3개 |
| 18 | **비편입 사유 분포** | |
| 19 | 투자자 과반 미달 | 10개 |
| 20 | 최소 비중 미달 | 2개 |

### 공통 스타일링 규칙

| 요소 | 스타일 |
|------|--------|
| 헤더 행 | 배경 #1F4E79, 폰트 White, Bold, 12pt |
| 제목 셀 | 배경 #2E75B6, 폰트 White, Bold, 14pt |
| bullish 셀 | 배경 #E2EFDA, 폰트 #375623 |
| bearish 셀 | 배경 #FCE4EC, 폰트 #C62828 |
| neutral 셀 | 배경 #F5F5F5, 폰트 #616161 |
| 합계/평균 행 | 배경 #D6E4F0, Bold |
| 숫자 포맷 | 비중 `0.0%`, 수익률 `+0.0%;-0.0%`, P/E `0.0`, ROE `0.0%`, 신뢰도 `0`, 점수 `0.00` |
| 열 너비 | 자동 조정 (최소 8, 최대 30) |
| 행 높이 | 데이터 행 18pt, 헤더 22pt |
| 테두리 | 얇은 회색 (#D9D9D9) 전체 격자 |
| 틀 고정 | 각 시트 헤더 행 아래 고정 (Freeze Panes) |
| 필터 | Portfolio, Ranking, Investor Matrix 시트에 자동 필터 |

---

## 주의사항

- predict 실행은 종목 수에 따라 수 분 소요될 수 있음
- investor-analysis는 종목당 투자자 수만큼 LLM 호출 발생 → 비용 주의
- 이 스킬은 교육/연구 목적이며 실제 투자 결정의 근거가 될 수 없음
