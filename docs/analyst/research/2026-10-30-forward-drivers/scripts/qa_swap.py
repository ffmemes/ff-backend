# For each label row: does desc match its own OCR description best, or another row's in the same file?
import pandas as pd, numpy as np, re
import os
D=os.environ.get('DATA_DIR','.'); A=D  # posts.tsv, raw labels, outputs
m=pd.read_csv(f'{A}/qa_alignment.tsv',sep='\t')
stop=set('the a an of to and in is it with on for that this at as by from be are was his her their they he she you your i my me meme text image shows features featuring person man woman caption picture photo screenshot which who about while its into has have joke not but what when one two top bottom panel humorous like'.split())
def toks(s): return {w[:6] for w in re.findall(r'[a-z]{3,}',str(s).lower()) if w not in stop}
out=[]
for f,g in m.groupby('file'):
    g=g.sort_values('line'); ocr={r.meme_id:toks(r.ocr_description) for r in g.itertuples() if isinstance(r.ocr_description,str)}
    for r in g.itertuples():
        dt=toks(r.desc)
        if not dt: continue
        sc={mid:len(dt&t)/len(dt) for mid,t in ocr.items()}
        own=sc.get(r.meme_id,np.nan); best=max(sc,key=sc.get)
        out.append(dict(meme_id=r.meme_id,file=f,line=r.line,own=own,best=best,best_sc=sc[best],
                        mis=(best!=r.meme_id) and sc[best]>=0.3 and sc[best]-(0 if np.isnan(own) else own)>=0.25))
o=pd.DataFrame(out)
chk=o[o.own.notna()]
print(chk.groupby('file').agg(n_checkable=('mis','size'),mis_rate=('mis','mean')).round(3))
# rows whose desc points to another row (incl. rows without own OCR)
print(o.groupby('file').mis.sum())
o.to_csv(f'{A}/qa_swap.tsv',sep='\t',index=False)
lines=o[o.mis].merge(m[['meme_id','desc']],on='meme_id')
for x in lines.itertuples(): print(x.file,x.line,x.meme_id,'->',x.best,round(x.own,2),round(x.best_sc,2),x.desc[:70])
