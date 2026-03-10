---
name: predict
description: |
  다중 팩터 앙상블 분석 기반 주식 수익률 예측 및 순위 산정 시스템.
  전설적 투자자들의 분석 방식을 종합하여 최대 500개 종목을 배치 처리.
  S&P 500, NASDAQ 100 + KOSPI, KOSDAQ 인덱스 지원.
  펀더멘털, 모멘텀, 하이브리드 전략 선택 가능. 시가총액 내림차순 정렬 기본 적용.
  사용 시점: "/predict", "수익률 예측", "순위 분석", "종목 추천",
  "1년 후 가장 수익률 좋을 종목은?", "어떤 종목을 사야 할까?",
  "AAPL, GOOGL, MSFT 중 뭘 사야해?",
  "S&P 500 분석", "S&P 500 종목 중 상위 10개 추천",
  "NASDAQ 분석", "NASDAQ 100 순위",
  "KOSPI 분석", "KOSPI 상위 종목 분석", "KOSDAQ 150 순위",
  "한국 전체 시장 분석", "KRX 전체 분석",
  "KOSPI200+KOSDAQ150 분석" → --index krx 사용 (두 인덱스를 분리 실행하지 말 것),
  "상위 종목 추천", 포트폴리오 순위, 투자 우선순위 결정
---

# Predict

다중 팩터 분석을 기반으로 종목 수익률을 예측하고 순위를 산정하는 시스템.
**최대 500개 종목을 배치 처리**할 수 있으며, S&P 500, NASDAQ 100 및 KOSPI, KOSDAQ, KRX 인덱스를 지원합니다.

## 인자 해석

`$ARGUMENTS` 또는 자연어 요청을 아래 규칙에 따라 해석하고 스크립트를 실행.

### 1. 인덱스 (`--index`)
- `sp500`, `s&p500`, `S&P 500`, `S&P500` → `--index sp500`
- `nasdaq100`, `nasdaq`, `NASDAQ 100`, `나스닥` → `--index nasdaq100`
- `kospi`, `KOSPI` → `--index kospi`
- `kosdaq`, `KOSDAQ` → `--index kosdaq`
- `kospi200`, `KOSPI 200`, `코스피200` → `--index kospi200`
- `kosdaq150`, `KOSDAQ 150`, `코스닥150` → `--index kosdaq150`
- `krx`, `KRX`, `한국`, `한국전체`, `kospi200+kosdaq150`, `KOSPI200+KOSDAQ150` → `--index krx`
- 인덱스·종목 모두 없으면 기본값 `--index sp500`

### 2. 종목 (`--tickers`)
- 콤마 구분 티커: `AAPL,MSFT,NVDA` → `--tickers AAPL,MSFT,NVDA`
- 한국 종목 코드: `005930,000660` → `--tickers 005930,000660`
- `--index`와 `--tickers` 동시 지정 시 `--tickers` 우선

### 3. 전략 (기본값: hybrid, 별도 플래그 불필요)
- hybrid 전략 시 **`--strategy` 인자를 추가하지 말 것** (스크립트 기본값)
- 다른 전략 명시 요청 시에만:
  - `fundamental`, `펀더멘털` → `--strategy fundamental`
  - `momentum`, `모멘텀` → `--strategy momentum`

### 4. 분석 대상 종목 수 (`--top`)
- `top 50`, `상위 50개 분석`, `50개 분석` → `--top 50`
- `--top` 미지정 시 전체 종목 분석

### 5. 결과 표시 순위 수 (`--display`)
- `display 30`, `30위까지`, `상위 30개 보여줘` → display 30
- `--display` 미지정 시 기본값: **30** (항상 상위 30개 표시)
- `--top`과의 차이: `--top`은 분석 대상 종목 수를 제한, `--display`는 분석 완료 후 순위표에 몇 위까지 보여줄지를 결정
- 예: `--index sp500 --display 30` → S&P 500 전체(~500개) 분석 후 상위 30개만 순위표에 표시

### 6. 시가총액 정렬 비활성화 (`--no-sort-by-cap`)
- 시가총액 내림차순 정렬은 기본 동작
- `정렬없이`, `no-sort-by-cap` → `--no-sort-by-cap`

### 7. 기타
- `no-cache`, `캐시없이`, `새로` → `--no-cache`
- `output 파일명.json` → `--output 파일명.json`
- `period 6M`, `6개월` → `--period 6M`

### 해석 예시

| 사용자 입력 | 해석 |
|-------------|------|
| `--index sp500 --display 30` | S&P 500 전체 분석 후 상위 30개 표시 |
| `--index krx` | KRX 전체 분석, 상위 30개 표시 |
| `--index sp500 --top 50` | S&P 500 시가총액 상위 50개만 분석 |
| `--tickers AAPL,MSFT,NVDA` | 3개 종목 분석 |
| `--index nasdaq100 --strategy momentum --top 20` | NASDAQ 100 상위 20개 모멘텀 분석 |
| `나스닥 상위 30위까지 보여줘` | NASDAQ 100 전체 분석 후 상위 30개 표시 |
| (빈 입력) | S&P 500 전체 분석, 상위 30개 표시 |

## 스크립트 실행

```bash
uv run python .Codex/skills/predict/scripts/analyze_stocks.py \
  --index sp500
```

인자가 비어있거나 `$ARGUMENTS`가 그대로이면 기본값(`--index sp500`)으로 전체 종목 분석. 시가총액 정렬 및 하이브리드 전략은 스크립트 기본 동작이므로 별도 CLI 플래그 불필요.

## 표준 출력 형식

스크립트 실행 후, 결과를 **[references/output_format.md](references/output_format.md)** 에 정의된 8-Section 형식으로 재포맷하여 반환. 스크립트 stdout을 그대로 보여주지 말 것.

8-Section 구조: 헤더 → 순위표 → 분석 요약 → 투자자별 강세 종목 → 합의도 → 경고 → 시가총액 분포 → 푸터.

---

## 분석 방법론

### 앙상블 기반 멀티 팩터 모델

전설적인 투자자들의 투자 철학을 **7가지 팩터**와 **투자자별 점수**로 통합:

#### 팩터별 가중치

| 팩터 | 가중치 | 투자자 스타일 | 주요 지표 |
|------|--------|--------------|----------|
| **Value** | 25% | 버핏, 그레이엄, 멍거 | P/E, P/B, EV/EBITDA, FCF Yield |
| **Growth** | 20% | 린치, 캐시우드 | 매출 성장률, EPS 성장률, PEG |
| **Quality** | 20% | 멍거, 피셔 | ROE, ROIC, 영업마진, 순이익률 |
| **Momentum** | 10% | 드러켄밀러 | 1개월/3개월 가격 모멘텀 |
| **Safety** | 10% | 파브라이, 버핏 | 부채비율, 유동비율, 이자보상배율 |
| **Sentiment** | 8% | 뉴스 분석 | 뉴스 헤드라인 센티먼트 |
| **Insider** | 7% | 내부자 거래 | 내부자 매수/매도 비율 |

#### 투자자 스타일별 점수

| 투자자 | 가중치 | 핵심 기준 |
|--------|--------|----------|
| Warren Buffett | 1.0 | ROE > 15%, 낮은 부채, 높은 마진, 원자재 hard cap 5점 |
| Charlie Munger | 0.95 | ROE > 20%, 품질 중시 |
| Ben Graham | 0.85 | P/E < 15, P/B < 1.5, 유동비율 > 2, 배당 + 수익 안정성 |
| Peter Lynch | 1.05 | PEG < 1, 성장 + 센티먼트, GARP 보너스 |
| Phil Fisher | 0.85 | R&D/Revenue 비율, 마진 개선 추세, 경영진 품질 |
| Cathie Wood | 0.70 | 고성장 (매출 > 25%), 혁신 |
| Stanley Druckenmiller | 0.70 | 모멘텀 + 성장 (팩터와 이중 가중치 방지) |
| Michael Burry | 0.75 | 극단적 저평가, P/E < 8 |

### 전략별 점수 계산

**Fundamental**: `최종 = (앙상블 × 60%) + (팩터 × 40%) + 사이즈 보너스 + Lynch GARP 보너스`

**Momentum**: `단기(20일) 최대 4점 + 장기(60일) 최대 4점 + RSI 보정 최대 2점 ± 추세 지속성 0.5점`

**Hybrid (기본, 권장)**:
```
하이브리드 = (펀더멘털 × F%) + (모멘텀 × M%)
  Buffett≥7 & Graham≥6: F=85%, M=15%
  Druckenmiller≥7 & 가치 약세: F=55%, M=45%
  기본값: F=70%, M=30%
```

### 현금흐름 품질 게이트

팩터 점수가 높아도 현금흐름이 나쁘면 감점: 영업CF 마이너스 -1.5점, FCF 마이너스 -1.0점, 영업마진 <5% -0.5점.

### 투자자 합의도

`std < 1.5` 높은 합의, `std < 2.5` 보통, `std ≥ 2.5` 낮은 합의 (경고).

### 투자 철학 불일치 경고

- Buffett 높은 + 원자재/에너지 → 철학 충돌
- Lynch 높은 + 메가캡($200B+) → 10배주 불가능
- Lynch 높은 + 매출 급감(-15%) → 떨어지는 칼
- Graham 높은 + ROE 음수 → 적자 기업

### 신호 결정 기준

| 총점 | 신호 | 예상 수익률 |
|------|------|------------|
| ≥ 8 | 🟢 strong_buy | `(총점-3)/10 × 35%` |
| ≥ 5 | 🔵 buy | (범위: -30% ~ +40%) |
| ≥ 2 | ⚪ hold | |
| ≥ 0 | 🟡 weak_sell | |
| < 0 | 🔴 sell | |

---

## CLI 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--tickers` | 분석할 종목 (콤마 구분) | - |
| `--index` | 인덱스 전체 분석 (sp500, nasdaq100, kospi, kosdaq, kospi200, kosdaq150, krx) | - |
| `--top` | 분석 대상 종목 수 제한 (미지정 시 전체 종목 분석) | 전체 |
| `--strategy` | 분석 전략 (fundamental, momentum, hybrid) | hybrid |
| `--no-sort-by-cap` | 시가총액 정렬 비활성화 | true (기본 정렬됨) |
| `--workers` | 병렬 처리 워커 수 | 10 |
| `--output` | 결과 저장 파일 (JSON) | - |
| `--period` | 예측 기간 | 1Y |
| `--no-cache` | 캐시 사용 안 함 (항상 새로 조회) | false |
| `--clear-cache` | 캐시 삭제 후 종료 | - |
| `--cache-stats` | 캐시 통계 출력 | - |
| `--update-tickers` | Wikipedia/PyKRX에서 최신 티커 목록 갱신 | - |

## 지원 인덱스

| 인덱스 | 설명 | 소스 |
|--------|------|------|
| **sp500** | S&P 500 (약 500개 종목) | Wikipedia |
| **nasdaq100** | NASDAQ 100 (약 100개 종목) | Wikipedia |
| **kospi** | KOSPI 전체 (약 950개 종목) | PyKRX |
| **kosdaq** | KOSDAQ 전체 (약 1,700개 종목) | PyKRX |
| **kospi200** | KOSPI 200 (시가총액 상위 200개) | PyKRX |
| **kosdaq150** | KOSDAQ 150 (시가총액 상위 150개) | PyKRX |
| **krx** | KRX = KOSPI 200 + KOSDAQ 150 (약 350개 종목). **별도 분리 실행 금지** | PyKRX |

## 스크립트 파일

| 파일 | 용도 |
|------|------|
| `analyze_stocks.py` | **CLI 진입점** |
| `config.py` | 공유 상수 및 설정 |
| `cache.py` | 파일 기반 캐시 시스템 |
| `rate_limiter.py` | Yahoo Finance rate limiting 대응 |
| `data_fetcher.py` | 데이터 수집 (재무지표, 가격, 뉴스, 내부자거래) |
| `factor_scoring.py` | 7가지 팩터 점수 계산 |
| `investor_scoring.py` | 5명 투자자 스타일 점수 + 섹터통계 + 경고 |
| `analysis.py` | 분석 파이프라인 (단일 + 배치) |
| `reporting.py` | 결과 출력 포맷팅 |
| `ranking_algorithm.py` | 앙상블 점수 계산 알고리즘 |

## 데이터 소스

| 데이터 | 해외 출처 | 한국 출처 |
|--------|-----------|-----------|
| 재무 지표 | Yahoo Finance | DART (OpenDartReader) |
| 가격 데이터 | Yahoo Finance (배치) | PyKRX |
| 시가총액 | Yahoo Finance | KRX Open API / PyKRX |
| 내부자 거래 | Yahoo Finance | DART 주요주주 공시 |
| 뉴스 헤드라인 | Yahoo Finance | FinanceDataReader |
| 인덱스 구성종목 | Wikipedia | PyKRX |

## 주의사항

1. **Yahoo Finance 사용**: API 키 불필요, 무료 데이터 소스 사용
2. **캐시 지원**: 동일 날짜 재실행 시 캐시 활용으로 빠른 분석
3. **배치 가격 다운로드**: `yf.download()`로 500개 종목 가격을 1회 API 호출로 수집
4. **투자 책임**: 이 분석은 참고용이며 투자 결정은 본인 책임
5. **한국 종목**: DART 재무데이터 사용 시 `DART_API_KEY` 환경변수 필요. 시가총액은 `₩320조`, `₩5,000억` 형태로 표시
