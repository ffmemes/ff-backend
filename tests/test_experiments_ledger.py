"""experiments/*.md parse and experiments/README.md matches `scripts/experiments.py index`."""

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "experiments_cli", ROOT / "scripts" / "experiments.py"
)
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def test_every_experiment_file_is_valid():
    exps = ledger.load()
    assert exps
    ids = [e["id"] for e in exps]
    assert len(ids) == len(set(ids)), "duplicate experiment id"
    for e in exps:
        name = e["file"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$", name), name
        assert set(ledger.KEYS) <= set(e), f"{name}: missing {set(ledger.KEYS) - set(e)}"
        assert e["status"] in ledger.STATUSES, f"{name}: status {e['status']!r}"
        for key in ("id", "hypothesis", "primary_metric", "result"):
            assert e[key], f"{name}: empty {key}"
        for key in ("started", "check_on", "decided"):
            assert not e[key] or DATE.match(e[key]), f"{name}: {key} {e[key]!r}"
        if e["status"] not in ledger.OPEN:
            assert e["decided"], f"{name}: decided experiment needs a decided date"


def test_readme_is_up_to_date():
    assert ledger.README.read_text(encoding="utf-8") == ledger.render(ledger.load()), (
        "experiments/README.md is stale: run `python scripts/experiments.py index`"
    )
