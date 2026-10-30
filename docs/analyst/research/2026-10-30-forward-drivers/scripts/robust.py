import numpy as np, pandas as pd, statsmodels.formula.api as smf
from scipy.stats import spearmanr
from sklearn.linear_model import RidgeCV
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
d=pd.read_pickle(f'{A}/d.pkl'); rng=np.random.default_rng(1); OUT=[]
def w(s=''): OUT.append(str(s)); print(s)
d['fresh60']=(d.age_published_d<60).astype(int); d['pun_vulg']=d.hum_wordplay_pun*d.vulg_any
d['text_heavy']=d.text_len.isin(['medium','long']).astype(int)
ctrl='C(src) + lnl + nl_na + C(hour)'
weeks=sorted(d.wk.unique()); cut=weeks[17]; d['period']=np.where(d.wk<=cut,'train','test')
w('## Robustness: per-feature effect (OLS zf, controls src+lnl+hour+fresh60), by period and score regime')
rows=[]
for f in ['format_tweet_screenshot','format_chat_screenshot','top_politics_news','hum_wordplay_pun','needs_context','vulg2','pun_vulg','text_len_long','text_heavy','addressable','top_romance_couple','top_work_office','top_it_programming','top_gaming','fs_hi','fresh60']:
    for name,sub in [('all',d),('train',d[d.period=='train']),('test',d[d.period=='test']),('v2',d[d.dl_sv==2]),('v4',d[d.dl_sv==4])]:
        extra='' if f=='fresh60' else '+ fresh60'
        m=smf.ols(f'zf ~ {f} {extra} + {ctrl}',sub).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(sub.wk)[0]})
        rows.append(dict(feature=f,subset=name,n1=int(sub[f].sum()),b=m.params[f],lo=m.conf_int().loc[f,0],hi=m.conf_int().loc[f,1],p=m.pvalues[f]))
R=pd.DataFrame(rows); R.to_csv(f'{A}/robust_by_period.tsv',sep='\t',index=False)
w(R.pivot(index='feature',columns='subset',values='b').round(3)[['all','train','test','v2','v4']].to_markdown())
w('\np-values'); w(R.pivot(index='feature',columns='subset',values='p').round(3)[['all','train','test','v2','v4']].to_markdown())
# within-source tweet effect
g=d.groupby(['src','format_tweet_screenshot']).zf.agg(['mean','size']).unstack()
w('\n## tweet_screenshot within source (zf mean, n)'); w(g.round(3).to_markdown())
# within-week paired: hit rate
w(f"\nhit rate tweet={d[d.format_tweet_screenshot==1].hit.mean():.3f} vs non={d[d.format_tweet_screenshot==0].hit.mean():.3f}")
# tweet vs text length overlap
w(pd.crosstab(d.format,d.text_len).to_markdown())
# compact time split: baseline vs baseline+{non_tweet} ; bootstrap by week
tr=d[d.period=='train']; te=d[d.period=='test']
def metr(pred,df):
    df=df.assign(pred=pred); rk=df.groupby('wk').pred.rank(pct=True,ascending=False)
    return spearmanr(df.pred,df.zf).statistic, df[rk<=0.2].hit.mean()/df.hit.mean()
Xb=pd.get_dummies(d[['src']]).astype(float).assign(lnl=d.lnl,nl_na=d.nl_na)
sets={'base':Xb,'base+fresh':Xb.assign(f=d.fresh60),'base+tweet':Xb.assign(t=d.format_tweet_screenshot),
      'base+fresh+tweet':Xb.assign(f=d.fresh60,t=d.format_tweet_screenshot),
      'base+fresh+tweet+pol+pun+nc':Xb.assign(f=d.fresh60,t=d.format_tweet_screenshot,p=d.top_politics_news,u=d.hum_wordplay_pun,c=d.needs_context)}
P={}
for k,X in sets.items():
    m=RidgeCV(alphas=np.logspace(-2,3,30)).fit(X.loc[tr.index],tr.zf); P[k]=m.predict(X.loc[te.index])
    if k!='base': w(f'{k} coefs: '+', '.join(f'{c}={v:.3f}' for c,v in zip(X.columns,m.coef_) if c in ('f','t','p','u','c')))
# also the simple rule: non-tweet multiplier on baseline rank
P['base×(tweet?0.8:1) rank']=np.log(np.exp(P['base']-P['base'].min()+0.1))+np.log(np.where(te.format_tweet_screenshot==1,0.8,1.0))
w('\n## Compact time split (test 7 weeks, n=%d)'%len(te))
res={}
wk=te.wk.unique()
B=[ [te.wk==x for x in rng.choice(wk,len(wk))] for _ in range(1000)]
for k,pr in P.items():
    s,l=metr(pr,te); bs=[]; bd=[]
    for idx in B:
        sub=pd.concat([te[m].assign(pred=pr[m.values],p0=P['base'][m.values]) for m in idx])
        a=metr(sub.pred.values,sub); b=metr(sub.p0.values,sub); bd.append([a[0]-b[0],a[1]-b[1]])
    q=np.percentile(bd,[2.5,97.5],axis=0)
    res[k]=dict(spearman=s,top20_lift=l,dSp_lo=q[0,0],dSp_hi=q[1,0],dLift_lo=q[0,1],dLift_hi=q[1,1])
w(pd.DataFrame(res).T.round(3).to_markdown())
# forward_score in each period
for n,s in [('train',tr),('test',te)]: w(f'forward_score Spearman {n}: {spearmanr(s.forward_score,s.zf).statistic:.3f}')
open(f'{A}/report_robust.md','w').write('\n'.join(OUT))
