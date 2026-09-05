# Synthetic channel-hit eligibility benchmark

The adopted set-based query reduced the warm median for choosing one hit from
400 candidates from **4,069 ms to 15.1 ms** on the same isolated fixture, about
**270× faster**. Revalidating one candidate fell from **56.2 ms to 10.3 ms**.
These are synthetic PostgreSQL execution measurements, not production latency
or a user-growth result.

## Fixture and method

- PostgreSQL 16.14, aarch64 Linux in a task-owned Docker container, on an ARM64 Mac.
- 250,000 memes: 225,000 canonical rows and 25,000 duplicate aliases, including
  two-hop families. The 400 candidate roots reached 490 family rows.
- 402,000 recorded reactions, 10,100 crossposts, two language preferences and
  two currently verified nonmember cache rows. All records are synthetic.
- Existing primary keys and representative lookup indexes, including the new
  `ix_meme_duplicate_of`; database size approximately 129 MB.
- `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`, four executions per query shape.
  Medians below exclude the first execution. `LIMIT 1` for latency measurements;
  complete result lists for equivalence checks.

| Query | Warm median | Warm samples |
| --- | ---: | --- |
| Original, 400 candidates | 4,069.23 ms | 4,322.49 / 4,069.23 / 3,904.89 ms |
| Set-based, 400 candidates | 15.09 ms | 17.95 / 15.09 / 14.87 ms |
| Original, one candidate | 56.18 ms | 61.49 / 55.44 / 56.18 ms |
| Set-based, one candidate | 10.28 ms | 10.67 / 10.28 / 9.86 ms |

## Root cause and index evidence

The original correlated membership/publication check scanned 10,100 crossposts
**396 times**. Its repeated hash-join node consumed approximately 9.689 ms per
loop. The rewrite materializes `seen_roots` and `blocked_roots` once, then uses
anti-joins; the blocked-root computation executes once, around 7.2 ms here.
Original-plan JIT compilation added approximately 45 ms; the rewritten plan did
not trigger JIT compilation in this fixture.

The duplicate index is used: `Index Scan` on `ix_meme_duplicate_of`, 490 probes,
and about 0.7 ms for the recursive family CTE in the initial index comparison.
Without that index PostgreSQL scanned all 250,000 meme rows three times;
the family CTE took about 239 ms. The original whole-query median remained
approximately four seconds with or without the index because the correlated
publication check dominated. The index alone was insufficient.

## Preserved behavior

All **13 full-result comparisons** matched: baseline; current membership;
unknown membership including a duplicate published to the other channel;
missing cache; stale cache; legacy positive history; sticky `ever_member`;
recorded direct alias; recorded two-hop alias; changed publication status;
changed canonical pointer; explicit excluded IDs; repeated pool IDs.
The baseline returned the same 396 eligible candidates.

The prototype was subsequently aligned with the adopted source's explicit UTC
comparison and score-then-recency order. After comment/whitespace normalization
the final prototype and source SQL are identical. The measured fixture used
equal publication timestamps and a UTC database, so these alignment edits do
not change its ranking or eligibility; no new timing claim is made for them.

## Artifacts and limits

- `synthetic-eligibility-benchmark.json`: initial index/no-index comparison.
- `synthetic-eligibility-optimized-benchmark.json`: timing samples, selected plan
  nodes, query hashes and the 13 equivalence results.
- `eligibility-query-optimized.sql`: final reviewed query copy.
- `eligibility-query-benchmark.py`: reproducible synthetic fixture and checks.
  It reads the current source as its comparison query; after adoption, both
  queries naturally represent the optimized implementation. The retained JSON
  records the original measured query hashes and baseline timings.

The fixture does not reproduce production concurrency, distribution skew,
cache pressure or network latency. Both task-owned tmpfs database containers
were removed, including all generated database data. No production database,
Telegram API, or private records were used.

Membership repair remains every 24 hours with a 24-hour freshness requirement.
Request duration, the worker interval and a backlog can create short gaps where
a cache record is too old. The hit slot then skips safely and normal feed
delivery continues; it never treats stale or failed checks as nonmembership.
