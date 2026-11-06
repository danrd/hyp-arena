"""Two OHF ideas checked on the saved records of the calibration (steps 1-5), no model calls (2026-11-06; method-v3.md
section 13): four-axis indirectness (system, intervention, endpoint, comparison) in place of the context and comparison
factors of v3.2, and independence groups by the trial ids in the abstracts.

    python scripts/ohf_probe.py
"""
import json, re, statistics
from collections import Counter
from scipy.stats import spearmanr
from hyparena.backtest import tied_auc
from hyparena.card import rules_v3 as r3, rules_v32 as r32, v3_levels as lv
from hyparena.card.models import ClaimVerification, HypothesisCard
from hyparena.tools import pubmed
C='/home/user/longevity-kg/hypothesis_sources/calibration/'
def axes(rec, claim):
    qm=rec.qualifiers_match; human=r3.human_claim(claim)
    sysl = 'serious' if human and r3.species_key(rec.species or '') not in ('human','') else ('partial' if any(qm.get(k)=='no' for k in ('population','sex','age_at_start','species')) else 'direct')
    im=qm.get('intervention_match','exact')
    inter = 'direct' if im=='exact' else 'partial' if im in ('dose_differs','regimen_differs','related_compound') else 'serious'
    need=r3_endpoint(claim); ep=rec.endpoint
    endp = 'direct' if ep in ('unknown', need) or not need else ('partial' if ep=='biomarker' else 'serious')
    comp = {'between_groups':'direct','within_group':'partial'}.get(rec.comparison,'serious')
    return sysl, inter, endp, comp
from hyparena.card.rules import claim_endpoint as r3_endpoint
W={'direct':1.0,'partial':2/3,'serious':1/3}
def w4(rec, claim, against):
    if not r3.usable(rec,'v3.1') or r3.context_level(rec) is None: return 0.0
    pre = claim.link in r3.PRECLINICAL_LINKS
    w = lv.design_weight(r3.record_design(rec), r3.human_claim(claim) and not pre)*r32.precision(rec.n_total)*r32.effect_weight(rec, against)
    for a in axes(rec, claim): w*=W[a]
    return w
us,res={},{}
for st in (1,2,3,4,5):
    us.update({u['id']:u for u in json.load(open(C+f'units_{st}.json'))}); res.update(json.load(open(C+f'run_{st}_v3.json')))
recs=[]; base_ctx=[]; four=[]; ax=Counter(); trial_groups=Counter(); links_changed=0; links_multi=0
samples={'calib':(1,2,3),'fresh':(4,5)}
P32={}; P4={}
for h,r in res.items():
    if h not in us: continue
    it=r['items'][0]
    if not it.get('card') or not it.get('verification') or 'v3' not in it: continue
    card=HypothesisCard.model_validate(it['card']); cvs=[ClaimVerification.model_validate(c) for c in it['verification']['claims']]
    by={c.id:c for c in card.claims}
    for cv in cvs:
        cl=by.get(cv.id)
        if not cl: continue
        ids=[]
        for rec in cv.evidence+cv.counterevidence:
            if r32.record_weight(rec,cl,False)<=0: continue
            a=axes(rec,cl); ax.update(f'{i}:{v}' for i,v in zip(('system','intervention','endpoint','comparison'),a))
            base_ctx.append(lv.weight('context',r3.context_level(rec))*lv.weight('comparison',rec.comparison if rec.comparison!='unknown' else 'none'))
            four.append(W[a[0]]*W[a[1]]*W[a[2]]*W[a[3]])
            ids.append(rec.record_id.replace('PMID:',''))
        if len(ids)>1:
            links_multi+=1
            ab=pubmed.fetch(ids); tr={p:set(re.findall(r'\b(NCT\d{8}|ISRCTN\d{8})\b',(ab.get(p,{}).get('abstract','')))) for p in ids}
            groups=len({frozenset(v) if v else p for p,v in tr.items()})
            if groups<len(ids): links_changed+=1
    P32[h]=r32.evaluate(card,cvs).P
    orig=r32.record_weight; r32.record_weight=w4
    try: P4[h]=r32.evaluate(card,cvs).P
    finally: r32.record_weight=orig
print('records',len(four)); print('axis distribution',sorted(ax.items()))
print('combined 4-axis: distinct',len({round(x,3) for x in four}),'top share',round(Counter(round(x,3) for x in four).most_common(1)[0][1]/len(four),2),
      '| current ctx*comparison: distinct',len({round(x,3) for x in base_ctx}),'top share',round(Counter(round(x,3) for x in base_ctx).most_common(1)[0][1]/len(base_ctx),2))
print('spearman 4-axis vs current',round(spearmanr(four,base_ctx).correlation,2))
for name,steps in samples.items():
    ids=[h for h in P32 if any(h in json.load(open(C+f'units_{s}.json')) and False for s in steps)]
for name,steps in samples.items():
    sids={u['id'] for s in steps for u in json.load(open(C+f'units_{s}.json'))}
    def auc(P):
        pos=[(P[h],0) for h in P if h in sids and us[h]['label']==1]; neg=[(P[h],0) for h in P if h in sids and us[h]['label']==0]
        return round(tied_auc(pos,neg),3)
    print(name,'P AUC v3.2',auc(P32),'v3.2 with 4 axes',auc(P4))
print('independence: links with >1 record',links_multi,'of them where trial ids merge records',links_changed)
