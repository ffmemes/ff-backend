import json, re, glob, pandas as pd, numpy as np
from sklearn.metrics import cohen_kappa_score
from scipy.stats import spearmanr
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
p=pd.read_csv(f'{D}/posts.tsv',sep='\t'); r=p[p.ch=='ru'].copy()
rows=[]
for f in sorted(glob.glob(f'{D}/labels/batch_*.jsonl')):
    for i,l in enumerate(open(f)):
        d=json.loads(l); d['file']=f.split('/')[-1]; d['line']=i; rows.append(d)
L=pd.DataFrame(rows)
print('labels',len(L),'unique',L.meme_id.nunique(),'in ru',L.meme_id.isin(r.meme_id).sum())
# batch file order check
for f in sorted(glob.glob(f'{D}/batches/*.txt')):
    ids=[int(x) for x in open(f).read().split()]
    print(f.split('/')[-1],len(ids))
m=r.merge(L,on='meme_id',how='left')
stop=set('the a an of to and in is it with on for that this at as by from be are was his her their they he she you your i my me meme text image shows features featuring person man woman caption picture photo screenshot which who about while its into has have joke'.split())
def toks(s): return {w for w in re.findall(r'[a-z]{3,}',str(s).lower()) if w not in stop}
def cyr(s): s=re.sub(r'@ffmemesbot','',str(s)); c=len(re.findall('[а-яё]',s,re.I)); a=len(re.findall('[a-z]',s,re.I)); return c,a
m['ocr']=m.ocr_text.fillna('').str.replace('@ffmemesbot','').str.strip()
m['has_ocr']=m.ocr.str.len()>=8
m['ovl']=[len(toks(a)&toks(b))/max(1,len(toks(a))) if isinstance(b,str) and b else np.nan for a,b in zip(m.desc,m.ocr_description)]
def lang_mis(row):
    if not row.has_ocr: return False
    c,a=cyr(row.ocr)
    if c>15 and a<c*0.3 and row.text_lang=='en': return True
    if a>15 and c<a*0.1 and row.text_lang=='ru': return True
    return False
m['lang_mis']=m.apply(lang_mis,axis=1)
m['none_mis']=m.has_ocr & (m.ocr.str.split().str.len()>4) & (m.text_len=='none')
m['ovl0']=m.ovl==0
m['suspect']=m.lang_mis|m.none_mis|m.ovl0
g=m[m.has_ocr|m.ocr_description.notna()].groupby('file')
print(g.agg(n=('meme_id','size'),lang_mis=('lang_mis','mean'),none_mis=('none_mis','mean'),ovl_mean=('ovl','mean'),ovl0=('ovl0','mean'),suspect=('suspect','mean')).round(3))
m[['meme_id','file','line','text_lang','text_len','desc','ocr','ocr_description','ovl','lang_mis','none_mis','suspect']].to_csv(f'{A}/qa_alignment.tsv',sep='\t',index=False)
# overlap
O=pd.DataFrame([json.loads(l) for l in open(f'{D}/labels/overlap.jsonl')])
J=O.merge(L,on='meme_id',suffixes=('_o','_m'))
print('overlap n',len(J), J.file.value_counts().to_dict())
out={}
for k in ['addressable','vulgarity','needs_context','format','text_lang','text_len','timely','valence']:
    out[k]=(cohen_kappa_score(J[k+'_o'].astype(str),J[k+'_m'].astype(str)), (J[k+'_o']==J[k+'_m']).mean())
for k,v in out.items(): print(f'kappa {k}: {v[0]:.2f} agree {v[1]:.2f}')
print('forward_score spearman', spearmanr(J.forward_score_o,J.forward_score_m))
for k in ['topics','humor']:
    jac=[len(set(a)&set(b))/len(set(a)|set(b)) for a,b in zip(J[k+'_o'],J[k+'_m'])]
    print(k,'jaccard mean',round(np.mean(jac),2))
# per-file overlap agreement on desc tokens (alignment proxy)
J['desc_ovl']=[len(toks(a)&toks(b))/max(1,len(toks(a)|toks(b))) for a,b in zip(J.desc_o,J.desc_m)]
print(J.groupby('file').agg(n=('meme_id','size'),desc_jac=('desc_ovl','mean'),desc_zero=('desc_ovl',lambda s:(s==0).mean()),fs_eq=('forward_score_o',lambda s: 0)).round(2))
J[['meme_id','file','desc_o','desc_m','desc_ovl']].to_csv(f'{A}/qa_overlap.tsv',sep='\t',index=False)
