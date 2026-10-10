"""Demo bundle (data/): capture, validation, and Pass 1 through the comparison.

Pass 1 here means hand-written draft records for the demo bundle go through
validation, the rules and every EXPECTED.md check, with no AI. It proves the
pipeline and the comparison are right before a live model run. It is not a
Pass 2 result: Pass 2 is `python -m promisewatch.pipeline.run` with a model.
"""

import copy
from pathlib import Path

import pytest

from promisewatch.model import Status
from promisewatch.pipeline.build import build
from promisewatch.pipeline.capture import capture
from promisewatch.pipeline.compare import compare
from promisewatch.rules import evaluate

BUNDLE = Path(__file__).resolve().parents[1] / "data" / "bundle.toml"

# Hand-written by reading the five files in data/ (Pass 1 for the demo bundle).
DEMO_DRAFTS = {
    "promises": [
        {
            "id": "p1", "promisor": "Cetak Jaya", "promisee": "Majlis Events",
            "outcome_kind": "goods", "description": "300 gift bags", "order_ref": "CJ-2611",
            "quantity": 300,
            "deadline": {"date": "13/11/2026", "time": None, "vague_text": None,
                         "question": None, "reasoning": "'13 Nov' in a 01/10/2026 chat; the "
                         "quotation states 13/11/2026"},
            "source_id": "chat_cetak_jaya:2",
            "supporting_source_ids": ["CJ-Q-0217_quotation:6", "CJ-Q-0217_quotation:10",
                                      "CJ-Q-0217_quotation:14"],
            "conditions": None,
            "value": {"amount_rm": "8400.00", "payer": "Majlis Events",
                      "payee": "Cetak Jaya", "source_id": "CJ-Q-0217_quotation:12"},
        },
        {
            "id": "p2", "promisor": "Majlis Events", "promisee": "Syarikat Hijau",
            "outcome_kind": "goods", "description": "300 gift bags", "order_ref": "ME-INV-0311",
            "quantity": 300,
            "deadline": {"date": "27/11/2026", "time": None, "vague_text": None,
                         "question": None, "reasoning": "'27 Nov' in a 02/10/2026 chat; the "
                         "invoice states 27/11/2026"},
            "source_id": "chat_syarikat_hijau:2",
            "supporting_source_ids": ["ME-INV-0311_invoice:9", "ME-INV-0311_invoice:13"],
            "conditions": None,
            "value": {"amount_rm": "11000.00", "payer": "Syarikat Hijau",
                      "payee": "Majlis Events", "source_id": "ME-INV-0311_invoice:11"},
        },
    ],
    "statements": [
        {"kind": "date_statement", "source_id": "chat_cetak_jaya:8", "about": ["p1"],
         "date": {"date": "28/11/2026", "time": None, "vague_text": None, "question": None,
                  "reasoning": "'28 Nov' on 14/10/2026, so 2026"},
         "name": None, "question": None, "cost": None},
        {"kind": "alternative_offered", "source_id": "chat_cetak_jaya:9", "about": ["p1"],
         "date": None, "name": "Cetak Murni", "question": None, "cost": None},
        {"kind": "instruction_like", "source_id": "chat_cetak_jaya:10", "about": ["p1"],
         "date": None, "name": None, "question": None, "cost": None},
    ],
    "evidence": [],
    "earlier_fulfilments": [],
    "links": [
        {"upstream": "p1", "downstream": "p2",
         "reason": "The organiser's bags for Syarikat Hijau come from Cetak Jaya's order.",
         "source_ids": ["chat_cetak_jaya:1", "chat_cetak_jaya:3"]},
    ],
}


@pytest.fixture(scope="module")
def cap():
    return capture(BUNDLE)


def drafts():
    return copy.deepcopy(DEMO_DRAFTS)


# ------------------------------------------------------------- capture


def test_capture_reads_every_line_with_its_source_type(cap):
    by_id = cap.by_id
    assert by_id["chat_cetak_jaya:8"].source.text == "28 Nov can?"
    assert by_id["chat_cetak_jaya:8"].source.party == "Cetak Jaya"
    assert by_id["chat_syarikat_hijau:1"].source.party == "Syarikat Hijau"
    assert by_id["chat_syarikat_hijau:1"].speaker == "Puan Aina"
    assert by_id["CJ-Q-0217_quotation:14"].source.type.value == "Document"
    assert by_id["CJ-Q-0217_quotation:14"].channel == "chat_cetak_jaya"  # attached there


def test_capture_turns_the_missing_photo_into_an_outside_bundle_statement(cap):
    assert [(s.kind.value, s.source_id) for s in cap.statements] == [
        ("outside bundle", "chat_cetak_jaya:5")
    ]


def test_answer_key_is_never_a_source(cap):
    assert not any("EXPECTED" in l.source.id for l in cap.lines)


# ------------------------------------------- Pass 1 through the comparison


def test_pass1_demo_drafts_pass_every_expected_check(cap):
    checks = compare(cap, drafts())
    failed = [f"{c.stage}: {c.name} -- {c.detail}" for c in checks if not c.ok]
    assert not failed, "\n".join(failed)


# ----------------------------------------------------------- validation


def issues_for(cap, d):
    return [(i.item, i.check) for i in build(cap, d).issues]


def test_evidence_from_the_injected_line_is_rejected(cap):
    d = drafts()
    d["evidence"].append({
        "kind": "signed_delivery_note", "source_id": "chat_cetak_jaya:10",
        "order_ref": "CJ-2611", "parties": ["Cetak Jaya", "Majlis Events"],
        "quantity": 300, "amount_rm": None, "signed": True, "dated": None,
    })
    built = build(cap, d)
    assert ("evidence 1 (signed_delivery_note)", "instruction-like source") in [
        (i.item, i.check) for i in built.issues
    ]
    assert evaluate(built.bundle).assessments["p1"].status is not Status.KEPT


def test_promise_said_by_someone_else_is_rejected(cap):
    d = drafts()
    d["promises"][0]["source_id"] = "chat_cetak_jaya:3"  # Majlis Events said this
    assert ("promise p1", "not the promisor") in issues_for(cap, d)


def test_amount_not_in_its_source_is_rejected(cap):
    d = drafts()
    d["promises"][0]["value"]["amount_rm"] = "9000.00"
    assert ("promise p1", "figure not in source") in issues_for(cap, d)


def test_date_not_in_its_source_is_rejected(cap):
    d = drafts()
    d["statements"][0]["date"]["date"] = "29/11/2026"
    assert ("statement 1 (date_statement)", "date not in source") in issues_for(cap, d)


def test_missing_photo_cannot_be_a_source(cap):
    d = drafts()
    d["promises"][0]["supporting_source_ids"].append("chat_cetak_jaya:5")
    assert ("promise p1", "not provided") in issues_for(cap, d)


def test_unknown_source_is_rejected(cap):
    d = drafts()
    d["statements"][1]["source_id"] = "chat_cetak_jaya:99"
    assert ("statement 2 (alternative_offered)", "unknown source") in issues_for(cap, d)


def test_links_enter_grey_and_only_a_human_confirms(cap):
    assert [l.confirmed for l in build(cap, drafts()).bundle.links] == [False]
    confirmed = build(cap, drafts(), confirmed={("p1", "p2")}).bundle.links
    assert [l.confirmed for l in confirmed] == [True]


# ------------------------------------------- sentinels only mean missing

EMPTY_DATE = {"date": "", "time": "", "vague_text": "", "question": "", "reasoning": ""}
EMPTY_MONEY = {"amount_rm": "", "payer": "", "payee": "", "source_id": ""}


def as_model_writes_it(d: dict) -> dict:
    """The demo drafts with every None written as its sentinel, as the
    union-free schema makes the model return them."""
    def text(obj, keys):
        for k in keys:
            if obj[k] is None:
                obj[k] = ""

    for p in d["promises"]:
        text(p, ["conditions"])
        text(p["deadline"], ["date", "time", "vague_text", "question"])
        p["quantity"] = p["quantity"] or 0
        p["value"] = p["value"] or dict(EMPTY_MONEY)
    for s in d["statements"]:
        text(s, ["name", "question"])
        if s["date"]:
            text(s["date"], ["date", "time", "vague_text", "question"])
        s["date"] = s["date"] or dict(EMPTY_DATE)
        s["cost"] = s["cost"] or dict(EMPTY_MONEY)
    return d


def test_extract_turns_sentinels_back_into_none():
    from promisewatch.pipeline.extract import sentinels_to_none

    d = as_model_writes_it(drafts())
    d["promises"][1]["quantity"] = 0
    d["promises"][1]["value"] = dict(EMPTY_MONEY)
    d = sentinels_to_none(d)
    assert d["promises"][0]["deadline"]["time"] is None
    assert d["promises"][0]["conditions"] is None
    assert d["promises"][1]["quantity"] is None
    assert d["promises"][1]["value"] is None
    assert d["statements"][1]["date"] is None and d["statements"][1]["cost"] is None
    assert d["statements"][0]["date"]["date"] == "28/11/2026"
    assert d["statements"][1]["name"] == "Cetak Murni"


def test_sentinel_drafts_score_exactly_like_none_drafts(cap):
    from promisewatch.pipeline.extract import sentinels_to_none

    def view(d):
        r = evaluate(build(cap, d, confirmed={("p1", "p2")}).bundle)
        return {k: (a.status_label, a.display, a.signals,
                    [o.text for o in a.options]) for k, a in r.assessments.items()}

    converted = sentinels_to_none(as_model_writes_it(drafts()))
    assert issues_for(cap, converted) == []
    assert view(converted) == view(drafts())
    assert compare(cap, converted) == compare(cap, drafts())


def test_validate_treats_a_stray_blank_like_missing(cap):
    d = drafts()
    d["promises"][0]["conditions"] = ""
    d["statements"][0]["question"] = ""
    built = build(cap, d)
    assert built.bundle.promises[0].conditions is None
    assert all(s.question is None for s in built.bundle.statements)


def test_a_half_filled_amount_is_not_a_sentinel_and_is_rejected(cap):
    from promisewatch.pipeline.extract import sentinels_to_none

    d = as_model_writes_it(drafts())
    d["promises"][0]["value"]["amount_rm"] = ""  # payer, payee, source still filled
    d = sentinels_to_none(d)
    assert d["promises"][0]["value"] is not None
    assert ("promise p1", "incomplete amount") in issues_for(cap, d)


def test_a_real_value_is_still_checked_against_its_source(cap):
    from promisewatch.pipeline.extract import sentinels_to_none

    d = as_model_writes_it(drafts())
    d["promises"][0]["quantity"] = 299
    assert ("promise p1", "figure not in source") in issues_for(cap, sentinels_to_none(d))


def test_schema_has_no_union_fields():
    from promisewatch.pipeline.extract import SCHEMA

    def unions(x):
        if isinstance(x, dict):
            return ("anyOf" in x) + isinstance(x.get("type"), list) + sum(
                unions(v) for v in x.values())
        if isinstance(x, list):
            return sum(unions(v) for v in x)
        return 0

    assert unions(SCHEMA) == 0


def test_run_001_now_diverges_at_extract_where_it_started(cap):
    """Run 001 cited no line stating p2's 300; the comparison must catch it
    at Extract, not only when Validate rejects the record."""
    import json

    from promisewatch.pipeline.compare import first_divergence

    run = BUNDLE.parent / "runs" / "claude-haiku-5-5-001.json"
    checks = compare(cap, json.loads(run.read_text())["drafts"])
    failed = [c.name for c in checks if not c.ok and c.stage == "Extract"]
    assert failed == ["customer: 300 and 27/11 are written in its cited lines (rule 8)"]
    assert first_divergence(checks) == "Extract"
