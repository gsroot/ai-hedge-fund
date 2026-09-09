"""Validate the generated research portfolio against input and intermediate evidence."""
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
sys.path.insert(0, str(ROOT / '.agents/skills/portfolio-report/scripts'))
import generate_portfolio_report as pr
sys.path.insert(0, str(ROOT / '.agents/skills/predict/scripts'))
from data_fetcher import get_prices


def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))


def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


base, final, sources = load('krx_base.json'), load('krx_final.json'), load('investor_source_data.json')
assert [(r['ticker'], r['total_score']) for r in base['rankings']] == [(r['ticker'], r['total_score']) for r in final['rankings']]
assert final['factor_weight_policy']['mode'] == 'prior_only'
assert final['news_sentiment_policy']['ranking_contribution_applied'] is False
universe = load('universe_probe.json')
universe_tickers = {t for m in universe['market_data'].values() for t in m['top_tickers']}
assert {r['ticker'] for r in final['rankings']} <= universe_tickers
top = final['rankings'][:30]
investors = ['buffett', 'lynch', 'fisher']
analyses = pr.load_investor_analyses(OUT / 'investor_results.json', final['analysis_date'])
assert set(analyses) == {r['ticker'] for r in top}
assert all(set(analyses[t]) == set(investors) for t in analyses)
assert all(analyses[t][i]['analysis_source'] == 'independent_investor_analysis' for t in analyses for i in investors)
for t in analyses:
    for statement in sources['stocks'][t]['statements'].values():
        assert all(receipt[:8] <= final['analysis_date'].replace('-', '') for receipt in statement.get('receipts', []))
sectors = {t: sources['stocks'][t]['sector'] for t in analyses}
candidates, excluded_majority = pr.build_candidates(top, investors, sectors, analyses)
risk = pr.load_risk_snapshot(OUT / 'krx_risk.json', final['analysis_date'])
candidates, excluded_risk = pr.apply_risk_adjustment(candidates, risk)
included, excluded_weight, cash = pr.allocate_weights(candidates, target_cash_weight=risk['market_regime']['target_cash_weight']*100)
portfolio = load('portfolio.json')
assert portfolio['weights'] == {r['ticker']: round(r['weight']/100, 6) for r in included}
assert abs(portfolio['cash_weight'] - cash/100) < 1e-6
assert abs(sum(portfolio['weights'].values()) + portfolio['cash_weight'] - 1) < 2e-6
assert all(0.02-1e-6 <= w <= 0.15+1e-6 for w in portfolio['weights'].values())
sector_weights = defaultdict(float)
for ticker, weight in portfolio['weights'].items():
    sector_weights[sectors[ticker]] += weight
    assert sum(analyses[ticker][i]['signal'] == 'bullish' for i in investors) >= 2
    assert all(analyses[ticker][i]['data_quality'] != 'insufficient' for i in investors)
assert all(w <= 0.35+2e-6 for w in sector_weights.values())
assert portfolio['cash_weight'] + 1e-6 >= risk['market_regime']['target_cash_weight']
raw_prices = {}
price_ranges = {}
for ticker in list(analyses) + [risk['market_regime']['benchmark']]:
    rows = get_prices(ticker, risk['lookback_start'], final['analysis_date'])
    raw_prices[ticker] = rows
    prices = pd.Series({pd.Timestamp(r.get('date') or r.get('time')): float(r['close']) for r in rows if (r.get('date') or r.get('time')) and r.get('close') is not None}, dtype=float).sort_index()
    assert not prices.empty
    assert prices.index.max().date().isoformat() <= final['analysis_date']
    assert (prices > 0).all()
    price_ranges[ticker] = {'first': prices.index.min().date().isoformat(), 'last': prices.index.max().date().isoformat(), 'observations': len(prices)}
    if ticker in risk['annualized_volatility']:
        vol = prices.pct_change(fill_method=None).std(ddof=1)*math.sqrt(252)
        assert abs(vol-risk['annualized_volatility'][ticker]) < 1e-10
    for peer, corr in risk['correlation'].get(ticker, {}).items():
        assert math.isfinite(corr) and -1.000001 <= corr <= 1.000001
        assert abs(corr-risk['correlation'][peer][ticker]) < 1e-12
price_frame = pd.DataFrame({t: pd.Series({pd.Timestamp(r.get('date') or r.get('time')):float(r['close']) for r in raw_prices[t]}, dtype=float) for t in analyses}).sort_index()
recomputed_correlations = price_frame.pct_change(fill_method=None).corr(min_periods=risk['min_observations'])
for t, peers in risk['correlation'].items():
    for peer, value in peers.items():
        assert abs(recomputed_correlations.loc[t, peer]-value) < 1e-12
assert risk['market_regime']['as_of_date'] <= final['analysis_date']
dump('risk_price_inputs.json', {'analysis_date':final['analysis_date'], 'source':'FDR for Korean equities; Yahoo Finance for KOSPI benchmark', 'prices':raw_prices, 'ranges':price_ranges})
excluded = excluded_majority + excluded_risk + excluded_weight
all_map = {r['ticker']: r for r in candidates + excluded}
all_map.update({r['ticker']:r for r in included})
enriched = [all_map[r['ticker']] for r in top]
details = {'analysis_date':final['analysis_date'], 'included':included, 'excluded':excluded, 'top_stocks':enriched,
           'cash_weight':cash, 'market_regime':risk['market_regime'], 'sector_weights':dict(sector_weights), 'price_ranges':price_ranges}
dump('report_details.json', details)
portfolio['research_provenance']['universe'] = {'kind':'current_market_cap_proxy_not_official_index_membership','as_of':'2026-09-08','kospi':200,'kosdaq':150,'total':350}
portfolio['research_provenance']['data_quality'] = 'partial'
portfolio['research_provenance']['price_ranges'] = price_ranges
portfolio['research_provenance']['benchmark_as_of'] = risk['market_regime']['as_of_date']
portfolio['research_provenance']['limitations'].extend([
    'KRX index membership failed; the existing fallback selects market cap top 200 KOSPI and top 150 KOSDAQ, including some preferred shares.',
    'KRX market cap uses 2026-09-08; current valuation uses a dated Naver snapshot, annual factors mainly use 2025 DART filings.',
    'Predict annual metrics omit some cash-flow and R&D fields; independent analysis separately considers complete DART annual and half-year statements where available.',
    'Independent analyst confidence is heuristic, not a calibrated probability of profit.',
    'API/news missing evidence and current metadata do not establish historical or out-of-sample performance.',
])
portfolio['research_provenance']['limitations'] = list(dict.fromkeys(portfolio['research_provenance']['limitations']))
dump('portfolio.json', portfolio)
validation = {'status':'passed_local_artifact_checks','portfolio_quality_validated':False,'universe_count':350,'ranked_count':len(final['rankings']),
              'independent_opinions':sum(len(v) for v in analyses.values()),'included_count':len(included),
              'weights_total':sum(portfolio['weights'].values())+portfolio['cash_weight'],'sector_weights':dict(sector_weights),
              'cash_weight':portfolio['cash_weight'],'market_cash_target':risk['market_regime']['target_cash_weight'],
              'price_dates':price_ranges,'checks':['input universe','news preserves rank and score','90 independent opinions','filing and price as-of cutoffs','raw price volatility recomputation','raw price correlation recomputation','correlation symmetry and bounds','majority and insufficient-data exclusions','single name cap','sector cap','minimum weights','serialized total','cash floor'],
              'unverified':['factor OOS','full pipeline OOS','independent human news labels and holdout','realized performance','native Excel application execution']}
dump('validation.json', validation)
print(json.dumps({'included':[(x['ticker'],x['company_name'],x['weight'],x['sector']) for x in included],'cash':cash,'regime':risk['market_regime'],'excluded':[(x['ticker'],x['exclusion_reason']) for x in excluded]},ensure_ascii=False))
