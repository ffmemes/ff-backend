import csv, math, random, collections, sys
rows = list(csv.DictReader(open('posts_raw.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE))
hdr = list(rows[0].keys()); assert all(None not in r for r in rows), 'ragged row'
for r in rows:
    for k, v in r.items():
        if v == 'None': r[k] = ''
n0 = len(rows)
rows = [r for r in rows if float(r['post_age_d']) >= 7 and r['forwards'] != '']
g = collections.defaultdict(list)
for r in rows:
    r['lf'] = math.log1p(int(r['forwards'])); g[(r['ch'], r['iso_week'])].append(r)
for (ch, wk), rs in g.items():
    mu = sum(r['lf'] for r in rs) / len(rs)
    zs = sorted(r['lf'] - mu for r in rs)
    q75 = zs[min(len(zs) - 1, math.ceil(0.75 * len(zs)) - 1)]  # value at 75th pct; hit = zf >= it and > 0 spread
    for r in rs:
        r['week_n'] = len(rs); r['zf'] = round(r['lf'] - mu, 4)
        r['hit'] = int(r['lf'] - mu >= q75 and zs[-1] > zs[0])
out = hdr[:10] + ['zf', 'hit', 'week_n'] + hdr[10:]
with open('posts.tsv', 'w') as f:
    w = csv.DictWriter(f, out, delimiter='\t', extrasaction='ignore', lineterminator='\n'); w.writeheader(); w.writerows(rows)
ru = [r['meme_id'] for r in rows if r['ch'] == 'ru']; en = [r['meme_id'] for r in rows if r['ch'] == 'en']
print('raw', n0, 'mature ru', len(ru), 'en', len(en), 'dup meme ids ru', len(ru) - len(set(ru)))
print('hit rate ru', sum(r['hit'] for r in rows if r['ch']=='ru')/len(ru), 'en', sum(r['hit'] for r in rows if r['ch']=='en')/len(en))
print('weeks', len(g), 'min week n', min(len(v) for v in g.values()))
print('range', min(r['posted_at_utc'] for r in rows), max(r['posted_at_utc'] for r in rows))
for ch in ('ru', 'en'):
    rs = [r for r in rows if r['ch'] == ch]
    print(ch, 'no_dl', sum(r['dl_nlikes'] == '' for r in rs), 'no_meme_stats', sum(r['ms_nlikes'] == '' for r in rs),
          'no_ocr', sum(r['ocr_text'] == '' for r in rs), 'no_desc', sum(r['ocr_description'] == '' for r in rs), 'no_views', sum(r['views'] in ('', '0') for r in rs))
import os; os.makedirs('batches', exist_ok=True)
rnd = random.Random(20261030)
ru_s = list(dict.fromkeys(ru)); rnd.shuffle(ru_s)
en_s = list(dict.fromkeys(en)); rnd.shuffle(en_s)
for pre, ids in (('batch', ru_s), ('en_batch', en_s)):
    for i in range(0, len(ids), 90):
        open(f'batches/{pre}_{i//90+1:02d}.txt', 'w').write('\n'.join(ids[i:i+90]) + '\n')
open('batches/overlap.txt', 'w').write('\n'.join(rnd.sample(ru_s, 60)) + '\n')
open('meme_ids_all.txt', 'w').write('\n'.join(dict.fromkeys(ru + en)) + '\n')
