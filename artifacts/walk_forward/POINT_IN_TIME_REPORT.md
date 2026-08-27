# Point-in-time 워크포워드 성과 근거 보고서

생성 기준일: 2026-08-26 (Asia/Seoul)

## 결론

이 보고서는 포트폴리오를 승인하거나 차단하는 게이트가 아니라 구성 결과에 붙는
성과 근거다. 최신 SEC 다중팩터 포트폴리오는 전체 투자자산을 대상으로 V, CRM,
TRV, DIS, MSFT, IBM, AMZN, AMGN을 각각 12.5%로 구성하며 현금 목표비중은 0%다.

근거 등급은 `promising`이다. 2018~2025 개발 구간에서는 다중팩터와 Ridge가 모두
DIA 및 동일가중 Dow보다 낮았으나, 모델 구조를 동결한 뒤 확인한
2026-01-01~2026-08-25 독립 구간에서 다중팩터는 두 기준선보다 높은 총수익률과
더 작은 최대낙폭을 기록했다. 162 거래일의 paired bootstrap 우위 확률은 DIA
92.55%, 동일가중 96.85%다. 관측기간이 1년 미만이고 95% 하한이 음수이므로
`robust` 근거에는 도달하지 않았다. 이는 포트폴리오 비중을 자동 축소하는 조건이
아니며 성과 불확실성을 함께 보여주는 정보다.

## 데이터 및 시점 통제

- 유니버스: 당시 Dow 30 구성종목과 구성 변경 효력일
- 재무: SEC EDGAR Company Facts, `filed <= signal_date`인 사실만 사용
- 가격: Yahoo Finance 실제 OHLC. 신호는 전 거래일 종가까지, 체결은 다음 거래일 시가
- 기업행동: Yahoo 사후 조정 가격을 사용하므로 공급자 빈티지 아카이브는 아님
- 비용: 편도 수수료 5bp + 슬리피지 5bp
- 제약: 단일 종목 최대 15%, 현금 허용
- 검증: 3년 rolling train / 다음 1년 non-overlapping OOS. Ridge는 train 내부의
  마지막 1년을 추가 검증 구간으로 사용
- 비교: DIA와 당시 구성종목 월별 동일가중 포트폴리오
- 보조 가격: Yahoo가 상장폐지 후 WBA 과거 가격도 반환하지 않아 Zenodo CC0
  데이터셋(DOI `10.5281/zenodo.12566460`, 원본 MD5
  `62f1c9e523552c13023e04c283d7fc26`)으로 누락값만 보완한다. Yahoo 관측값이
  존재하면 Yahoo 값을 우선하며, 혼합 공급자라는 한계는 결과에 기록한다.

## 2018~2025 개발 워크포워드

| 모델 | 총수익률 | CAGR | Sharpe | MDD | 근거 해석 |
|---|---:|---:|---:|---:|---|
| 가격 모멘텀 | 72.64% | 7.08% | 0.47 | -26.78% | 기준선 하회 |
| SEC 다중팩터 | 103.01% | 9.28% | 0.58 | -30.03% | 기준선 하회 |
| Nested Ridge | 105.58% | 9.45% | 0.57 | -34.57% | 기준선 하회 |
| DIA | 125.33% | 10.72% | 0.63 | -36.70% | 기준선 |
| 역사적 Dow 동일가중 | 125.34% | 10.72% | 0.64 | -34.57% | 기준선 |

Ridge의 DIA 대비 CAGR 차이는 -1.27%p이고 paired block bootstrap의 95% 구간은
-5.15%p~+2.80%p, 우위 확률은 27.35%다. 동일가중 대비 CAGR도 -1.27%p다.
WBA를 제외했던 중간 실행에서는 Ridge가 DIA를 소폭 앞섰으나, 30/30 유니버스로
복원하자 우위가 사라졌다. 상장폐지 종목 결손에 대한 민감성을 실제로 확인한
사례이며, 해당 중간 결과는 채택하지 않는다.

## 2026 독립 전진 구간

기간은 2026-01-01~2026-08-25다. CAGR은 비교 편의를 위한 연환산 수치이며
1년 실제 수익률로 해석하면 안 된다.

| 모델 | 구간 총수익률 | 연환산 CAGR | Sharpe | MDD | 근거 등급 |
|---|---:|---:|---:|---:|---|
| SEC 다중팩터 | 30.46% | 51.22% | 2.76 | -8.34% | promising |
| Nested Ridge | 3.84% | 6.04% | 0.42 | -15.79% | weak |
| DIA | 11.92% | 19.15% | 1.37 | -9.76% | 기준선 |
| 역사적 Dow 동일가중 | 12.63% | 20.33% | 1.66 | -8.43% | 기준선 |

다중팩터는 2023~2025 학습에서 가치 40%, 품질 40%, 성장 20%, 상위 8개
동일가중으로 고정됐다. DIA 대비 paired bootstrap 우위 확률은 92.55%지만 95%
구간 하한은 -9.79%p다. 동일가중 대비 우위 확률은 96.85%, 하한은 -1.18%p다.
완전한 30/30 유니버스, 기준선 초과 총수익률, 기준선보다 나쁘지 않은 최대낙폭,
독립 홀드아웃, 126 거래일 이상, 우위 확률 80% 이상의 `promising` 조건은 모두
충족한다. 3년 관측과 95% 하한 양수 조건은 충족하지 못해 `robust` 등급은 아니다.

마지막 연구 후보는 2026-07-31 신호, 2026-08-03 체결 기준으로 V, CRM, TRV,
DIS, MSFT, IBM, AMZN, AMGN 각 12.5%다. 전체 목표비중 합계는 100%이고 현금은
0%다. 후보 상태는 `portfolio-ready`, 목표 포트폴리오 비율은 100%다.

## 성과 근거 등급

등급은 포트폴리오 생성 여부나 자금 비중을 결정하지 않는다.

- `preliminary`: 완전한 역사적 유니버스에서 비용 반영 총수익률이 DIA와 역사적
  동일가중을 모두 상회한다.
- `promising`: `preliminary` 조건에 더해 최대낙폭이 두 기준선보다 나쁘지 않고,
  사전 동결한
  독립 OOS 126 거래일 이상, 두 기준선 대비 paired bootstrap 우위 확률이 각각
  80% 이상이다.
- `robust`: `promising` 조건에 더해 최소 3년 OOS와 두 기준선 대비 CAGR 차이의
  paired bootstrap 95% 하한이 양수다.
- `weak`: 기준선 초과 성과 근거가 확인되지 않았다.

이번 등급 체계는 2026 홀드아웃 결과를 본 뒤 도입했으므로 사전등록된 통계적 확증이
아니다. 이후 새로 쌓이는 미사용 데이터는 등급 갱신에만 사용하며, 어떤 등급도 미래
최고 수익률을 보장하지 않는다.

## 산출물

- `dow_momentum_2018_2025/walk_forward_results.json`
- `dow_multifactor_2018_2025/multifactor_walk_forward_results.json`
- `dow_multifactor_2018_2025/ridge_walk_forward_results.json`
- `dow_2026_holdout/multifactor_walk_forward_results.json`
- `dow_2026_holdout/ridge_walk_forward_results.json`
- `dow_2026_holdout/multifactor_latest_candidate.json`

가격 캐시 SHA-256:

- 2018~2025 결합 가격: `36d6c4fdd192657ca52e60087eb0fac2a255d408483d4d2f364266366f34757f`
- 2026 결합 가격: `d69d4c0010d4874218880db4a54c25fcc47103e2749215f4bc0e69b4e6ec1b39`
- WBA 보조 원본: `eb8b800b62f8b161ae0b407752d9d47c50f4d08dd2549ec97212a46892fb7897`

데이터 출처:

- SEC Company Facts: https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
- Dow 구성 변경: https://www.spglobal.com/spdji/en/indices/equity/dow-jones-industrial-average/
- 가격: Yahoo Finance via yfinance
- WBA 보조 가격: https://doi.org/10.5281/zenodo.12566460
