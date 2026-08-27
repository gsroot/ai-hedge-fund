# 뉴스 순위 반영 검증 계약

뉴스를 순위에 반영하려면 `news_sentiment_enrichment.py apply`에 아래 구조의
`--validation-json`을 전달한다. 모든 조건을 동시에 만족하지 않으면 자동으로
`risk_and_explanation_only`를 사용한다.

이 파일만으로는 충분하지 않다. 기본 predict JSON이 `predict_factor_v1` 공통
factor evidence를 적용한 `evidence_shrunk` 모드여야 하고, 같은 원시 metrics로
다시 계산한 `sentiment` 등급이 `promising` 또는 `robust`여야 한다.

```json
{
  "schema_version": 2,
  "classifier_policy_id": "news_event_v2",
  "validation_decision": {
    "accuracy_validated": true,
    "evidence_grade": "strong",
    "gates": {
      "semantic": {
        "gold_sample_size": 90,
        "macro_f1": 0.70,
        "class_recalls": {
          "positive": 0.60,
          "negative": 0.60,
          "neutral": 0.60
        }
      },
      "predictive": {
        "directional_event_count": 50,
        "wilson_lower_bound": 0.50,
        "positive_mean_abnormal_return": 0.001,
        "negative_mean_abnormal_return": -0.001,
        "long_short_abnormal_return": 0.002,
        "beats_neutral_baseline_5d": true,
        "beats_neutral_baseline_20d": true
      },
      "portfolio": {
        "independent_holdout_windows": 2,
        "net_excess_return_delta": 0.001,
        "sharpe_delta": 0.01
      }
    }
  }
}
```

## 산출 규칙

- 사람 정답 라벨은 기사 결과와 미래 수익률을 보지 않은 독립 평가자가 만든다.
- 의미 평가는 최소 90건과 각 positive, negative, neutral recall 0.60 이상을 요구한다.
- 방향성 평가는 동결한 미래 홀드아웃, 다음 실제 거래일 시가 진입, KRX 벤치마크
  차감 수익률을 사용한다.
- 포트폴리오 평가는 뉴스 미사용 기준 포트폴리오와 동일한 유니버스, 리밸런싱,
  제약, 거래비용으로 비교하고 서로 겹치지 않는 홀드아웃 창을 최소 2개 사용한다.
- 검증 파일의 `classifier_policy_id`가 분류 작업의 값과 다르면 재검증한다.
- 공통 factor evidence의 시장·인덱스·시점·종료일 계약은 기본 `predict`
  실행 단계에서 검사한다. 이 파일은 분류 정확도와 뉴스 추가 성과만 보완한다.
- 통과 여부를 먼저 정한 뒤 결과를 보며 임계값을 바꾸지 않는다.
