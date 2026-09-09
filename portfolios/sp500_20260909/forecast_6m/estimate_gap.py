"""Reproducible six-month conditional return-gap and historical-risk estimates."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    assumptions = read(HERE / 'assumptions.json')
    portfolio = read(HERE.parent / 'sp500_portfolio.json')
    manifest = read(HERE / 'price_manifest.json')
    weights = pd.Series(portfolio['weights'], dtype=float)
    cash = portfolio['cash_weight']
    equity = float(weights.sum())
    assert math.isclose(equity + cash, 1.0)
    assert assumptions['exact_pipeline_oos_validated'] is False
    series = {}
    for ticker in [*weights.index, 'SPY']:
        source = HERE / f'{ticker}_prices.csv'
        assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['tickers'][ticker]['sha256']
        frame = pd.read_csv(source, index_col='Date', parse_dates=True)
        series[ticker] = frame['Adj Close']
    prices = pd.DataFrame(series).sort_index()
    assert prices.index.is_unique and not prices.isna().any().any()
    assert (prices > 0).all().all()
    assert str(prices.index.max().date()) == assumptions['price_cutoff']
    returns = prices.pct_change(fill_method=None).iloc[1:]
    windows = []
    for count in assumptions['beta_window_observations']:
        data = returns.tail(count)
        market = data['SPY']
        p = data[weights.index] @ weights
        benchmark_variance = market.var(ddof=1)
        beta = float(p.cov(market) / benchmark_variance)
        stock_betas = {t: float(data[t].cov(market) / benchmark_variance) for t in weights.index}
        assert math.isclose(beta, sum(weights[t] * stock_betas[t] for t in weights.index))
        active = p - market
        annual_te = float(active.std(ddof=1) * math.sqrt(252))
        residual = p - beta * market
        annual_residual_vol = float(residual.std(ddof=1) * math.sqrt(252))
        decomposition = (beta - 1)**2 * benchmark_variance * 252 + annual_residual_vol**2
        assert math.isclose(annual_te**2, decomposition, rel_tol=1e-10)
        # Blocks retain local serial dependence. Centering removes the historical mean;
        # these are synthetic first-order shock magnitudes, not calibrated intervals.
        centered = active.to_numpy() - active.mean()
        block = 20
        horizon = assumptions['horizon_trading_days_approximation']
        generator = np.random.default_rng(20260909 + count)
        starts = generator.integers(0, len(centered), size=(20000, math.ceil(horizon / block)))
        indexes = (starts[..., None] + np.arange(block)) % len(centered)
        samples = centered[indexes].reshape(20000, -1)[:, :horizon].sum(axis=1)
        windows.append({
            'requested_daily_returns': count, 'actual_daily_returns': len(data),
            'first_return_date': str(data.index.min().date()), 'last_return_date': str(data.index.max().date()),
            'portfolio_beta': beta, 'equity_sleeve_beta': beta / equity, 'stock_betas': stock_betas,
            'annual_tracking_error': annual_te,
            'six_month_active_return_sd_sqrt_time': annual_te * math.sqrt(assumptions['horizon_years_approximation']),
            'annual_portfolio_volatility': float(p.std(ddof=1) * math.sqrt(252)),
            'annual_market_volatility': float(market.std(ddof=1) * math.sqrt(252)),
            'annual_residual_volatility': annual_residual_vol,
            'centered_block_bootstrap_shock_quantiles': {str(q): float(np.quantile(samples, q)) for q in [.025, .1, .5, .9, .975]},
            'bootstrap': {'samples': len(samples), 'block_days': block, 'horizon_days': horizon, 'seed': 20260909 + count, 'calibrated_predictive_interval': False},
        })
    beta = sum(row['portfolio_beta'] * weight for row, weight in zip(windows, assumptions['beta_window_weights']))
    rf = assumptions['annual_short_rate_assumption'] * assumptions['horizon_years_approximation']
    market_prior = (1 + assumptions['annual_market_return_prior'])**assumptions['horizon_years_approximation'] - 1

    def calculate(market_return, cash_return, b=beta):
        equity_contribution = equity * rf + b * (market_return - rf)
        p = equity_contribution + cash * cash_return
        gap = p - market_return
        assert math.isclose(gap, (b - 1) * (market_return - rf) + cash * (cash_return - rf), abs_tol=1e-12)
        return {'market_return': market_return, 'portfolio_return': p, 'gap_percentage_points': gap * 100}

    scenarios = {}
    for label, cash_return in assumptions['cash_return_6m_scenarios'].items():
        expected = calculate(market_prior, cash_return)
        expected['window_sensitivity_gap_pp'] = [calculate(market_prior, cash_return, row['portfolio_beta'])['gap_percentage_points'] for row in windows]
        scenarios[label] = {
            'cash_return': cash_return, 'baseline': expected,
            'market_sensitivity': [calculate(market_return, cash_return) for market_return in [-.2, -.1, 0., .05, .1, .2]],
            'equity_sleeve_return_to_match_market_at_market_plus_5pct': (.05 - cash * cash_return) / equity,
        }
    result = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'interpretation': 'unvalidated conditional prior; not a performance claim or a calibrated probability forecast',
        'forecast_start': assumptions['analysis_date'], 'forecast_end_label': assumptions['horizon_end_label'],
        'weights': portfolio['weights'], 'cash_weight': cash,
        'risk_windows': windows, 'ensemble_portfolio_beta': beta,
        'six_month_market_prior': market_prior, 'six_month_risk_free_proxy': rf,
        'scenarios': scenarios,
        'portfolio_only_cost_sensitivity_pp': {
            f'{bps}_bps_one_way': {'entry_only': equity * bps / 100, 'entry_plus_exit_at_unchanged_notional': 2 * equity * bps / 100}
            for bps in [10, 25]
        },
        'alpha_sensitivity': {'a_10_percentage_point_equity_sleeve_outperformance_changes_portfolio_gap_pp': equity * 10},
        'input_hashes': {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in ['assumptions.json', 'price_manifest.json']},
        'forecast_calibrated': False, 'accuracy_estimate': None, 'calculation_checks_passed': True,
    }
    (HERE / 'forecast_results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
