"""Pass 1, rules only: the Risk Test Set run on hand-written records.

Expected results come from the test set and CLAUDE.md, plus Resonantly-Feral's
rulings of 10/10/2026:
- Options are asserted only where the test set states them (P13, P18).
- Overdue unverified shows only "Did this happen?", no options.
- P15 stops on both orders, no level on either.
- P17b expects no anomaly flag.
- P03/P23: the earlier order carried tracking only.
- P14 takes the stop route: "Which Raya?".
- A stopped record is Open with the level withheld.
- P16 has no promise record, only the outside-bundle flag.
- The customer promise is asserted only where its deadline is given.
"""

from decimal import Decimal

import pytest

from promisewatch.model import (
    BROKEN_DISPLAY,
    LOW_DISPLAY,
    OVERDUE_QUESTION,
    OVERDUE_REASON,
    Direction,
    FlagKind,
    Level,
    OptionKind,
    Signal,
    Status,
)
from promisewatch.rules import evaluate
from tests import fixtures as fx
from tests.fixtures import day

S1, S2, S3, S4, S5, D = Signal.S1, Signal.S2, Signal.S3, Signal.S4, Signal.S5, Signal.D


def assess(bundle, promise_id="printer"):
    return evaluate(bundle).assessments[promise_id]


def codes(a):
    return {r.code for r in a.reasons}


def assert_scored(a, status, level, signals):
    """Status, level, exact signals, and a reason for every signal (rule 13)."""
    assert a.status is status
    assert a.level is level
    assert a.signals == frozenset(signals)
    for s in signals:
        assert s.name in codes(a), f"no reason given for {s.name}"
    if level is Level.LOW:
        assert a.display == LOW_DISPLAY
    else:
        assert a.reasons, "a level above LOW needs reasons"
    assert a.stop is None


def assert_stopped(a, question):
    """Rule 17: Open with the level withheld, one question, no options."""
    assert a.status is Status.OPEN
    assert a.level is None
    assert a.stop is not None
    assert a.stop.question == question
    assert a.stop.unclear
    assert a.options == ()


def assert_overdue(a):
    """Ruling F: Overdue unverified, HIGH, one question, no options."""
    assert a.status is Status.OVERDUE_UNVERIFIED
    assert a.level is Level.HIGH
    assert any(r.code == "OVERDUE" and r.text == OVERDUE_REASON for r in a.reasons)
    assert a.question == OVERDUE_QUESTION
    assert a.options == ()


def flags_of(result, kind):
    return [f for f in result.flags if f.kind is kind]


def near_reason(a):
    return next(r for r in a.reasons if r.code == "S3")


# ------------------------------------------------- statuses and evidence


def test_p01_clean_far_away():
    result = evaluate(fx.p01())
    a = result.assessments["printer"]
    assert_scored(a, Status.OPEN, Level.LOW, [])
    # Ruling Z: missing by channel is listed even far from the deadline.
    missing = flags_of(result, FlagKind.MISSING_BY_CHANNEL)
    assert {f.text.split(":")[0] for f in missing} == {
        "No signed delivery note",
        "No tracking",
    }


def test_p02_kept_near_with_dependent():
    a = assess(fx.p02())
    assert a.status is Status.KEPT
    assert a.level is None
    assert a.fulfilment_evidence == ("d1",)


def test_p03_claim_on_channel_that_sends_proof():
    a = assess(fx.p03())
    assert_scored(a, Status.OPEN, Level.MEDIUM, [S2, S3])
    assert "m2" in a.recorded  # the claim is recorded as a Message
    assert a.fulfilment_evidence == ()
    assert "7-day window" in near_reason(a).text


def test_p04_claim_on_channel_that_never_sends_proof():
    result = evaluate(fx.p04())
    a = result.assessments["printer"]
    assert_scored(a, Status.OPEN, Level.LOW, [S3])
    assert "m2" in a.recorded
    missing = flags_of(result, FlagKind.MISSING_BY_CHANNEL)
    assert any("tracking" in f.text and "printer" in f.about for f in missing)


def test_p05_owner_says_its_fine():
    a = assess(fx.p05())
    assert_scored(a, Status.OPEN, Level.MEDIUM, [S2, S3])
    assert "o1" in a.recorded  # Owner-said: recorded, changes nothing


def test_p06_missing_proof_with_dependent():
    a = assess(fx.p06())
    assert_scored(a, Status.OPEN, Level.HIGH, [S2, S3, D])
    # Customer deadline not given in the test set: customer unasserted.


def test_p07_near_with_dependent_no_other_signal():
    a = assess(fx.p07())
    assert_scored(a, Status.OPEN, Level.MEDIUM, [S3, D])
    # Customer deadline not given in the test set: customer unasserted.


# ------------------------------------------------ revisions and conflicts


def assert_revised_proposed(a, forecast):
    assert a.status is Status.REVISED
    assert a.by_when.original == day(13, 11)
    assert a.by_when.agreed == day(13, 11)
    assert a.by_when.forecast == forecast
    assert a.by_when.acceptance_evidenced is False
    assert [r.date for r in a.by_when.revisions] == [forecast]
    assert [r.source_id for r in a.by_when.revisions] == ["m2"]


def test_p08_revised_still_in_time():
    result = evaluate(fx.p08())
    a = result.assessments["printer"]
    assert_revised_proposed(a, day(20, 11))
    assert_scored(a, Status.REVISED, Level.MEDIUM, [D])
    assert "REVISION" in codes(a)
    c = result.assessments["customer"]
    assert_scored(c, Status.OPEN, Level.LOW, [])


def test_p09_revised_past_customer_deadline():
    result = evaluate(fx.p09())
    a = result.assessments["printer"]
    assert_revised_proposed(a, day(28, 11))
    assert_scored(a, Status.REVISED, Level.HIGH, [S1, D])
    s1 = next(r for r in a.reasons if r.code == "S1")
    assert "28/11" in s1.text and "27/11" in s1.text
    assert "customer" in s1.refs
    c = result.assessments["customer"]
    assert_scored(c, Status.OPEN, Level.HIGH, [S5])


def test_p10_link_only_proposed():
    result = evaluate(fx.p10())
    a = result.assessments["printer"]
    assert_revised_proposed(a, day(28, 11))
    assert_scored(a, Status.REVISED, Level.MEDIUM, [])
    assert "REVISION" in codes(a)
    assert [l.confirmed for l in result.links] == [False]  # shown grey
    c = result.assessments["customer"]
    assert_scored(c, Status.OPEN, Level.LOW, [])  # no risk passed downstream


def test_p11_third_party_says_late():
    result = evaluate(fx.p11())
    a = result.assessments["printer"]
    assert_scored(a, Status.OPEN, Level.MEDIUM, [S4])
    assert a.by_when.agreed == day(13, 11)
    assert a.by_when.forecast is None
    assert a.by_when.revisions == ()
    conflicts = flags_of(result, FlagKind.CONFLICT)
    assert any("m2" in f.source_ids for f in conflicts)


# ------------------------------------------------------------------ breaks


def test_p12_deadline_passed():
    assert_overdue(assess(fx.p12()))


def test_p13_refusal_before_deadline():
    a = assess(fx.p13())
    assert a.status is Status.BROKEN
    assert a.level is None
    assert a.display == BROKEN_DISPLAY
    assert "m2" in a.sources  # the refusal is shown
    # Ruling N: no alternative named and no confirmed dependent in P13.
    assert [o.kind for o in a.options] == [
        OptionKind.FIND_ANOTHER_WAY,
        OptionKind.ACCEPT_FAILURE,
    ]
    assert "cost not stated" in a.options[0].text
    assert all(o.cost is None for o in a.options)  # no cost stated in the bundle
    assert a.if_nobody_acts == (
        "The gift bags from Cetak Jaya will not arrive, and nothing replaces them."
    )


# ----------------------------------------------------------- unclear input


def test_p14_vague_date_stops():
    result = evaluate(fx.p14())
    a = result.assessments["payment"]
    assert_stopped(a, "Which Raya?")
    assert a.by_when.unresolved is not None
    assert flags_of(result, FlagKind.UNRESOLVED_DATE)


def test_p15_cannot_tell_which_order():
    result = evaluate(fx.p15())
    for pid in ("bags", "banners"):
        a = result.assessments[pid]
        assert_stopped(a, "Which order is late?")
        assert a.by_when.revisions == ()  # the delay is pinned on neither


def test_p16_points_outside_bundle():
    result = evaluate(fx.p16())
    assert result.assessments == {}  # not a promise
    assert any("m1" in f.source_ids for f in flags_of(result, FlagKind.OUTSIDE_BUNDLE))
    assert result.exposure == ()  # no price carried in


def test_p17_planted_instruction():
    result = evaluate(fx.p17())
    a = result.assessments["payment"]
    assert_scored(a, Status.OPEN, Level.LOW, [])
    assert any("m1" in f.source_ids for f in flags_of(result, FlagKind.ANOMALY))


def test_p17b_polite_claim_of_payment():
    result = evaluate(fx.p17b())
    a = result.assessments["payment"]
    assert_scored(a, Status.OPEN, Level.LOW, [])
    assert "m1" in a.recorded
    assert a.fulfilment_evidence == ()
    assert flags_of(result, FlagKind.ANOMALY) == []  # ordinary request, no alarm


# --------------------------------------------------------------- decisions


def test_p18_options_without_invented_costs():
    result = evaluate(fx.p18())
    a = result.assessments["printer"]
    assert_scored(a, Status.REVISED, Level.HIGH, [S1, D])
    assert [o.kind for o in a.options] == [
        OptionKind.ACCEPT_REVISED_DATE,
        OptionKind.CONTACT_ALTERNATIVE,
        OptionKind.ACCEPT_RISK,
    ]
    backup = a.options[1]
    assert backup.name == "Cetak Murni"
    assert backup.cost is None
    assert "cost not stated" in backup.text
    assert all(o.cost is None for o in a.options)
    assert a.if_nobody_acts
    c = result.assessments["customer"]
    assert_scored(c, Status.OPEN, Level.HIGH, [S5])


# ---------------------------------------------------------- review cases


def test_p19_amount_direction_no_total():
    result = evaluate(fx.p19())
    assert_scored(result.assessments["printer"], Status.REVISED, Level.HIGH, [S1, D])
    assert_scored(result.assessments["customer"], Status.OPEN, Level.HIGH, [S5])
    lines = {(l.promise_id, l.amount_rm, l.direction, l.source_id) for l in result.exposure}
    assert lines == {
        ("printer", Decimal("8400"), Direction.PAYABLE, "d2"),
        ("customer", Decimal("11000"), Direction.RECEIVABLE, "d3"),
    }
    assert len(result.exposure) == 2  # no sum, no net line


def test_p20_confirmed_failure_reaches_dependent():
    result = evaluate(fx.p20())
    a = result.assessments["printer"]
    assert a.status is Status.BROKEN
    assert a.level is None
    assert a.display == BROKEN_DISPLAY
    c = result.assessments["customer"]
    assert_scored(c, Status.OPEN, Level.HIGH, [S5])
    s5 = next(r for r in c.reasons if r.code == "S5")
    assert {"printer", "m2", "link-1"} <= set(s5.refs)


def test_p21_explicit_fulfilment_dispute():
    a = assess(fx.p21())
    assert_scored(a, Status.DISPUTED, Level.MEDIUM, [S4])
    assert {"d1", "m2"} <= set(a.sources)  # both sides shown
    assert a.fulfilment_evidence == ()  # not closed


def test_p22_proof_belongs_to_another_order():
    result = evaluate(fx.p22())
    a = result.assessments["printer"]
    assert_scored(a, Status.OPEN, Level.LOW, [])
    assert a.fulfilment_evidence == ()
    assert any("d1" in f.source_ids for f in flags_of(result, FlagKind.EVIDENCE_MISMATCH))


def test_p23_tracking_is_not_delivery():
    a = assess(fx.p23())
    assert_scored(a, Status.OPEN, Level.LOW, [S3])
    assert a.fulfilment_evidence == ()  # tracking cannot close delivery


def test_p24_proposal_cannot_erase_overdue():
    a = assess(fx.p24())
    assert_overdue(a)
    assert a.by_when.original == day(14, 10)
    assert a.by_when.agreed == day(14, 10)
    assert a.by_when.forecast == day(20, 10)
    assert [r.date for r in a.by_when.revisions] == [day(20, 10)]


# ------------------------------------------------- rulings V and W


def test_ruling_v_day_only_deadline_means_end_of_day():
    # Due "15/10" with no time: at 09:00 that day it has not passed yet.
    b = fx.bundle(
        "V", [fx.msg("m1", fx.CJ, "Bags ready by 15/10.")], promises=(fx.printer(day(15, 10)),)
    )
    a = assess(b)
    assert_scored(a, Status.OPEN, Level.LOW, [S3])


def test_ruling_w_same_day_forecast_is_not_past():
    result = evaluate(fx._revised("W", day(27, 11)))
    a = result.assessments["printer"]
    assert_revised_proposed(a, day(27, 11))
    assert_scored(a, Status.REVISED, Level.MEDIUM, [D])
    assert "REVISION" in codes(a)


# ---------------------------------------------------------- every case


@pytest.mark.parametrize("case", sorted(fx.ALL))
def test_same_input_same_answer(case):
    """Rule 12 / repeatability: two runs on one bundle give the same result."""
    assert evaluate(fx.ALL[case]()) == evaluate(fx.ALL[case]())
