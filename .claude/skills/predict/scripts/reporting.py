"""Display research priority, observable coverage and dated prices."""
from research_ranking import build_research_shortlist


def print_results(results, top_n=None, strategy="hybrid"):
    shown = results[:top_n] if top_n is not None else results
    print(f"\n조사 우선순위 · {strategy} · {len(results)}개 중 {len(shown)}개 표시")
    print("순위  종목                 조사점수  가격 기준일   가격 관측수  재무 블록  관측 비중")
    for row in shown:
        evidence = row["research_evidence"]
        blocks = sum(bool(fields) for fields in evidence["fundamental_fields"].values())
        financials = "해당 없음" if strategy == "momentum" else f"{blocks}/4"
        print(f"{row['rank']:4}  {row['ticker']:<19}  {row['total_score']:7.2f}  {evidence['price_end']}  "
              f"{evidence['price_observations']:5}       {financials:<8}  {row['observed_weight_share']:.0%}")
    slate = build_research_shortlist(results)
    print(f"독립 분석 후보 {len(slate['candidates'])}개 · 전체 순위 상위 및 업종·팩터별 선두")
