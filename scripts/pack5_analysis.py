"""Analysis of Argon pack 5 (specs/record-weight-2026-11-08.yaml references.R4_pairs_argon). Free.

    python -m scripts.pack5_analysis
"""
import json, math
from collections import Counter, defaultdict
from scipy.stats import kendalltau
D='/home/user/longevity-kg/reviews/argon-2026-11-08/'
ans=json.load(open(D+'pack_5_answer.json')); key=json.load(open(D+'pack_5_key.json')); task=json.load(open(D+'pack_5_task.json'))
A={p['id']:p for p in ans['pairs']}; K={p['id']:p for p in key['pairs']}
def sgn(w,band=0.1):
    d=math.log(w[0]/w[1]); return 0 if abs(d)<band else (1 if d>0 else -1)
arg=lambda i:{'A':1,'B':-1,'equal':0}[A[i]['stronger']]
main=[i for i in K if not K[i]['swapped']]
out={}
for wk in ('w_v35','w_candidate'):
    x=[arg(i) for i in main]; y=[sgn(K[i][wk]) for i in main]
    tau=kendalltau(x,y,variant='b').statistic
    ne=[(a,b) for a,b in zip(x,y) if a!=0 and b!=0]
    conc=sum(a==b for a,b in ne)/len(ne)
    per=defaultdict(list)
    for i in main:
        a,b=arg(i),sgn(K[i][wk])
        if a and b: per[K[i]['stratum']].append(a==b)
    out[wk]={'tau_b':round(tau,3),'concordance_non_tied':round(conc,3),'n_non_tied':len(ne),
             'per_stratum':{k:f"{sum(v)}/{len(v)}" for k,v in sorted(per.items())}}
print(json.dumps(out,indent=1))
print("argon calls equal:",sum(arg(i)==0 for i in main),"of",len(main))
# repeatability
rep=[i for i in K if K[i]['swapped']]
src={K[i]['src']:i for i in main}
agree=sum(arg(i)==-arg(src[K[i]['src']]) for i in rep); print("repeat agreement",agree,"/",len(rep))
print("reasons main:",Counter(A[i]['reasons'][0] for i in main).most_common())
print("finding_misread anywhere:",sum('finding_misread' in A[i]['reasons'] for i in main))
# labels
R={r['id']:r for r in ans['records']}; KR=key['records']
def kappa(pairs):
    n=len(pairs); po=sum(a==b for a,b in pairs)/n; ca=Counter(a for a,_ in pairs); cb=Counter(b for _,b in pairs)
    pe=sum(ca[k]*cb[k] for k in set(ca)|set(cb))/n**2; return round((po-pe)/(1-pe),3), round(po,3)
pc=[(KR[i]['verifier_context'],R[i]['context']) for i in KR]
print("context verifier vs argon kappa,agree",kappa(pc),Counter(f"{a}->{b}" for a,b in pc).most_common(8))
print("argon context dist",Counter(R[i]['context'] for i in R))
bw=Counter((KR[i]['blinding_words'],R[i]['blinding']) for i in KR if KR[i]['design'] in('rct','non_randomised'))
print("blinding words vs argon (trials):",bw.most_common())
sj=Counter((KR[i]['subjective_rule'],R[i]['outcome_subjective']) for i in KR); print("subjective rule vs argon",sj.most_common())
ds=Counter((KR[i]['design'],R[i]['design']) for i in KR); print("design agree", sum(v for (a,b),v in ds.items() if a==b),"/",sum(ds.values()))
nn=[(KR[i]['n_total'],R[i]['n_total']) for i in KR]; print("n agree", sum(1 for a,b in nn if a==b),"/",len(nn), "ours None argon num", sum(1 for a,b in nn if a is None and b))
