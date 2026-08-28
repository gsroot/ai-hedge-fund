---
name: portfolio-report
description: |
  predict 상대 순위와 독립 investor-analysis 결과를 결합해 제약식 포트폴리오와
  시장 국면에 따른 동적 현금비중, 선택적 엑셀 리포트를 만든다.
  사용 시점: "투자 리포트", "포트폴리오 구성",
  "상위 종목 심층 분석", "버핏·린치 관점 포트폴리오", "엑셀 투자 리포트".
---

# Portfolio Report

`predict → investor-analysis → portfolio-report` 순서로 사용한다. predict의
투자자 점수를 별도의 심층 분석인 것처럼 복제하지 않는다.

이 경로는 설명 가능한 연구 후보를 만드는 휴리스틱이며, SEC 다중팩터
워크포워드와 동일한 methodology가 아니다. 다른 전략의 좋은 백테스트를 이
리포트의 검증 근거로 전용하지 않는다. 수익률 최대화 또는 실전 배포를 주장하려면
이 정확한 `predict + investor-analysis + risk adjustment + caps` 파이프라인 자체를
point-in-time으로 다시 실행한 독립 OOS 결과가 필요하다.

## 입력

- 상위 종목 수: 기본 30
- 투자자: 기본 `buffett,lynch,fisher`; `all`은 12명
- 엑셀: 기본 생성
- `predict JSON`: 필수
- 종목별 독립 `investor-analysis JSON`: 필수
- 동일 기준일의 변동성·상관·시장 국면 `risk JSON`: 필수

지원 식별자:

`buffett,munger,damodaran,lynch,graham,fisher,druckenmiller,pabrai,burry,ackman,jhunjhunwala,wood`

## 워크플로우

1. `predict`로 후보 유니버스의 상대 순위를 JSON으로 저장한다.
2. 상위 N개 각각을 선택한 투자자 관점에서 독립 분석한다.
3. 분석 결과를 다음 구조로 저장한다.

```json
{
  "analysis_date": "YYYY-MM-DD",
  "analyses": {
    "AAPL": {
      "buffett": {"signal": "bullish", "confidence": 78, "reasoning": "...", "data_quality": "complete"},
      "lynch": {"signal": "neutral", "confidence": 61, "reasoning": "...", "data_quality": "partial"}
    }
  }
}
```

4. predict 후보와 해당 시장 벤치마크의 기준일까지 가격으로 risk snapshot을 만든다.
   `sp500=SPY`, `nasdaq100=QQQ`, `kospi/kospi200/krx=^KS11`,
   `kosdaq/kosdaq150=^KQ11`을 기본 사용한다. custom 유니버스는 `--benchmark`를
   명시한다.

```bash
uv run python .agents/skills/portfolio-report/scripts/build_risk_snapshot.py \
  --predict-json results.json --top 30 --output risk.json
```

5. 리포트 생성기를 실행한다. 요청 투자자 중 하나라도 종목별 분석이 누락되면
   생성기는 실패한다. 임의 중립값이나 predict 점수로 보충하지 않는다.

```bash
uv run python .agents/skills/portfolio-report/scripts/generate_portfolio_report.py \
  --predict-json results.json \
  --investor-json investor_results.json \
  --risk-json risk.json \
  --top 30 \
  --investors buffett,lynch,fisher \
  --xlsx yes \
  --portfolio-json portfolios/portfolio.json \
  --output-dir portfolios
```

## 포트폴리오 규칙

1. 선택 투자자의 과반이 `bullish`인 종목만 후보에 남긴다.
2. 원시 비중 점수는 `predict total_score × 독립 분석 confidence × bullish 합의율`을
   연환산 변동성과 후보 간 평균 양의 상관으로 조정한다.
3. 단일 종목 최대 15%, 단일 섹터 최대 35%, 최소 종목 비중 2%다.
4. 시장 현금 목표는 15%를 기준으로 과열 점수와 부정 전망이 높을수록 늘리고,
   공포 점수와 긍정 전망이 높을수록 줄인다. 결과는 0~50% 범위다.
   - 과열: 200일선 이격, RSI, 6개월 상승률
   - 공포: 252일 고점 낙폭, RSI 과매도, 20일 실현변동성
   - 전망: 가격/200일선, 50/200일선, 6개월 모멘텀
5. 공포와 부정 전망이 동시에 발생하면 두 효과를 상쇄한다. 공포가 크다는 이유만으로
   하락 추세를 무시하거나, 추세가 나쁘다는 이유만으로 공포 구간의 주식을 전부
   현금화하지 않는다.
6. 종목·섹터 상한 때문에 목표 주식비중을 채우지 못하면 남은 비중도 현금이다.
   실제 현금은 시장 목표보다 많을 수 있지만 적을 수는 없다. 제약을 깨면서
   다시 100%로 정규화하지 않는다.
7. 과거 분석일에는 현재 Yahoo 섹터를 끼워 넣지 않는다. predict JSON에 당시 섹터가
   없으면 `Unknown`으로 두며 Unknown 묶음에도 섹터 상한을 적용한다.
8. `score_implied_return_pct`는 예상수익률이 아니다. 리포트에서는 “점수 환산값”과
   “점수 환산 기여값”으로만 표시한다.

## 12개 투자자 가중치

가중치는 합의 신뢰도에만 사용한다. 역사적 성과를 정밀 추정한 값으로 해석하지 않는다.

| 투자자 | 가중치 | 투자자 | 가중치 |
|---|---:|---|---:|
| Buffett | 1.00 | Munger | 0.95 |
| Damodaran | 0.90 | Lynch | 0.85 |
| Graham | 0.85 | Fisher | 0.82 |
| Druckenmiller | 0.80 | Pabrai | 0.78 |
| Burry | 0.75 | Ackman | 0.75 |
| Jhunjhunwala | 0.72 | Wood | 0.70 |

## 결과 확인

- 종목별 비중 `<= 15%`
- 섹터 합계 `<= 35%`
- 주식 비중 + 현금 비중 `= 100%`
- 실제 현금 비중 `>= market_regime.target_cash_weight`
- `market_regime.as_of_date <= analysis_date`
- 모든 투자자 분석의 `analysis_source = independent_investor_analysis`
- 과거 결과라면 섹터·재무 데이터의 기준 시점 확인
- 실제 자금 투입 전 `backtesting`으로 고정 유니버스와 비용을 반영해 검증
- `backtesting.evidence_assessment`는 근거 설명에 사용하되 포트폴리오 생성을 차단하거나
  목표비중을 자동 축소하지 않음
- portfolio JSON의 `research_provenance`에
  `predict -> independent_investor_analysis -> risk_snapshot -> portfolio_report` 순서,
  factor evidence mode, provider 상태, news ranking policy, 검증 범위와 미검증 한계가
  포함됨. 기존 provenance 없는 snapshot은 새 계약 통과 결과로 소급 표기하지 않음

구성일 이후 데이터가 존재할 때는 생성된 목표비중 자체를 검증한다.

```bash
uv run python .agents/skills/backtesting/scripts/backtest.py \
  --weights-json portfolios/portfolio.json \
  --start YYYY-MM-DD --end YYYY-MM-DD --rebalance monthly
```

`--start`는 portfolio JSON의 `analysis_date`보다 반드시 늦어야 한다.

스크립트: [scripts/build_risk_snapshot.py](scripts/build_risk_snapshot.py),
[scripts/market_regime.py](scripts/market_regime.py),
[scripts/generate_portfolio_report.py](scripts/generate_portfolio_report.py)
