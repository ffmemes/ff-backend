# Time split for the final candidate signals: relatable(-), tweet_screenshot(-), politics(+). Week-block bootstrap of Δ vs baseline.
import numpy as np, pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import RidgeCV
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
d=pd.read_pickle(f'{A}/d.pkl'); rng=np.random.default_rng(2); weeks=sorted(d.wk.unique()); cut=weeks[17]
tr=d[d.wk<=cut]; te=d[d.wk>cut]
def metr(pred,df):
    df=df.assign(pred=pred); rk=df.groupby('wk').pred.rank(pct=True,ascending=False)
    return spearmanr(df.pred,df.zf).statistic, df[rk<=0.2].hit.mean()/df.hit.mean(), df[rk<=0.2].zf.mean()
Xb=pd.get_dummies(d[['src']]).astype(float).assign(lnl=d.lnl,nl_na=d.nl_na)
sets={'base (src+lnl ≈v4)':Xb,'+relatable':Xb.assign(r=d.hum_relatable),'+tweet':Xb.assign(t=d.format_tweet_screenshot),
 '+politics':Xb.assign(p=d.top_politics_news),'+relatable+tweet':Xb.assign(r=d.hum_relatable,t=d.format_tweet_screenshot),
 '+relatable+tweet+politics':Xb.assign(r=d.hum_relatable,t=d.format_tweet_screenshot,p=d.top_politics_news)}
P={k:RidgeCV(alphas=np.logspace(-2,3,30)).fit(X.loc[tr.index],tr.zf).predict(X.loc[te.index]) for k,X in sets.items()}
# fixed multiplier rule on top of base prediction (no refit): penalize 0.1 zf per flag
P['rule: base −0.1·rel −0.1·tweet']=P['base (src+lnl ≈v4)']-0.1*te.hum_relatable.values-0.1*te.format_tweet_screenshot.values
P['rule alone: −rel −tweet (no base)']=-(te.hum_relatable.values+te.format_tweet_screenshot.values)+rng.normal(0,1e-6,len(te))
wk=te.wk.unique(); B=[rng.choice(wk,len(wk)) for _ in range(1000)]
res={}
for k,pr in P.items():
    s,l,z=metr(pr,te); bd=[]
    for b in B:
        idx=np.concatenate([np.where(te.wk.values==x)[0] for x in b]); sub=te.iloc[idx]
        a=metr(pr[idx],sub); c=metr(P['base (src+lnl ≈v4)'][idx],sub); bd.append([a[0]-c[0],a[1]-c[1]])
    q=np.percentile(bd,[2.5,97.5],axis=0); res[k]=dict(spearman=s,top20_lift=l,top20_zf=z,dSp_lo=q[0,0],dSp_hi=q[1,0],dLift_lo=q[0,1],dLift_hi=q[1,1])
R=pd.DataFrame(res).T.round(3); print(R.to_markdown())
open(f'{A}/report_timesplit2.md','w').write(f'## Final-candidate time split (train ≤{cut} n={len(tr)}, test n={len(te)}, 7 weeks)\n'+R.to_markdown())
