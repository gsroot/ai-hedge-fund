"""Serialize article-by-article decisions authored by the active skill LLM."""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
tasks = json.loads((OUT/'news_tasks.json').read_text(encoding='utf-8'))
decisions = {}
for name in ['news_decisions.json','news_decisions_2.json','news_decisions_3.json','news_decisions_4.json']:
    chunk = json.loads((OUT/name).read_text(encoding='utf-8'))
    assert not (set(chunk) & set(decisions))
    decisions.update(chunk)
# These are serialization aliases for explicit LLM decisions, not keyword classification rules.
codes = {
    'A': ('ambiguous','macro_industry','neutral','unknown','none',45,True),
    'U': ('unrelated','other','neutral','none','none',90,True),
    'M': ('ambiguous','market_price_recap','neutral','none','intraday',90,True),
    'T': ('relevant','market_price_recap','neutral','none','intraday',95,False),
    'R': ('relevant','routine_disclosure','neutral','unknown','none',95,False),
    'O': ('relevant','other','neutral','unknown','none',70,False),
    'P': ('relevant','product_partnership','positive','unknown','medium',75,False),
    'C': ('relevant','contract','neutral','unknown','medium',80,False),
    'N': ('relevant','other','negative','unknown','medium',75,False),
    'G': ('relevant','other','neutral','unknown','short',65,False),
    'I': ('relevant','management','neutral','unknown','long',75,False),
}
results=[]
for task in tasks['tasks']:
    ticker=task['ticker']
    assert {x[0] for x in decisions[ticker]} == {x['article_index'] for x in task['articles']}
    rows=[]
    for index, code, reasoning in decisions[ticker]:
        values=codes[code]
        rows.append(dict(zip(['relevance','event_type','sentiment','surprise','impact_horizon','confidence','abstain'],values),article_index=index,reasoning=reasoning))
    results.append({'ticker':ticker,'classifications':rows})
payload={'schema_version':2,'classifier_policy_id':'news_event_v2','analysis_date':'2026-09-09','source':'active_skill_llm',
         'limitations':['Classified provided dated article summaries. No full-text or independent human accuracy validation.','Multiple publishers can describe the same economic event; classification counts are not independent event counts.'],
         'results':results}
(OUT/'news_classifications.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print({'tickers':len(results),'articles':sum(len(x['classifications']) for x in results)})
