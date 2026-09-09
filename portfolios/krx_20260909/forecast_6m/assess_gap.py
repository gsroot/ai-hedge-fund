"""Exposure diagnostics and conditional arithmetic; no return-alpha forecast."""
import hashlib
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT / '.agents/skills/predict/scripts'))
from data_fetcher import get_prices

protocol = json.loads((OUT/'research_protocol.json').read_text(encoding='utf-8'))
portfolio_path = OUT.parent/'portfolio.json'
portfolio = json.loads(portfolio_path.read_text(encoding='utf-8'))
weights = pd.Series(portfolio['weights'], dtype=float)
cash = portfolio['cash_weight']
assert abs(weights.sum()+cash-1) < 1e-12
cutoff = protocol['price_cutoff']
benchmark = protocol['benchmark']
tickers = [*weights.index, benchmark]
cache_path = OUT/'price_inputs.json'
if cache_path.exists():
    price_inputs = json.loads(cache_path.read_text(encoding='utf-8'))
else:
    raw, metadata = {}, {}
    for ticker in tickers:
        # Yahoo end is exclusive; request one more calendar day, then explicitly clip.
        end = (datetime.fromisoformat(cutoff)+timedelta(days=1)).date().isoformat() if ticker == benchmark else cutoff
        rows = get_prices(ticker, protocol['data_request_start'], end)
        rows = [r for r in rows if protocol['data_request_start'] <= str(r.get('date') or r.get('time'))[:10] <= cutoff]
        assert rows, ticker
        raw[ticker] = rows
        metadata[ticker] = {'requested_start':protocol['data_request_start'], 'api_end_argument':end, 'analysis_cutoff':cutoff,
                            'provider':'Yahoo Finance' if ticker == benchmark else 'Korean price fetcher: FinanceDataReader primary, PyKRX fallback',
                            'retrieved_at':datetime.now(timezone.utc).isoformat()}
    price_inputs = {'prices':raw,'metadata':metadata}
    cache_path.write_text(json.dumps(price_inputs,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

series = {}
ranges = {}
for ticker in tickers:
    records = price_inputs['prices'][ticker]
    dates = [pd.Timestamp(str(r.get('date') or r.get('time'))[:10]) for r in records]
    assert len(dates) == len(set(dates)), ticker
    s = pd.Series([float(r['close']) for r in records], index=dates).sort_index()
    assert np.isfinite(s).all() and (s>0).all()
    assert s.index.max().date().isoformat() <= cutoff
    series[ticker] = s
    ranges[ticker] = {'first':s.index.min().date().isoformat(),'last':s.index.max().date().isoformat(),'observations':len(s)}

# Calculate returns before alignment: a missing observation must not bridge dates silently.
prices = pd.DataFrame(series).sort_index()
returns = prices.pct_change(fill_method=None).dropna(how='any')
returns.to_csv(OUT/'aligned_daily_returns.csv',index_label='date',float_format='%.12g')
assert len(returns) >= 252
x = returns[benchmark]
y = returns[weights.index] @ weights

def diagnostics(portfolio_returns, benchmark_returns):
    covariance = float(portfolio_returns.cov(benchmark_returns))
    beta = covariance / float(benchmark_returns.var(ddof=1))
    active = portfolio_returns - benchmark_returns
    intercept = float(portfolio_returns.mean()-beta*benchmark_returns.mean())
    residuals = portfolio_returns-intercept-beta*benchmark_returns
    return {'observations':len(active),'first_return':active.index.min().date().isoformat(),
            'last_return':active.index.max().date().isoformat(),'beta':beta,
            'correlation':float(portfolio_returns.corr(benchmark_returns)),
            'portfolio_annualized_volatility':float(portfolio_returns.std(ddof=1)*math.sqrt(252)),
            'benchmark_annualized_volatility':float(benchmark_returns.std(ddof=1)*math.sqrt(252)),
            'active_annualized_volatility':float(active.std(ddof=1)*math.sqrt(252)),
            'active_six_month_sqrt_time_scale':float(active.std(ddof=1)*math.sqrt(126)),
            'residual_six_month_sqrt_time_scale':float(residuals.std(ddof=1)*math.sqrt(126)),
            'historical_daily_intercept_not_forecast':intercept}

windows = {str(n):diagnostics(y.tail(n),x.tail(n)) for n in [63,126,252]}
windows['all_common'] = diagnostics(y,x)

rng = np.random.default_rng(protocol['bootstrap_seed'])
boot = []
sample = np.column_stack([y.to_numpy(), x.to_numpy()])
n = len(sample)
block = protocol['block_length']
for _ in range(protocol['bootstrap_samples']):
    starts = rng.integers(0,n-block+1,size=math.ceil(n/block))
    idx = np.concatenate([np.arange(s,s+block) for s in starts])[:n]
    a,b = sample[idx,0],sample[idx,1]
    boot.append([np.cov(a,b,ddof=1)[0,1]/np.var(b,ddof=1),np.std(a-b,ddof=1)*math.sqrt(126)])
boot = np.asarray(boot)
bootstrap = {'scope':'Parameter sensitivity under resampling, not a future prediction interval or accuracy score',
             'samples':len(boot),'block_length':block,
             'beta_quantiles_05_50_95':np.quantile(boot[:,0],[.05,.5,.95]).tolist(),
             'six_month_risk_scale_quantiles_05_50_95':np.quantile(boot[:,1],[.05,.5,.95]).tolist()}

scenarios = []
for cash_rate in protocol['cash_annual_sensitivity']:
    cash_return = math.sqrt(1+cash_rate)-1
    for market_return in protocol['kospi_six_month_scenarios']:
        assumed_stock_return = market_return
        portfolio_return = weights.sum()*assumed_stock_return+cash*cash_return
        break_even_outperformance = cash/weights.sum()*(market_return-cash_return)
        row = {'market_return':market_return,'cash_annual_rate_assumption':cash_rate,'cash_six_month_return':cash_return,
               'equity_basket_outperformance_assumption':0,'portfolio_return':portfolio_return,
               'portfolio_minus_kospi':portfolio_return-market_return,
               'required_equity_basket_outperformance_to_match_kospi':break_even_outperformance,
               'portfolio_gap_if_basket_outperforms_by_5pp':portfolio_return+.05*weights.sum()-market_return,
               'portfolio_gap_if_basket_outperforms_by_10pp':portfolio_return+.10*weights.sum()-market_return}
        assert abs(weights.sum()*(market_return+break_even_outperformance)+cash*cash_return-market_return)<1e-12
        assert abs(row['portfolio_minus_kospi']-cash*(cash_return-market_return))<1e-12
        scenarios.append(row)

stock_diagnostics = {}
for ticker in weights.index:
    stock_diagnostics[ticker] = {'beta_252':float(returns[ticker].tail(252).cov(x.tail(252))/x.tail(252).var()),
                                'weight':float(weights[ticker])}

result = {'as_of':cutoff,'horizon_end':protocol['horizon_end'],'horizon_trading_days_approx':126,'benchmark':benchmark,
          'portfolio_sha256':hashlib.sha256(portfolio_path.read_bytes()).hexdigest(),
          'point_forecast_excess_return':None,'calibrated_outperformance_probability':None,
          'accuracy_status':'unvalidated','reason':'No independent same-pipeline six-month OOS alpha evidence; current joint history is too short for reliable calibration',
          'cash_weight':cash,'price_ranges':ranges,'common_observations':len(returns),
          'available_nonoverlapping_six_month_blocks':len(returns)//126,
          'six_month_blocks_after_one_126_day_training_block':max(0,(len(returns)-126)//126),
          'risk_diagnostics':windows,'individual_risk':stock_diagnostics,'bootstrap_sensitivity':bootstrap,
          'scenarios':scenarios,
          'assumptions':['Current weights applied to individual daily returns only to estimate current exposure, not to backtest selection performance',
                         'Scenarios use initial weights held over six months; no assumed interim rebalance',
                         'KOSPI price returns; stock dividends, trading costs and tax omitted and must be added for realized total-return comparison',
                         'Cash 0% and 3% annual rates are sensitivities, not offered rates',
                         'Square-root time scaling is descriptive; not a calibrated confidence interval or guaranteed loss bound',
                         'Historical regression intercept is not extrapolated; its sign changes across windows']}
(OUT/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
print(json.dumps({'ranges':ranges,'risk':windows,'bootstrap':bootstrap,'blocks':result['available_nonoverlapping_six_month_blocks']},ensure_ascii=False))
