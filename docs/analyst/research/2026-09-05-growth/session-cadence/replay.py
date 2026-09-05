import os,asyncio,json,statistics
from collections import defaultdict,deque,Counter
from datetime import datetime,timedelta
import asyncpg
from sqlalchemy.engine import make_url
SQL="WITH base AS (\n SELECT r.user_id,r.meme_id,r.sent_at AS event_at,r.recommended_by\n FROM user_meme_reaction r JOIN experiment_assignment e ON e.user_id=r.user_id AND e.experiment_id='channel_hits_v1'\n JOIN \"user\" u ON u.id=r.user_id\n WHERE r.sent_at >= $1::timestamp-interval '1 day' AND r.sent_at < $2::timestamp\n AND u.type='user' AND r.recommended_by IS NOT NULL\n AND r.recommended_by NOT IN('uploaded_meme','low_sent_pool','friend_challenge','share_link','last')\n AND r.recommended_by NOT LIKE 'broadcast%' AND r.recommended_by NOT LIKE 'friend_challenge%'\n), gaps AS (\n SELECT *,lag(event_at) OVER(PARTITION BY user_id ORDER BY event_at,meme_id) AS previous_at FROM base\n), assigned AS (\n SELECT *,sum(CASE WHEN previous_at IS NULL OR event_at-previous_at>interval '30 minutes' THEN 1 ELSE 0 END)\n OVER(PARTITION BY user_id ORDER BY event_at,meme_id) AS session_id FROM gaps\n)\nSELECT user_id,session_id,min(event_at) AS start_at,max(event_at) AS end_at,count(*) AS deliveries,\n count(*) FILTER(WHERE recommended_by='direct') AS direct_deliveries\nFROM assigned GROUP BY user_id,session_id\nHAVING min(event_at)>=$1 AND min(event_at)<$2 ORDER BY user_id,start_at"
async def main():
 c=await asyncpg.connect(make_url(os.environ["DATABASE_URL"]).set(drivername="postgresql").render_as_string(hide_password=False),timeout=10,server_settings={"timezone":"UTC","default_transaction_read_only":"on","statement_timeout":"45000"},statement_cache_size=0)
 try:
  rows=await c.fetch(SQL,datetime(2026,8,12),datetime(2026,9,5))
  users=defaultdict(list)
  for r in rows:users[r["user_id"]].append(dict(r))
  totals=Counter();counts_by_user=defaultdict(list);first_lengths=[];later_lengths=[];return_hours=[];direct=0
  for sessions in users.values():
   day_counts=Counter()
   rolling={2:deque(),3:deque()}
   accepted=Counter()
   prev_end=None
   for s in sessions:
    ts=s["start_at"];day=ts.date();rank=day_counts[day];day_counts[day]+=1
    direct+=s["direct_deliveries"]
    (first_lengths if rank==0 else later_lengths).append(s["deliveries"])
    if prev_end and rank>0:return_hours.append((ts-prev_end).total_seconds()/3600)
    prev_end=s["end_at"]
    for cap,q in rolling.items():
     while q and ts-q[0]>=timedelta(hours=24):q.popleft()
     if len(q)<cap:q.append(ts);accepted[f"rolling24_cap{cap}"]+=1
   totals["sessions"]+=len(sessions);totals["active_user_days"]+=len(day_counts)
   totals["calendar_cap2"]+=sum(min(v,2) for v in day_counts.values())
   totals["calendar_cap3"]+=sum(min(v,3) for v in day_counts.values())
   for name,value in accepted.items():totals[name]+=value;counts_by_user[name].append(value)
  def quantiles(values):
   return {"min":min(values),"median":statistics.median(values),"p90":sorted(values)[int((len(values)-1)*.9)],"max":max(values)}
  print(json.dumps({"users":len(users),"totals":dict(totals),"first_session_delivery_quantiles":quantiles(first_lengths),"later_session_delivery_quantiles":quantiles(later_lengths),"within_day_return_pause_hours_quantiles":quantiles(return_hours),"direct_deliveries":direct,"per_user_24d_opportunity_quantiles":{k:quantiles(v) for k,v in counts_by_user.items()}},default=str))
 finally:await c.close()
try:asyncio.run(main())
except Exception as exc:print(json.dumps({"error":type(exc).__name__}));raise SystemExit(1)


