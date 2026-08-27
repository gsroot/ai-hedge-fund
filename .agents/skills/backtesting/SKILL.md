---
name: backtesting
description: |
  가격·재무 데이터의 기준 시점을 지키는 포트폴리오 백테스트. 실제 거래일,
  전일 신호/익일 시가 체결, 거래비용, Sharpe/Sortino, MDD, 실현 승률을 계산한다.
  사용 시점: "백테스트 해줘", "전략 시뮬레이션", "과거 데이터로 검증",
  "AAPL 모멘텀 테스트", "삼성전자 백테스트", "포트폴리오 성과 검증".
---

# Backtesting

이 스킬은 전략의 과거 성과를 재현한다. 높은 수익률을 만드는 도구가 아니라,
미래정보 누수·거래비용·유니버스 편향을 드러내는 검증 도구로 사용한다.

## 필수 정확성 규칙

1. 신호에는 체결일 전 거래일 종가까지의 데이터만 사용한다.
2. 거래는 다음 실제 거래일 시가에 체결한다.
3. 미국 Yahoo 재무·뉴스·내부자 데이터는 현재 스냅샷이므로 과거
   `predictor`/`hybrid` 백테스트에 사용하지 않는다. 단일 종목 엔진은 현재
   `momentum`만 허용한다. 미국 펀더멘털 워크포워드는 SEC Company Facts를
   `filed <= signal_date`로 거르는 아래 전용 경로만 사용한다.
4. 한국 `predictor`/`hybrid`는 기준일 당시 공시 가능했던 DART 연간자료와
   PyKRX 데이터를 사용한다. 다만 이후 정정공시 버전을 분리하지 못하므로 결과의
   `validity.fundamental_data` 경고를 유지한다.
5. `--index`는 현재 구성종목이라 생존편향이 있다. 기본 차단하며, 탐색 목적으로만
   `--acknowledge-survivorship-bias`를 명시한다. 검증 결과에는 당시 유니버스를
   `--tickers`로 전달한다.
6. 수수료·슬리피지·매도세를 0으로 암묵 가정하지 않는다. 시장/브로커에 맞게
   CLI 값을 조정한다.
7. 벤치마크 차이는 단순 초과수익이며 회귀 알파가 아니다.

## 실행

```bash
# 미국 종목: point-in-time 가격만 쓰는 기본 모멘텀
uv run python .agents/skills/backtesting/scripts/backtest.py \
  --tickers AAPL,MSFT,GOOGL \
  --start 2024-01-01 --end 2024-12-31 \
  --strategy momentum --rebalance monthly \
  --commission-bps 5 --slippage-bps 5 --risk-free-rate 0.04

# 한국 종목: 공시 시점을 보수적으로 지키는 hybrid
uv run python .agents/skills/backtesting/scripts/backtest.py \
  --tickers 005930,000660 \
  --start 2024-01-01 --end 2024-12-31 \
  --strategy hybrid --rebalance monthly \
  --commission-bps 5 --slippage-bps 5 --sell-tax-bps 18

# 현재 S&P 500 구성종목을 쓰는 탐색용 실행(검증용으로 해석 금지)
uv run python .agents/skills/backtesting/scripts/backtest.py \
  --index sp500 --top 50 --acknowledge-survivorship-bias \
  --start 2024-01-01 --end 2024-12-31 --strategy momentum

# portfolio-report가 만든 고정 목표비중을 구성일 이후 구간에서 검증
uv run python .agents/skills/backtesting/scripts/backtest.py \
  --weights-json portfolios/portfolio.json \
  --start 2024-02-01 --end 2025-01-31 --rebalance monthly
```

## 가격 전용 워크포워드 OOS 검증

미국 재무 데이터의 과거 빈티지가 없을 때는 펀더멘털을 현재 값으로 대체하지
않는다. 대신 역사적 Dow 구성 변경과 해당 신호일까지의 실제 조정 OHLC만 쓰는
가격 기반 검증을 실행할 수 있다. 각 OOS 연도의 파라미터는 직전 3년 학습
Sharpe만으로 선택하며, 신호는 전 거래일 종가·체결은 다음 시가다.

```bash
uv run python .agents/skills/backtesting/scripts/walk_forward.py \
  --start-oos 2018-01-01 --end-oos 2025-12-31 \
  --train-years 3 --commission-bps 5 --slippage-bps 5 \
  --sensitivity-total-cost-bps 0,25 --fixed-grid-diagnostics \
  --output-dir artifacts/walk_forward/dow_momentum_2018_2025 \
  --refresh-data
```

이 모드는 가격·구성종목 시점만 검증한다. Yahoo의 사후 기업행동 조정과 공급자
정정 이력은 빈티지별로 보존되지 않으며, 재무·뉴스·내부자 팩터를 검증한 것으로
해석하지 않는다. 데이터 누락 종목과 월별 유니버스 커버리지는 결과에 기록한다.

## SEC point-in-time 다중팩터 검증

미국 재무 팩터는 SEC EDGAR Company Facts의 실제 제출일을 기준으로 복원한다.
가치·품질·성장·모멘텀·저변동성 조합을 직전 3년 학습 성과로 선택하고 다음 1년을
OOS로 평가한다. DIA뿐 아니라 당시 Dow 구성종목 동일가중도 기준선으로 쓴다.
각 리밸런싱의 신호일까지 DIA 가격만 사용해 과열·공포·전망 점수를 다시 계산하고,
`portfolio-report/scripts/market_regime.py`와 동일한 0~50% 동적 현금 규칙을 적용한다.
고정 100% 주식이나 단순 200일선 이탈 시 50% 현금 규칙으로 대체하지 않는다.

```bash
uv run python .agents/skills/backtesting/scripts/multifactor_walk_forward.py \
  --start-oos 2018-01-01 --end-oos 2025-12-31 \
  --train-years 3 --commission-bps 5 --slippage-bps 5 \
  --bootstrap-samples 2000 \
  --output-dir artifacts/walk_forward/dow_multifactor_2018_2025 \
  --refresh-prices
```

상장폐지 후 Yahoo가 과거 가격을 제거한 종목은 검증 가능한 별도 CSV로 보완한다.
CSV는 `Date,Open,Close,Adj Close`를 포함해야 하며 기존 Yahoo 관측값을 덮지 않고
누락값만 채운다. 파일 경로·SHA-256·기간은 결과에 기록된다.

```bash
uv run python .agents/skills/backtesting/scripts/multifactor_walk_forward.py \
  ... \
  --supplemental-price WBA=artifacts/walk_forward/supplemental_sources/WBA_stock_data.csv
```

선형 예측 모델은 외부 OOS 안에서 다시 학습/검증을 나누는 nested 경로로 비교한다.
알파, 보유 종목 수, 가중 방식, 월/분기 리밸런싱은 내부 검증에서만 선택한다.

```bash
uv run python .agents/skills/backtesting/scripts/ridge_walk_forward.py \
  --start-oos 2018-01-01 --end-oos 2025-12-31 --train-years 3 \
  --factor-panel artifacts/walk_forward/dow_multifactor_2018_2025/point_in_time_factor_panel.csv \
  --adjusted-price-cache artifacts/walk_forward/dow_multifactor_2018_2025/adjusted_ohlc.csv \
  --output-dir artifacts/walk_forward/dow_multifactor_2018_2025
```

`--independent-holdout`은 모델·그리드·기간을 결과 확인 전에 동결한 경우에만 쓴다.
백테스트는 포트폴리오 구성을 승인하거나 차단하지 않는다. 검증 근거를 `weak`,
`preliminary`, `promising`, `robust`로 분류해 포트폴리오와 함께 보여준다.
`multifactor_latest_candidate.json`은 근거 등급과 무관하게 선택 모델의 전체 목표비중을
`weights`와 `cash_weight`에 기록한다. 두 합은 1이고 시장 국면도 함께 기록한다.

`promising`은 독립 OOS가 126 거래일 이상이고 아래 조건을 모두 만족한 경우다.

- 역사적 월별 유니버스 가격 커버리지 100%
- 비용 반영 구간 총수익률이 DIA와 역사적 동일가중을 모두 상회
- 최대낙폭이 DIA와 역사적 동일가중보다 모두 나쁘지 않음
- 두 기준선 대비 paired block bootstrap 우위 확률이 각각 80% 이상
- 결과 확인 전에 모델·그리드·기간을 동결한 독립 홀드아웃 선언

`robust`는 위 조건에 더해 최소 3년 OOS와 두 기준선 대비 CAGR 차이의 paired
bootstrap 95% 하한 양수를 요구한다. `preliminary`는 완전한 유니버스에서 두
기준선의 총수익률을 앞선 상태다. 이 등급은 성과 근거의 강도이지 자금 비중 제한이나
매수 승인 플래그가 아니다.

## Predict 7개 팩터 통합 검증

`predict_factor_v1`의 가치·성장·품질·모멘텀·안전성·뉴스 심리·내부자
팩터를 같은 시점·수익률·비용·ablation 기준으로 검증한다. 기존 Dow
multifactor 패널은 팩터 정의가 다르므로 이 경로에 재사용하지 않는다.

```bash
uv run python .agents/skills/backtesting/scripts/factor_evidence.py \
  --factor-panel artifacts/krx_predict_factor_panel.csv \
  --prior-weights-json artifacts/predict_prior_weights.json \
  --market-scope krx --applicable-index krx \
  --universe-id historical_krx_membership_v1 \
  --round-trip-cost-bps 30 --point-in-time --independent-holdout \
  --output artifacts/krx_predict_factor_evidence.json
```

입력 패널·등급·가중치 수축 계약은
[references/factor_evidence_contract.md](references/factor_evidence_contract.md)를 반드시 적용한다.
뉴스 `sentiment`는 이 공통 성과 검증 외에 분류 정확도 게이트도 통과해야 한다.
산출물은 7개 기본 팩터의 상대 비중만 다루며, 투자자 persona와 hybrid 전체
모델을 검증한 것으로 표현하지 않는다.

## 주요 옵션

| 옵션 | 설명 | 기본값 |
|---|---|---|
| `--tickers` | 콤마 구분 고정 유니버스 | - |
| `--weights-json` | 구성일과 0~1 목표비중을 담은 portfolio JSON | - |
| `--index` | 현재 인덱스/사전 그룹. 승인 플래그 필수 | - |
| `--acknowledge-survivorship-bias` | 현재 구성종목 사용의 편향 승인 | false |
| `--start`, `--end` | 백테스트 기간 | 필수 |
| `--strategy` | `momentum`, `predictor`, `hybrid` | momentum |
| `--rebalance` | `daily`, `weekly`, `monthly` | weekly |
| `--commission-bps` | 편도 수수료 | 5 |
| `--slippage-bps` | 편도 슬리피지 | 5 |
| `--sell-tax-bps` | 매도 거래세 | 0 |
| `--risk-free-rate` | 연 무위험수익률, 소수 | 0 |
| `--benchmark` | 비교 벤치마크 | SPY |
| `--output` | JSON 저장 경로 | - |

## 결과 해석

- `total_return`, `annualized_return`: 비용 반영 성과
- `sharpe_ratio`, `sortino_ratio`: 사용자가 지정한 무위험수익률 반영
- `max_drawdown`: 고점 대비 최대 손실
- `win_rate`: 매수 횟수나 confidence가 아니라 실제 청산 거래의 실현손익 기준
- `transaction_costs`: 수수료·세금·슬리피지의 누적 비용
- `benchmark_excess_return`: 포트폴리오 총수익률 - 벤치마크 총수익률
- `validity.survivorship_bias`: 현재 인덱스 구성종목 사용 여부
- 목표비중 백테스트는 `analysis_date < start`를 강제해 포트폴리오 선정 후 성과만 측정

## 검증 체크리스트

- `trade_history[].signal_date < trade_history[].date`인지 확인한다.
- 이름별 비중, 현금, 거래비용이 의도한 설정과 맞는지 확인한다.
- `--index` 결과는 종목선정 성과의 증거로 사용하지 않는다.
- 한 기간의 최고 성과만 고르지 말고 훈련/검증/워크포워드 구간을 분리한다.
- 이미 확인한 OOS를 바탕으로 모델을 바꿨다면 그 구간을 개발 구간으로 강등하고,
  새 기간만 독립 홀드아웃으로 표시한다.
- `evidence_assessment`를 포트폴리오 생성 승인이나 자금 비중 제한으로 해석하지 않는다.
- 근거 등급이 낮아도 포트폴리오는 생성하되, 성과 불확실성과 실패한 검증 항목을
  결과에서 숨기지 않는다. 서로 다른 methodology는 별도로 검증한다.
- 분할·상장폐지·배당·세금·유동성·시장충격 등 미모델링 항목을 함께 보고한다.

## 테스트

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v
```

스크립트: [scripts/backtest.py](scripts/backtest.py),
[scripts/walk_forward.py](scripts/walk_forward.py),
[scripts/multifactor_walk_forward.py](scripts/multifactor_walk_forward.py),
[scripts/ridge_walk_forward.py](scripts/ridge_walk_forward.py),
[scripts/factor_evidence.py](scripts/factor_evidence.py)
