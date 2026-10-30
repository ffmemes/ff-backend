import json, glob, numpy as np, pandas as pd, statsmodels.formula.api as smf
from scipy.stats import spearmanr
from statsmodels.stats.multitest import multipletests
from sklearn.linear_model import RidgeCV, LogisticRegression
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
A=D; rng=np.random.default_rng(0); OUT=[]
def w(s=''): OUT.append(str(s)); print(s)
p=pd.read_csv(f'{D}/posts.tsv',sep='\t'); r=p[p.ch=='ru'].copy()
L=pd.read_json(os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','labels.jsonl'),lines=True)
# labels.jsonl already has the 5 QA swap fixes applied and foreign_watermark dropped
d=r.merge(L,on='meme_id')
assert len(d)==870
for k in ['topics','humor']:
    for v in sorted({x for l in d[k] for x in l}): d[f'{k[:3]}_{v}']=d[k].apply(lambda l:int(v in l))
for c in ['format','text_lang','text_len','valence','quality','addressee']:
    for v in d[c].unique(): d[f'{c}_{v}']=(d[c]==v).astype(int)
d['vulg1']=(d.vulgarity==1).astype(int); d['vulg2']=(d.vulgarity==2).astype(int); d['vulg_any']=(d.vulgarity>0).astype(int)
d['fs_hi']=(d.forward_score>=4).astype(int)
# source fixed effect: sources with >=20 RU posts in the sample, else 'other'
vc=d.meme_source_id.value_counts()
d['src']=d.meme_source_id.where(d.meme_source_id.isin(vc[vc>=20].index)).astype('Int64').astype(str).replace('<NA>','other')
d['age_b']=pd.cut(d.age_published_d,[-1,3,14,60,365,1e5],labels=['a0_3d','a3_14d','a14_60d','a60_365d','a365p']).astype(str)
d['lnl']=np.log1p(d.dl_nlikes.fillna(d.dl_nlikes.median())); d['nl_na']=d.dl_nlikes.isna().astype(int)
d['hour']=d.hour_msk.astype(str)
d['wk']=d.iso_week
feats=[c for c in d.columns if c.startswith(('top_','hum_','format_','text_lang_','text_len_','valence_','quality_','addressee_'))]+['addressable','needs_context','timely','vulg1','vulg2','vulg_any','fs_hi']
feats=[f for f in feats if d[f].sum()>=15 and d[f].sum()<=855]
# ---------- univariate
base_z=d.zf.mean(); base_h=d.hit.mean()
w('# Blind content labels vs RU channel forwards'); w(f'n={len(d)} RU posts, {d.wk.nunique()} weeks; baseline zf={base_z:.3f}, hit={base_h:.3f}')
def boot(x,y,B=2000):
    dif=[rng.choice(x,len(x)).mean()-rng.choice(y,len(y)).mean() for _ in range(B)]
    return np.percentile(dif,[2.5,97.5])
rows=[]
for f in feats+[f'fs_{i}' for i in range(1,6)]:
    m=(d.forward_score==int(f[-1])) if f.startswith('fs_') and f!='fs_hi' else d[f]==1
    a,b=d.zf[m].values,d.zf[~m].values
    lo,hi=boot(a,b); 
    rows.append(dict(feature=f,n=int(m.sum()),zf=a.mean(),dzf=a.mean()-b.mean(),ci_lo=lo,ci_hi=hi,hit=d.hit[m].mean(),hit_rest=d.hit[~m].mean()))
U=pd.DataFrame(rows).sort_values('dzf'); U.to_csv(f'{A}/univariate.tsv',sep='\t',index=False)
w('\n## Univariate (dzf = mean zf with feature − without; bootstrap 95% CI)'); w(U.round(3).to_markdown(index=False))
# ---------- multivariate
ctrl='C(src, Treatment("other")) + C(hour) + C(age_b, Treatment("a365p")) + lnl + nl_na'
mv=['addressable','needs_context','timely','vulg1','vulg2']+[f for f in feats if f.startswith(('top_','hum_'))]+['format_tweet_screenshot','format_multi_panel','format_chat_screenshot','format_photo_no_text','format_drawing_comic','text_len_long','text_len_medium','text_len_none','valence_negative','valence_positive','quality_low','quality_high']
mv=[f for f in mv if f in feats and f not in ('top_other','hum_vulgar')]  # hum_vulgar ~ collinear with vulg
fo=f'zf ~ {"+".join(mv)} + {ctrl}'
ols=smf.ols(fo,d).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(d.wk)[0]})
lg=smf.logit(f'hit ~ {"+".join(mv)} + {ctrl}',d).fit(disp=0,cov_type='cluster',cov_kwds={'groups':pd.factorize(d.wk)[0]})
T=pd.DataFrame({'b':ols.params,'lo':ols.conf_int()[0],'hi':ols.conf_int()[1],'p':ols.pvalues,'logit_OR':np.exp(lg.params),'logit_p':lg.pvalues})
lab=T.loc[mv].copy(); lab['q_BH']=multipletests(lab.p,method='fdr_bh')[1]; lab['logit_q_BH']=multipletests(lab.logit_p,method='fdr_bh')[1]
lab=lab.sort_values('p'); lab.to_csv(f'{A}/ols_labels.tsv',sep='\t')
w(f'\n## OLS zf (week-clustered SE), R2={ols.rsquared:.3f}, adjR2={ols.rsquared_adj:.3f}; logit hit pseudoR2={lg.prsquared:.3f}'); w(lab.round(3).to_markdown())
ctl=T.drop(mv).drop('Intercept'); w('\n### Controls'); w(ctl.round(3).to_markdown())
# compact controls-only model for reference
b0=smf.ols(f'zf ~ {ctrl}',d).fit(); w(f'\ncontrols-only R2={b0.rsquared:.3f} adjR2={b0.rsquared_adj:.3f}')
# forward_score alone in multivariate
fsm=smf.ols(f'zf ~ forward_score + {ctrl}',d).fit(cov_type='cluster',cov_kwds={'groups':pd.factorize(d.wk)[0]})
w(f'forward_score coef given controls: {fsm.params.forward_score:.3f} CI [{fsm.conf_int().loc["forward_score",0]:.3f},{fsm.conf_int().loc["forward_score",1]:.3f}] p={fsm.pvalues.forward_score:.3g}')
rho=spearmanr(d.forward_score,d.zf); w(f'forward_score Spearman with zf (all): {rho.statistic:.3f} p={rho.pvalue:.3g}')
# ---------- time split
weeks=sorted(d.wk.unique()); cut=weeks[int(round(len(weeks)*0.7))-1]
tr=d[d.wk<=cut]; te=d[d.wk>cut]
w(f'\n## Time split: train weeks ≤{cut} (n={len(tr)}), test {len(te)} posts / {te.wk.nunique()} weeks')
def metrics(pred,df):
    df=df.assign(pred=pred); rho=spearmanr(df.pred,df.zf).statistic
    df['rk']=df.groupby('wk').pred.rank(pct=True,ascending=False)
    top=df[df.rk<=0.2]; return rho, top.hit.mean()/df.hit.mean(), top.zf.mean()
def bootm(pred,df,B=1000):
    df=df.assign(pred=pred).reset_index(drop=True); wk=df.wk.unique(); res=[]
    for _ in range(B):
        s=pd.concat([df[df.wk==x] for x in rng.choice(wk,len(wk))]); res.append(metrics(s.pred.values,s)[:2])
    return np.percentile(np.array(res),[2.5,97.5],axis=0)
X_ctrl=pd.get_dummies(d[['src','hour','age_b']]).astype(float).assign(lnl=d.lnl,nl_na=d.nl_na)
Xb=pd.get_dummies(d[['src']]).astype(float).assign(lnl=d.lnl,nl_na=d.nl_na)  # ≈ v4: source prior + bot likes
Xl=d[mv].astype(float)
res={}
def fit_pred(X):
    m=RidgeCV(alphas=np.logspace(-2,3,30)).fit(X.loc[tr.index],tr.zf); return m.predict(X.loc[te.index])
cands={'baseline src+lnl (≈v4)':Xb,'baseline + all labels':pd.concat([Xb,Xl],axis=1),'baseline + forward_score':Xb.assign(fs=d.forward_score),
       'controls (src+hour+age+lnl)':X_ctrl,'controls + all labels':pd.concat([X_ctrl,Xl],axis=1),'forward_score alone':d[['forward_score']].astype(float),
       'lnl alone':d[['lnl']]}
preds={}
for k,X in cands.items():
    pr=fit_pred(X) if k!='forward_score alone' else d.loc[te.index,'forward_score'].values+rng.normal(0,1e-6,len(te))
    preds[k]=pr; rho,lift,tz=metrics(pr,te.copy()); ci=bootm(pr,te.copy())
    res[k]=dict(spearman=rho,sp_lo=ci[0,0],sp_hi=ci[1,0],top20_lift=lift,lift_lo=ci[0,1],lift_hi=ci[1,1],top20_zf=tz)
R=pd.DataFrame(res).T; w(R.round(3).to_markdown()); R.to_csv(f'{A}/timesplit.tsv',sep='\t')
# paired diff: baseline+labels vs baseline (week bootstrap)
def paired(k1,k0,B=1000):
    df=te.assign(p1=preds[k1],p0=preds[k0]).reset_index(drop=True); wk=df.wk.unique(); out=[]
    for _ in range(B):
        s=pd.concat([df[df.wk==x] for x in rng.choice(wk,len(wk))])
        out.append([metrics(s.p1.values,s)[0]-metrics(s.p0.values,s)[0], metrics(s.p1.values,s)[1]-metrics(s.p0.values,s)[1]])
    return np.percentile(np.array(out),[2.5,50,97.5],axis=0).round(3)
for k1,k0 in [('baseline + all labels','baseline src+lnl (≈v4)'),('baseline + forward_score','baseline src+lnl (≈v4)'),('controls + all labels','controls (src+hour+age+lnl)')]:
    w(f'paired Δ ({k1} − {k0}) [2.5,50,97.5] spearman={paired(k1,k0)[:,0].tolist()} lift={paired(k1,k0)[:,1].tolist()}')
d.to_pickle(f'{A}/d.pkl'); open(f'{A}/report_stats.md','w').write('\n'.join(OUT))
