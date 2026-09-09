"""Combine separately authored opinions without deriving opinions from predict."""
import json
from pathlib import Path

out = Path(__file__).resolve().parent
source = json.loads((out / 'investor_source_data.json').read_text(encoding='utf-8'))
date = source['analysis_date']
tickers = list(source['tickers'])
combined = {t: {} for t in tickers}
for investor in ['buffett', 'lynch', 'fisher']:
    p = json.loads((out / f'investor_{investor}.json').read_text(encoding='utf-8-sig'))
    assert p['analysis_date'] == date
    assert set(p['analyses']) == set(tickers)
    for ticker, opinion in p['analyses'].items():
        assert opinion['analysis_source'] == 'independent_investor_analysis'
        assert opinion['analysis_date'] == date
        assert opinion['signal'] in {'bullish', 'neutral', 'bearish'}
        assert 0 <= opinion['confidence'] <= 100
        assert opinion['data_quality'] in {'complete', 'partial', 'insufficient'}
        assert opinion['reasoning'].strip()
        combined[ticker][investor] = opinion
result = {
    'analysis_date': date,
    'analysis_source': 'independent_investor_analysis',
    'independence': 'Three separate Codex agents, one persona each. Raw financial snapshots and selected issuer facts only; no predict scores or other persona conclusions provided.',
    'confidence_meaning': 'Subjective strength of evidence, not probability of return or success.',
    'sources': ['investor_source_data.json', 'primary_source_spot_checks.json'],
    'analyses': combined,
}
(out / 'investor_analyses.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
print(f'Combined {len(combined)} tickers and {sum(len(v) for v in combined.values())} independent opinions')
