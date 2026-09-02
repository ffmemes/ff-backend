# Database Connection Pool Exhaustion — 2026-04-01

Status: resolved; prevention guidance retained from issue FFM-187

## Impact

Scheduled analytics and recommendation work competed for the same database
connections. Once the pool was saturated, retries amplified the contention and
made otherwise healthy queries appear unavailable.

## Root Cause

This was a workload-coordination problem, not simply a pool-size problem:

- Several scheduled flows overlapped.
- A statistics flow performed broad table scans while recommendation work was
  issuing multiple candidate queries concurrently.
- Retry behavior added more connection attempts while the database was already
  constrained.
- There was no useful visibility into connection ownership, wait time, or the
  number of active queries per flow.

Increasing the pool alone would have moved the bottleneck and increased the
database's concurrent work. The durable fix is to bound and coordinate demand.

## Prevention

1. Stagger high-cost scheduled flows and give each an explicit concurrency cap.
2. Keep full-table statistics work outside peak recommendation windows.
3. Bound per-request query fan-out; do not hold a connection while waiting on
   unrelated network or application work.
4. Configure acquisition timeouts and bounded exponential backoff. A timeout
   must reduce pressure, not trigger an immediate retry storm.
5. Monitor checked-out connections, acquisition wait time, query duration,
   flow identity, and database active/waiting sessions.
6. Alert before saturation is complete so an operator can pause non-critical
   flows while the product remains available.
7. Consider a transaction-pooling proxy only after transaction boundaries and
   session-state assumptions have been verified.

## Verification Checklist

- Recommendation traffic remains healthy while each scheduled flow runs.
- Two expensive flows cannot start concurrently unless explicitly allowed.
- A simulated exhausted pool produces bounded failures and recovery, not an
  unbounded retry loop.
- Dashboards identify which workload owns connections during contention.
- Runbooks name the non-critical flows that are safe to pause first.

## Lesson

Connection pools are admission-control boundaries. Treat pool exhaustion as a
signal to reduce or reschedule demand before increasing capacity.
