# One-feature-at-a-time screen with controls (src+lnl+hour+age bucket), week-clustered SE, BH over all label features.
import numpy as np, pandas as pd, statsmodels.formula.api as smf
from statsmodels.stats.multitest import multipletests
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
d=pd.read_pickle(f'{A}/d.pkl'); g=pd.factorize(d.wk)[0]
feats=[c for c in d.columns if c.startswith(('top_','hum_','format_','text_len_','valence_','addressee_','quality_'))]+['addressable','needs_context','timely','vulg1','vulg2','fs_hi','forward_score']
feats=[f for f in feats if d[f].nunique()>1 and (f=='forward_score' or 15<=d[f].sum()<=855)]
rows=[]
for f in feats:
    m=smf.ols(f'zf ~ {f} + C(src) + lnl + nl_na + C(hour) + C(age_b)',d).fit(cov_type='cluster',cov_kwds={'groups':g})
    l=smf.logit(f'hit ~ {f} + C(src) + lnl + nl_na + C(hour) + C(age_b)',d).fit(disp=0,cov_type='cluster',cov_kwds={'groups':g})
    rows.append(dict(feature=f,n=int(d[f].sum()) if f!='forward_score' else len(d),b=m.params[f],lo=m.conf_int().loc[f,0],hi=m.conf_int().loc[f,1],p=m.pvalues[f],OR=np.exp(l.params[f]),p_logit=l.pvalues[f]))
S=pd.DataFrame(rows); S['q']=multipletests(S.p,method='fdr_bh')[1]; S['q_logit']=multipletests(S.p_logit,method='fdr_bh')[1]
S=S.sort_values('p'); S.to_csv(f'{A}/screen_bh.tsv',sep='\t',index=False); print(S.head(14).round(4).to_markdown(index=False))
open(f'{A}/report_screen.md','w').write('## Single-feature screen (controls src+lnl+hour+age; BH over %d features)\n'%len(S)+S.round(4).to_markdown(index=False))
