# Predict factor evidence contract

`predict_factor_v1`의 7개 순위 팩터를 같은 기준으로 검증하고, `predict`가
사전 가중치를 근거 강도에 따라 수축할 수 있는 JSON을 만드는 계약이다.

## 호환성 경계

- `factor_spec_id`는 `predict_factor_v1`이어야 한다.
- 입력 팩터 값은 신호일 당시
  `predict/scripts/factor_scoring.py`의 정확한 점수 정의로 다시 계산해야 한다.
- 7개 팩터는 `value`, `growth`, `quality`, `momentum`, `safety`,
  `sentiment`, `insider`다. 모두 값이 클수록 매력적인 방향이어야 한다.
- 팩터 계산식, 결측치 처리, 데이터 공급자 또는 유니버스 정의를 바꾸면 기존
  검증 JSON을 재사용하지 않는다. 의미가 달라지면 `factor_spec_id`도 올린다.
- 기존 `multifactor_walk_forward.py`의 가치·품질·성장·모멘텀·저변동성 패널은
  팩터 정의와 개수가 다르므로 이 계약의 입력으로 사용할 수 없다.

## CSV 입력

한 행은 한 체결일의 한 종목이다. 다음 열을 모두 포함한다.

| 열 | 계약 |
|---|---|
| `signal_date` | 팩터 산출 기준일. 체결일보다 앞선 실제 거래일 |
| `execution_date` | 신호 다음 실제 체결일 |
| `label_end_date` | 다음 리밸런싱 체결일. `execution_date`보다 뒤 |
| `ticker` | 해당 시점 유니버스 종목 코드 |
| `forward_return` | `execution_date` 체결가부터 `label_end_date` 체결가까지 수익률 |
| 7개 팩터 열 | `signal_date`에 관측 가능했던 원점수. 결측은 허용하지만 coverage에 반영 |

`execution_date,ticker`는 유일해야 하고, 각 체결일에는 최소 5종목이 있어야 한다.
등급의 12·36 OOS 기간을 1·3년으로 해석하므로 체결 간격은 20~45일의 월간 주기를
강제한다. 각 기간의 `label_end_date`는 다음 `execution_date`와 같아야 한다.
현재 구성종목을 과거 전 기간에 소급한 패널, 정정 전후 빈티지를 구분하지 않은
사후 재무값, 신호일 이후 기사·공시·거래는 point-in-time 근거가 아니다.

## 공통 검증 지표

각 팩터에 동일하게 다음을 계산한다.

- 체결일별 Spearman rank IC와 moving-block bootstrap 95% 구간
- IC 양수 비율과 팩터 데이터 coverage
- 상위 20% 동일가중의 비용 차감 누적수익, 유니버스 대비 수익, 상·하위 spread
- 직전 포트폴리오 대비 turnover
- 기존 사전 가중치 composite에서 해당 팩터만 제거한 ablation 수익 차이

비용은 `--round-trip-cost-bps`로 반드시 명시한다. 첫 매수는 round-trip 비용의
절반, 완전 교체는 한 번의 round-trip 비용이 되도록 `0.5 * L1` turnover에 곱한다.

## 근거 등급과 가중치

`predict`는 JSON에 적힌 claimed 등급을 신뢰하지 않고 원시 metrics에서 재계산한다.

| 등급 | 최소 조건 | prior multiplier |
|---|---|---:|
| `robust` | 36 OOS 기간, coverage 90%, IC 95% 하한 양수, IC 양수율 55%, 비용 차감 초과수익·ablation 양수, 독립 홀드아웃 | 1.00 |
| `promising` | 12 OOS 기간, coverage 90%, 평균 IC·IC 양수율 50%·비용 차감 초과수익·ablation 양수, 독립 홀드아웃 | 0.85 |
| `preliminary` | 12 OOS 기간, coverage 80%, 평균 IC와 비용 차감 초과수익 양수 | 0.65 |
| `weak` | 위 조건 미달 | 0.35 |
| `contradicted` | 12 OOS 기간에서 평균 IC·초과수익·ablation이 모두 0 이하 | 0.00 |
| `unvalidated` | 팩터 근거 자체가 없음 | 0.50 |

prior에 multiplier를 곱한 뒤 기존 팩터 블록의 총 가중치로 다시 정규화한다.
따라서 multiplier는 prior보다 신뢰도를 올리지 않지만, 신뢰도가 낮은 팩터에서
빠진 상대 비중은 더 강한 팩터로 이동할 수 있다. 모든 팩터가 `contradicted`이면
순위 생성을 중단하지 않고 prior 상대 비중으로 폴백하되 `fallback_reason`을 남긴다.

## 실행

사전 가중치 JSON은 7개 키를 직접 담거나 `factor_weights` 객체로 담는다.

```bash
uv run python .agents/skills/backtesting/scripts/factor_evidence.py \
  --factor-panel artifacts/krx_predict_factor_panel.csv \
  --prior-weights-json artifacts/predict_prior_weights.json \
  --market-scope krx --applicable-index krx \
  --universe-id historical_krx_membership_v1 \
  --round-trip-cost-bps 30 --point-in-time --independent-holdout \
  --output artifacts/krx_predict_factor_evidence.json
```

`--independent-holdout`은 기간·팩터·임계값을 결과 확인 전에 동결했을 때만 쓴다.
산출물의 `validation_end`는 마지막 `label_end_date`이므로 `predict` 분석일보다
반드시 앞서야 한다. 시장 범위와 인덱스도 정확히 일치해야 한다.

## 뉴스의 추가 게이트

`sentiment`도 이 공통 성과 검증을 받지만 이것만으로 순위 반영이 허용되지는 않는다.
뉴스는 기사 관련성·이벤트·방향 분류 자체의 사람 라벨 정확도 검증이 별도로 필요하다.
따라서 공통 factor evidence와 `predict/references/news_validation_contract.md`의
semantic·predictive·portfolio 게이트를 모두 통과한 경우에만 뉴스 점수가 중립값을
대체한다.

## 해석 제한

이 JSON은 7개 기본 팩터 블록의 상대 비중 근거다. 투자자 persona 앙상블,
Lynch GARP 보너스, 현금흐름 패널티, enhanced momentum과 hybrid 조건부 결합까지
전체 모델이 검증되었다는 뜻은 아니다. 서로 다른 시장·유니버스·점수 버전에
검증 결과를 전이하지 않는다.
