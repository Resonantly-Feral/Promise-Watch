"""Pass 2 marks on the scorecard: W only when an issue names the case."""

import copy
import json
from pathlib import Path

from promisewatch.site import pass2

RUNS = Path(__file__).resolve().parents[1] / "data" / "runs"


def test_run_001_is_w_for_both_cases():
    # p2 is rejected ("promise p2") and the link p1 -> p2 is dropped ("link 1").
    assert pass2(RUNS / "claude-haiku-5-5-001.json")["marks"] == {"printer": "W", "customer": "W"}


def test_run_002_is_r_for_both_cases():
    assert pass2(RUNS / "claude-haiku-5-5-002.json")["marks"] == {"printer": "R", "customer": "R"}


def test_an_unrelated_issue_does_not_make_a_wrong_case_w(tmp_path):
    saved = json.loads((RUNS / "claude-haiku-5-5-002.json").read_text())
    d = copy.deepcopy(saved["drafts"])
    customer = next(p["id"] for p in d["promises"] if p["promisee"] == "Syarikat Hijau")
    d["promises"] = [p for p in d["promises"] if p["id"] != customer]  # silently missing
    d["links"] = []
    d["statements"].append({"kind": "remark", "source_id": "chat_cetak_jaya:99", "about": [],
                            "date": None, "name": None, "question": None, "cost": None})
    run = tmp_path / "silent.json"
    run.write_text(json.dumps({**saved, "drafts": d}))
    result = pass2(run)
    assert result["issues"]  # an issue exists, but it names neither case
    assert result["marks"] == {"printer": "X", "customer": "X"}
