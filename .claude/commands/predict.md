profit-predictor 스킬을 사용하여 주식 수익률 예측 분석을 실행해줘.

## 사용자 요청 파라미터

$ARGUMENTS

## 파라미터 해석 규칙

사용자가 입력한 `$ARGUMENTS`를 아래 규칙에 따라 해석하고, profit-predictor 스킬에 적절한 인자를 전달해줘.

### 1. 인덱스 지정 (`--index`)
- `sp500`, `s&p500`, `S&P 500`, `S&P500` → `--index sp500`
- `nasdaq100`, `nasdaq`, `NASDAQ 100`, `나스닥` → `--index nasdaq100`
- `kospi`, `KOSPI` → `--index kospi`
- `kosdaq`, `KOSDAQ` → `--index kosdaq`
- `kospi200`, `KOSPI 200`, `코스피200` → `--index kospi200`
- `kosdaq150`, `KOSDAQ 150`, `코스닥150` → `--index kosdaq150`
- `krx`, `KRX`, `한국`, `한국전체`, `kospi200+kosdaq150`, `KOSPI200+KOSDAQ150` → `--index krx`
- 인덱스가 명시되지 않고 종목도 없으면 기본값 `--index sp500` 사용

### 2. 종목 지정 (`--tickers`)
- 콤마로 구분된 티커 심볼: `AAPL,MSFT,NVDA` → `--tickers AAPL,MSFT,NVDA`
- 한국 종목 코드: `005930,000660` → `--tickers 005930,000660`
- `--index`와 `--tickers`가 동시에 지정되면 `--tickers` 우선

### 3. 전략 지정 (기본값: hybrid, 별도 플래그 불필요)
- 스크립트 기본값이 `hybrid`이므로 hybrid 전략 시 **`--strategy` 인자를 추가하지 말 것**
- 다른 전략을 명시적으로 요청한 경우에만 인자 추가:
  - `fundamental`, `펀더멘털` → `--strategy fundamental`
  - `momentum`, `모멘텀` → `--strategy momentum`

### 4. 상위 N개 (`--top`)
- `top 50`, `상위 50`, `50개` → `--top 50`
- **`--top`이 명시되지 않으면 전체 종목을 분석** (종목 수 제한 없음)

### 5. 시가총액 정렬 비활성화 (`--no-sort-by-cap`)
- 시가총액 내림차순 정렬은 스크립트 기본 동작이므로 활성화 플래그는 존재하지 않음
- `정렬없이`, `no-sort-by-cap` → `--no-sort-by-cap` (정렬 비활성화)

### 6. 기타 옵션
- `no-cache`, `캐시없이`, `새로` → `--no-cache`
- `output 파일명.json` → `--output 파일명.json`
- `period 6M`, `6개월` → `--period 6M`

## 실행 방식

해석된 파라미터를 profit-predictor 스킬에 전달하여 실행해줘.
인자가 비어있거나 `$ARGUMENTS`가 그대로이면 기본값(`--index sp500`)으로 전체 종목을 분석해줘 (시가총액 정렬 및 하이브리드 전략은 스크립트 기본 동작이므로 별도 CLI 플래그 불필요).

## 프롬프트 생성 예시

| 사용자 입력 | 생성할 프롬프트 |
|-------------|----------------|
| `--index krx` | profit-predictor 스킬을 사용해서 KRX(KOSPI200+KOSDAQ150) 전체 종목을 하이브리드 전략으로 1년 후 수익률 예측 분석해줘 |
| `--index sp500 --top 50` | profit-predictor 스킬을 사용해서 S&P 500 시가총액 상위 50개 종목을 하이브리드 전략으로 1년 후 수익률 예측 분석해줘 |
| `--tickers AAPL,MSFT,NVDA` | profit-predictor 스킬을 사용해서 AAPL, MSFT, NVDA 종목을 하이브리드 전략으로 1년 후 수익률 예측 분석해줘 |
| `--index nasdaq100 --strategy momentum --top 20` | profit-predictor 스킬을 사용해서 NASDAQ 100 시가총액 상위 20개 종목을 모멘텀 전략으로 1년 후 수익률 예측 분석해줘 |
| `kospi200+kosdaq150 상위 50개` | profit-predictor 스킬을 사용해서 KRX(KOSPI200+KOSDAQ150) 시가총액 상위 50개를 하이브리드 전략으로 1년 후 수익률 예측 분석해줘 |
| (빈 입력) | profit-predictor 스킬을 사용해서 S&P 500 전체 종목을 하이브리드 전략으로 1년 후 수익률 예측 분석해줘 |

위 규칙에 따라 파라미터를 해석한 뒤, profit-predictor 스킬을 즉시 실행해줘.
