"""Experiment ledger CLI. One file per experiment in experiments/, front matter on top.

python scripts/experiments.py list [--status running]
python scripts/experiments.py due
python scripts/experiments.py index        # regenerates experiments/README.md
python scripts/experiments.py readout <id>
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "experiments"
README = DIR / "README.md"
KEYS = (
    "id status hypothesis primary_metric guardrails unit variants started "
    "check_on decided result learning code readout"
).split()
STATUSES = ("proposed", "running", "shipped", "killed", "inconclusive")
OPEN = ("proposed", "running")


def parse(path: Path) -> dict:
    """Flat `key: value` front matter between the first two `---` lines."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path.name}: no front matter")
    meta = {}
    for line in lines[1:]:
        if line.strip() == "---":
            meta["file"] = path.name
            return meta
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{path.name}: bad front matter line {line!r}")
        meta[key.strip()] = value.strip()
    raise ValueError(f"{path.name}: front matter not closed")


def load() -> list[dict]:
    return [parse(p) for p in sorted(DIR.glob("*.md")) if p != README]


def _row(cells) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |"


def _table(header, rows) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(r) for r in rows)]


TEMPLATE = """\
---
id: my_experiment_v1
status: proposed
hypothesis: one line, falsifiable
primary_metric: likes per active user per week
guardrails: LR not down >3 pp, block rate, empty queue
unit: user
variants: control:50,treatment:50
started:
check_on: YYYY-MM-DD
decided:
result: unknown
learning:
code: FLAG_NAME, src/path.py
readout: docs/analyst/my-experiment-v1.sql
---

# Experiment: my_experiment_v1

Design, assignment, frozen decision rules, confounds.

## Log
- YYYY-MM-DD: started (deploy sha / PR).
"""

HEADER = f"""\
# Experiments

One file per experiment: `experiments/YYYY-MM-DD-slug.md` (date = when it was
designed or started). Status lives in the front matter, so files never move.
This README is generated: `python scripts/experiments.py index`.
**Read it before designing a new experiment:** the Decided table is everything
we tried and what we now believe.

Growth bar for new experiments: ship only if the funnel gets less leaky
(first tap / first like / reached-5) and/or the k-factor moves (unique non-self
share clicks, new-user invites). Session length and block rate are guardrails.
North star: [`SPEC.md`](../SPEC.md). Growth thesis:
[`docs/growth/virality-loop.md`](../docs/growth/virality-loop.md).

## Add, check, close

1. **Add:** copy the template into `experiments/YYYY-MM-DD-slug.md`, freeze the
   decision rule in the body, commit the readout SQL under `docs/analyst/`.
   Set `status: running` and `started:` when it deploys.
2. **Check:** `python scripts/experiments.py due` lists running experiments
   whose `check_on` has passed; `python scripts/experiments.py readout <id>`
   prints the command to run against `$ANALYST_DATABASE_URL` (read-only).
   Append dated numbers to the file's log.
3. **Close:** set `status` (shipped / killed / inconclusive), `decided`,
   `result` (numbers + CI or n) and `learning` (one line: what we now believe).
   Never delete the file. Readouts stay in `docs/analyst/readouts/`; link them.
4. Run `python scripts/experiments.py index` and commit the README with it.

Front matter is flat `key: value`; lists are comma-separated; unknown is `unknown`.
Status: {" | ".join(STATUSES)}.

```markdown
{TEMPLATE}```
"""


def render(exps: list[dict]) -> str:
    def link(e):
        return f"[{e['id']}]({e['file']})"

    open_ = sorted(
        (e for e in exps if e["status"] in OPEN),
        key=lambda e: (e["check_on"] or "9999", e["id"]),
    )
    done = sorted(
        (e for e in exps if e["status"] not in OPEN),
        key=lambda e: (e["decided"] or e["started"], e["id"]),
        reverse=True,
    )
    out = [HEADER, f"## Open ({len(open_)})", ""]
    out += _table(
        ["check_on", "experiment", "status", "primary metric", "hypothesis"],
        (
            [e["check_on"] or "-", link(e), e["status"], e["primary_metric"], e["hypothesis"]]
            for e in open_
        ),
    )
    out += ["", f"## Decided ({len(done)}, newest first)", ""]
    out += _table(
        ["decided", "experiment", "status", "result", "learning"],
        ([e["decided"] or "-", link(e), e["status"], e["result"], e["learning"]] for e in done),
    )
    return "\n".join(out) + "\n"


def overdue(e: dict, today: str) -> bool:
    return e["status"] == "running" and (not e["check_on"] or e["check_on"] <= today)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("--status", choices=STATUSES)
    sub.add_parser("due")
    sub.add_parser("index")
    sub.add_parser("readout").add_argument("id")
    args = ap.parse_args(argv)
    exps = load()
    today = dt.date.today().isoformat()

    if args.cmd in ("list", "due"):
        rows = exps
        if args.cmd == "due":
            rows = [e for e in exps if overdue(e, today)]
        elif args.status:
            rows = [e for e in exps if e["status"] == args.status]
        for e in rows:
            flag = ""
            if overdue(e, today):
                flag = "OVERDUE" if e["check_on"] else "NO DATE"
            print(
                f"{e['id']:<38} {e['status']:<12} {e['check_on'] or '-':<10} "
                f"{flag:<7} {e['primary_metric'][:40]:<40} {e['result'][:70]}"
            )
    elif args.cmd == "index":
        README.write_text(render(exps), encoding="utf-8")
        print(f"wrote {README.relative_to(DIR.parent)} ({len(exps)} experiments)")
    elif args.cmd == "readout":
        match = [e for e in exps if e["id"] == args.id]
        if not match:
            print(f"no experiment with id {args.id}", file=sys.stderr)
            return 1
        e = match[0]
        print(f"file: experiments/{e['file']}")
        paths = [p.strip() for p in e["readout"].split(",") if p.strip()]
        if not paths:
            print("no readout recorded")
        for p in paths:
            if p.endswith(".sql"):
                print(f'psql "$ANALYST_DATABASE_URL" -f {p}')
            elif p.endswith(".py"):
                print(f"python {p}")
            else:
                print(f"read: {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
