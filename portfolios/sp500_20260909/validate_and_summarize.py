"""Validate this research snapshot and preserve readable allocation evidence."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.agents/skills/portfolio-report/scripts'))
import generate_portfolio_report as report


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def main():
    predict = read('sp500_predict.json')
    portfolio = read('sp500_portfolio.json')
    portfolio['research_provenance']['input_provenance'] = predict.get('input_provenance', {})
    portfolio['research_provenance']['exact_pipeline_oos_validated'] = False
    (OUT / 'sp500_portfolio.json').write_text(json.dumps(portfolio, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    risk = read('sp500_risk.json')
    universe = read('sp500_constituents_20260909.json')
    source = read('investor_source_data.json')
    analyses = report.load_investor_analyses(OUT / 'investor_analyses.json', predict['analysis_date'])
    investors = ['buffett', 'lynch', 'fisher']
    top = predict['rankings'][:30]
    sectors = report.fetch_sectors(top, predict['analysis_date'])
    candidates, excluded_majority = report.build_candidates(top, investors, sectors, analyses)
    candidates, excluded_risk = report.apply_risk_adjustment(candidates, risk)
    included, excluded_weight, cash = report.allocate_weights(
        candidates, target_cash_weight=risk['market_regime']['target_cash_weight'] * 100)
    sector_weights = defaultdict(float)
    for row in included:
        sector_weights[row['sector']] += row['weight'] / 100
        assert row['analysis_source'] == 'independent_investor_analysis'
        assert sum(a['signal'] == 'bullish' for a in row['investor_analysis'].values()) >= 2
    w = portfolio['weights']
    assert len(w) == len(included)
    assert w == {r['ticker']: round(r['weight'] / 100, 6) for r in included}
    assert abs(sum(w.values()) + portfolio['cash_weight'] - 1) < 1e-9
    assert abs(cash / 100 - portfolio['cash_weight']) < 1e-9
    assert all(.02 - 1e-9 <= v <= .15 + 1e-9 for v in w.values())
    assert all(v <= .35 + 1e-9 for v in sector_weights.values())
    assert portfolio['cash_weight'] >= risk['market_regime']['target_cash_weight']
    assert predict['analysis_date'] == risk['analysis_date'] == portfolio['analysis_date'] == source['analysis_date']
    assert risk['market_regime']['as_of_date'] <= predict['analysis_date']
    assert set(w) <= set(universe['tickers'])
    assert len({r['ticker'] for r in predict['rankings']}) == len(predict['rankings'])
    assert all(r['data_as_of'] == predict['analysis_date'] for r in predict['rankings'])
    assert all(set(analyses[r['ticker']]) >= set(investors) for r in top)
    assert all(analyses[r['ticker']][i].get('analysis_source') == 'independent_investor_analysis' for r in top for i in investors)
    vols = risk['annualized_volatility']
    corr = risk['correlation']
    variance = sum(w[t] * w[u] * vols[t] * vols[u] * corr[t][u] for t in w for u in w)
    assert variance >= 0 and math.isfinite(variance)
    for t in w:
        assert 0 < vols[t] and math.isfinite(vols[t])
        assert abs(corr[t][t] - 1) < 1e-9
        assert all(-1 <= corr[t][u] <= 1 and abs(corr[t][u] - corr[u][t]) < 1e-9 for u in w)
    price_coverage = {}
    risk_price_inputs = {}
    for t in [r['ticker'] for r in top] + ['SPY']:
        # Read the exact cache used by build_risk_snapshot, without changing the window.
        scripts = ROOT / '.agents/skills/predict/scripts'
        key = f"prices_yf_{t}_{predict['analysis_date']}_{risk['lookback_start']}"
        path = scripts / '.cache' / predict['analysis_date'] / (hashlib.md5(key.encode()).hexdigest()[:16] + '.json')
        if path.exists():
            prices = json.loads(path.read_text(encoding='utf-8'))
            risk_price_inputs[t] = prices
            dates = [r.get('date') or r.get('time') for r in prices if r.get('close') is not None]
            price_coverage[t] = {'count': len(dates), 'first': min(dates), 'last': max(dates), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            assert max(dates) <= predict['analysis_date']
        else:
            price_coverage[t] = {'cache_not_found': True}
    assert all(not v.get('cache_not_found') for v in price_coverage.values())
    (OUT / 'risk_price_inputs.json').write_text(json.dumps({'source': 'Yahoo Finance adjusted daily OHLCV', 'analysis_date': predict['analysis_date'], 'tickers': risk_price_inputs}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    metrics_input = {}
    for ticker in universe['tickers']:
        key = f"metrics_yf_{ticker}_{predict['analysis_date']}_"
        path = scripts / '.cache' / predict['analysis_date'] / (hashlib.md5(key.encode()).hexdigest()[:16] + '.json')
        metrics_input[ticker] = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    (OUT / 'predict_input_metrics.json').write_text(json.dumps({'source': 'Yahoo Finance current snapshot', 'analysis_date': predict['analysis_date'], 'tickers': metrics_input}, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    files = ['sp500_predict.json', 'investor_source_data.json', 'investor_analyses.json', 'sp500_risk.json', 'sp500_portfolio.json', 'sp500_constituents_20260909.json', 'provider_readiness.json', 'ssga_membership_crosscheck.json', 'primary_source_spot_checks.json', 'risk_price_inputs.json', 'predict_input_metrics.json']
    evidence = {
        'analysis_date': predict['analysis_date'],
        'validated_at': datetime.now(timezone.utc).isoformat(),
        'constraints_passed': True,
        'universe_count': len(universe['tickers']),
        'ranked_count': len(predict['rankings']),
        'unranked_tickers': sorted(set(universe['tickers']) - {r['ticker'] for r in predict['rankings']}),
        'independent_analysis_count': sum(len(analyses[r['ticker']]) for r in top),
        'holdings_count': len(w),
        'sector_weights': dict(sector_weights),
        'equity_weight': sum(w.values()),
        'cash_weight': portfolio['cash_weight'],
        'historical_annualized_portfolio_volatility': math.sqrt(variance),
        'volatility_method': 'sqrt(w^T covariance w), daily returns annualized by 252, USD cash volatility assumed zero; historical estimate only',
        'price_coverage': price_coverage,
        'included': included,
        'excluded': excluded_majority + excluded_risk + excluded_weight,
        'input_sha256': {name: hashlib.sha256((OUT / name).read_bytes()).hexdigest() for name in files},
        'limitations': [
            'prior_only factors; no applicable point-in-time OOS evidence for this exact allocation pipeline',
            'Yahoo current financial snapshot. Fiscal period and retrieval date differ; filing vintages not verified.',
            'CF and MU provider FCF differs from issuer measures/windows; unreconciled. IVZ P/E is forward, not trailing.',
            'News score remains neutral and does not differentiate ranks. Complete event/news review not performed.',
            'Wikipedia direct audit failed with HTTP 403. Requests plus pandas table extraction recovered all 503 tickers, matching SSGA ETF proxy as of 2026-09-04.',
            'Historical covariance is an estimate, not a forecast or maximum loss bound. Tax, FX risk, commissions and execution slippage excluded.',
            'Agent OS doctor: PLUGIN_CAPABILITY_REGISTRY_DRIFT unresolved. Not an application data-validation failure.'
        ]
    }
    (OUT / 'validation_summary.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({k: v for k, v in evidence.items() if k not in {'included', 'excluded', 'input_sha256', 'price_coverage', 'limitations'}}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
