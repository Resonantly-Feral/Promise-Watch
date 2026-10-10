"""Fixes from the spec-checker review of 10/10/2026.

These cases are not in the Risk Test Set. Each one pins a behaviour that
CLAUDE.md decides but the test set does not reach.
"""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from promisewatch.model import (
    MYT,
    Direction,
    FlagKind,
    Level,
    Link,
    Money,
    Signal,
    Status,
)
from promisewatch.rules import evaluate
from tests import fixtures as fx
from tests.fixtures import CJ, ME, SH, day


def flags_of(result, kind):
    return [f for f in result.flags if f.kind is kind]


# ---------------------------------------------------- bug 1: exposure


def test_bug1_exposure_includes_overdue_unverified_and_its_dependents():
    # Overdue unverified is always HIGH, so it is at risk (Exposure section).
    b = fx.bundle(
        "B1",
        [
            fx.msg("m1", CJ, "Will deliver the bags by 14/10."),
            fx.doc("d2", CJ, "Quote: Majlis Events owes Cetak Jaya RM8,400."),
            fx.doc("d3", ME, "Invoice: Syarikat Hijau owes Majlis Events RM11,000."),
            fx.CUSTOMER_SOURCE_27,
        ],
        promises=(
            fx.printer(day(14, 10), value=Money(Decimal("8400"), ME, CJ, "d2")),
            fx.customer(day(27, 11), value=Money(Decimal("11000"), SH, ME, "d3")),
        ),
        links=(fx.link(True),),
    )
    result = evaluate(b)
    assert result.assessments["printer"].status is Status.OVERDUE_UNVERIFIED
    lines = {(l.promise_id, l.amount_rm, l.direction, l.source_id) for l in result.exposure}
    assert lines == {
        ("printer", Decimal("8400"), Direction.PAYABLE, "d2"),
        ("customer", Decimal("11000"), Direction.RECEIVABLE, "d3"),
    }


# ---------------------------------------- bug 2: S4 needs a real conflict


def test_bug2_third_party_repeating_the_agreed_date_is_not_a_conflict():
    b = fx.bundle(
        "B2",
        [
            fx.msg("m1", CJ, "Bags ready by 13/11."),
            fx.msg("m2", SH, "We were told 13/11."),
        ],
        promises=(fx.printer(day(13, 11)),),
        statements=(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=day(13, 11)),
        ),
    )
    result = evaluate(b)
    a = result.assessments["printer"]
    assert Signal.S4 not in a.signals
    assert a.level is Level.LOW
    assert flags_of(result, FlagKind.CONFLICT) == []


def test_bug2_third_party_different_date_still_conflicts():
    # P11 stays as it was: a different date is a conflict.
    a = evaluate(fx.p11()).assessments["printer"]
    assert Signal.S4 in a.signals


# ------------------------------------------ bug 6: links outside the bundle


def test_bug6_link_to_a_promise_outside_the_bundle_is_flagged():
    b = fx.bundle(
        "B6",
        [fx.msg("m1", CJ, "Bags ready by 13/11.")],
        promises=(fx.printer(day(13, 11)),),
        links=(Link("link-x", upstream="printer", downstream="ghost", confirmed=True),),
    )
    result = evaluate(b)
    outside = flags_of(result, FlagKind.OUTSIDE_BUNDLE)
    assert any("link-x" in f.text and "ghost" in f.about for f in outside)
    # Never used: no downstream signal from a promise that isn't here.
    assert Signal.D not in result.assessments["printer"].signals


# ------------------------------------- bug 3: acceptance per revision


def _accept_then_revise(accept_latest=False):
    sources = [
        fx.msg("m1", CJ, "Bags ready by 13/11."),
        fx.msg("m2", CJ, "Sorry boss, 20/11 can?"),
        fx.msg("m3", ME, "OK, 20/11 is fine."),
        fx.CUSTOMER_SOURCE_27,
    ]
    statements = [
        fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=day(20, 11)),
        fx.Statement(fx.StatementKind.ACCEPTANCE, "m3", ("printer",), date=day(20, 11)),
    ]
    if not accept_latest:
        sources.append(fx.msg("m4", CJ, "Sorry boss, 28/11 can?"))
        statements.append(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m4", ("printer",), date=day(28, 11))
        )
    return fx.bundle(
        "B3",
        sources,
        promises=(fx.printer(day(13, 11)), fx.customer(day(27, 11))),
        statements=tuple(statements),
        links=(fx.link(True),),
    )


def test_bug3_acceptance_belongs_to_the_revision_it_names():
    a = evaluate(_accept_then_revise()).assessments["printer"]
    bw = a.by_when
    assert bw.original == day(13, 11)
    assert bw.agreed == day(20, 11)  # the accepted revision
    assert bw.forecast == day(28, 11)  # the newer one, not accepted
    assert bw.acceptance_evidenced is False  # about the latest forecast
    assert [(r.date, r.source_id, r.accepted_by) for r in bw.revisions] == [
        (day(20, 11), "m2", "m3"),
        (day(28, 11), "m4", None),
    ]
    revision = next(r for r in a.reasons if r.code == "REVISION")
    assert "not evidenced" in revision.text
    assert a.level is Level.HIGH  # 28/11 is past the customer's 27/11
    assert fx.OptionKind.ACCEPT_REVISED_DATE in [o.kind for o in a.options]


# --------------------------------- gap 11: "Revised (proposed)" label


def test_gap11_revised_is_labelled_proposed_until_accepted():
    assert evaluate(fx.p08()).assessments["printer"].status_label == "Revised (proposed)"


def test_gap11_accepted_revision_drops_the_proposed_label():
    a = evaluate(_accept_then_revise(accept_latest=True)).assessments["printer"]
    assert a.status is Status.REVISED
    assert a.status_label == "Revised"
    assert a.by_when.agreed == day(20, 11)
    assert a.by_when.acceptance_evidenced is True


# ------------------------------------- bug 4: unclear evidence match


def _bags_300_with_note(note_quantity):
    bags = fx.Outcome(fx.OutcomeKind.GOODS, "gift bags", "CJ-BAGS", quantity=300)
    return fx.bundle(
        "B4",
        [
            fx.msg("m1", CJ, "300 gift bags by 13/11."),
            fx.doc("d1", CJ, "Signed delivery note, gift bags, order CJ-BAGS."),
        ],
        promises=(fx.printer(day(13, 11), outcome=bags),),
        evidence=(
            fx.Evidence(
                fx.EvidenceKind.SIGNED_DELIVERY_NOTE,
                "d1",
                "CJ-BAGS",
                frozenset({CJ, ME}),
                quantity=note_quantity,
                signed=True,
            ),
        ),
    )


def test_bug4_evidence_missing_the_stated_quantity_stops():
    a = evaluate(_bags_300_with_note(None)).assessments["printer"]
    assert a.status is Status.OPEN  # not Kept
    assert a.level is None
    assert a.stop is not None
    assert "300" in a.stop.question
    assert a.options == ()


def test_bug4_evidence_with_a_different_quantity_is_a_mismatch():
    result = evaluate(_bags_300_with_note(250))
    a = result.assessments["printer"]
    assert a.status is Status.OPEN
    assert a.stop is None
    assert a.level is Level.LOW
    assert any("d1" in f.source_ids for f in flags_of(result, FlagKind.EVIDENCE_MISMATCH))


# ----------------------------- bug 5: ambiguous mark-changing statements


def test_bug5_refusal_that_could_mean_two_orders_stops_both():
    b = fx.bundle(
        "B5",
        [
            fx.msg("m1", CJ, "Gift bags ready by 13/11."),
            fx.msg("m2", CJ, "Banners ready by 20/11."),
            fx.msg("m3", CJ, "Sorry boss, cannot do the order, cancel."),
        ],
        promises=(
            fx.printer(day(13, 11), "m1", fx.BAGS, id="bags"),
            fx.printer(day(20, 11), "m2", fx.BANNERS, id="banners"),
        ),
        statements=(
            fx.Statement(
                fx.StatementKind.REFUSAL, "m3", ("bags", "banners"),
                question="Which order is cancelled?",
            ),
        ),
    )
    result = evaluate(b)
    for pid in ("bags", "banners"):
        a = result.assessments[pid]
        assert a.status is Status.OPEN  # not Broken
        assert a.level is None
        assert a.stop.question == "Which order is cancelled?"


# ---------------------------------------- bug 7: vague revision dates


def _vague_revision(with_dependent):
    vague = fx.UnresolvedDate("next week", "Which day next week?")
    return fx.bundle(
        "B7",
        [
            fx.msg("m1", CJ, "Bags ready by 13/11."),
            fx.msg("m2", CJ, "Sorry boss, next week can?"),
            fx.CUSTOMER_SOURCE_27,
        ],
        promises=(fx.printer(day(13, 11)),)
        + ((fx.customer(day(27, 11)),) if with_dependent else ()),
        statements=(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=vague),
        ),
        links=(fx.link(True),) if with_dependent else (),
    )


def test_bug7_vague_revision_with_dependent_is_flagged_and_stops():
    result = evaluate(_vague_revision(with_dependent=True))
    a = result.assessments["printer"]
    assert any("m2" in f.source_ids for f in flags_of(result, FlagKind.UNRESOLVED_DATE))
    assert a.level is None  # S1 can't be checked, so no silent "no S1"
    assert a.stop.question == "Which day next week?"
    assert a.status_label == "Revised (proposed)"


def test_bug7_vague_revision_without_dependent_is_flagged_and_scored():
    result = evaluate(_vague_revision(with_dependent=False))
    a = result.assessments["printer"]
    assert any("m2" in f.source_ids for f in flags_of(result, FlagKind.UNRESOLVED_DATE))
    assert a.stop is None
    assert a.level is Level.MEDIUM  # a revision S1 does not cover


# --------------------------- gap 2: Overdue unverified beats Disputed


def test_gap2_overdue_beats_disputed_and_keeps_the_dispute_in_reasons():
    p21 = fx.p21()
    b = fx.bundle(
        "G2", p21.sources,
        promises=(fx.printer(day(14, 10)),),
        evidence=p21.evidence,
        statements=p21.statements,
    )
    a = evaluate(b).assessments["printer"]
    assert a.status is Status.OVERDUE_UNVERIFIED
    assert a.level is Level.HIGH
    assert a.question == "Did this happen?"
    assert a.options == ()
    assert {r.code for r in a.reasons} == {"OVERDUE", "S4"}
    s4 = next(r for r in a.reasons if r.code == "S4")
    assert {"d1", "m2"} <= set(s4.refs)


# ------------------------- gap 3: a disputed failure is Disputed


def test_gap3_confirmed_failure_that_is_disputed_is_disputed():
    b = fx.bundle(
        "G3",
        [
            fx.msg("m1", CJ, "Bags ready by 13/11."),
            fx.msg("m2", ME, "Confirmed: the bags order failed."),
            fx.msg("m3", CJ, "No boss, we delivered already."),
        ],
        promises=(fx.printer(day(13, 11)),),
        statements=(
            fx.Statement(fx.StatementKind.FAILURE_CONFIRMED, "m2", ("printer",)),
            fx.Statement(fx.StatementKind.FULFILMENT_DISPUTE, "m3", ("printer",)),
        ),
    )
    a = evaluate(b).assessments["printer"]
    assert a.status is Status.DISPUTED
    assert Signal.S4 in a.signals
    assert a.level is Level.MEDIUM
    assert {"m2", "m3"} <= set(a.sources)


# --------------------------------- gap 8: an optional sourced cost


def test_gap8_alternative_with_a_stated_cost_shows_it():
    cost = Money(Decimal("500"), ME, "Cetak Murni", "m3")
    b = fx._revised(
        "G8",
        day(28, 11),
        extra_sources=[fx.msg("m3", CJ, "Can try Cetak Murni as backup, RM500.")],
        extra_statements=[
            fx.Statement(
                fx.StatementKind.ALTERNATIVE_OFFERED, "m3", ("printer",),
                name="Cetak Murni", cost=cost,
            )
        ],
    )
    a = evaluate(b).assessments["printer"]
    backup = next(o for o in a.options if o.kind is fx.OptionKind.CONTACT_ALTERNATIVE)
    assert backup.cost == cost
    assert "RM500" in backup.text and "m3" in backup.text
    assert "not stated" not in backup.text


# ====================== second review, fixes of 10/10/2026 (rules frozen after)


# -------------------------- finding 1: restating the same date is no revision


def test_promisor_restating_the_agreed_date_is_not_a_revision():
    b = fx.bundle(
        "F1",
        [fx.msg("m1", CJ, "Bags ready by 13/11."), fx.msg("m2", CJ, "Confirm 13/11 boss.")],
        promises=(fx.printer(day(13, 11)),),
        statements=(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=day(13, 11)),
        ),
    )
    a = evaluate(b).assessments["printer"]
    assert a.status is Status.OPEN
    assert a.by_when.revisions == ()
    assert a.level is Level.LOW


def test_promisor_moving_back_to_the_original_date_is_a_revision():
    b = fx.bundle(
        "F1b",
        [
            fx.msg("m1", CJ, "Bags ready by 13/11."),
            fx.msg("m2", CJ, "Sorry boss, 20/11 can?"),
            fx.msg("m3", CJ, "Good news boss, 13/11 can do."),
        ],
        promises=(fx.printer(day(13, 11)),),
        statements=(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=day(20, 11)),
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m3", ("printer",), date=day(13, 11)),
        ),
    )
    a = evaluate(b).assessments["printer"]
    assert [r.source_id for r in a.by_when.revisions] == ["m2", "m3"]
    assert a.by_when.forecast == day(13, 11)


# ------------------ finding 2: only Document or Message evidence can close


def test_owner_said_evidence_cannot_close_a_promise():
    p02 = fx.p02()
    owner_note = fx.Source(
        "d1", fx.SourceType.OWNER_SAID, "I have the signed delivery note, all good.", ME
    )
    sources = [owner_note if s.id == "d1" else s for s in p02.sources]
    b = fx.bundle(
        "F2", sources, promises=p02.promises, evidence=p02.evidence, links=p02.links
    )
    a = evaluate(b).assessments["printer"]
    assert a.status is Status.OPEN  # not Kept
    assert a.fulfilment_evidence == ()
    assert "d1" in a.recorded  # recorded, changes no mark (rule 3)


def test_message_evidence_can_close_a_promise():
    a = evaluate(fx.p23()).assessments["printer"]  # tracking pasted in chat
    assert Signal.S2 not in a.signals  # it counts as progress proof


# --------------------------------------- W: exact times when both stated


def _times(forecast, downstream):
    return fx.bundle(
        "W2",
        [
            fx.msg("m1", CJ, "Bags ready by 19/10."),
            fx.msg("m2", CJ, "Sorry boss, later can?"),
            fx.CUSTOMER_SOURCE,
        ],
        promises=(fx.printer(day(19, 10)), fx.customer(downstream)),
        statements=(
            fx.Statement(fx.StatementKind.DATE_STATEMENT, "m2", ("printer",), date=forecast),
        ),
        links=(fx.link(True),),
    )


def at(d, m, h):
    return datetime(2026, m, d, h, 0, tzinfo=MYT)


def test_w_both_times_stated_later_time_same_day_is_past():
    a = evaluate(_times(at(20, 10, 18), at(20, 10, 12))).assessments["printer"]
    assert Signal.S1 in a.signals


def test_w_day_only_forecast_same_day_as_timed_deadline_is_not_past():
    a = evaluate(_times(day(20, 10), at(20, 10, 12))).assessments["printer"]
    assert Signal.S1 not in a.signals


def test_w_timed_forecast_same_day_as_day_only_deadline_is_not_past():
    a = evaluate(_times(at(20, 10, 18), day(20, 10))).assessments["printer"]
    assert Signal.S1 not in a.signals


# ------------- Q1-Q2: a stopped record keeps its status, level withheld


def _ambiguous_touching(first_deadline, refusal_on_first=False):
    statements = [
        fx.Statement(
            fx.StatementKind.DATE_STATEMENT, "m3", ("bags", "banners"),
            date=day(30, 11), question="Which order moves to 30/11?",
        ),
    ]
    sources = [
        fx.msg("m1", CJ, "Gift bags by the date."),
        fx.msg("m2", CJ, "Banners ready by 20/11."),
        fx.msg("m3", CJ, "Boss, the order 30/11 can?"),
    ]
    if refusal_on_first:
        sources.append(fx.msg("m4", CJ, "Gift bags cannot do, cancel."))
        statements.append(fx.Statement(fx.StatementKind.REFUSAL, "m4", ("bags",)))
    return fx.bundle(
        "Q1",
        sources,
        promises=(
            fx.printer(first_deadline, "m1", fx.BAGS, id="bags"),
            fx.printer(day(20, 11), "m2", fx.BANNERS, id="banners"),
        ),
        statements=tuple(statements),
    )


def test_q1_overdue_candidate_keeps_status_with_level_withheld():
    result = evaluate(_ambiguous_touching(day(14, 10)))
    a = result.assessments["bags"]
    assert a.status is Status.OVERDUE_UNVERIFIED
    assert a.level is None
    assert a.stop.question == "Which order moves to 30/11?"
    assert a.options == ()


def test_q1_broken_candidate_keeps_status_with_options_withheld():
    a = evaluate(_ambiguous_touching(day(13, 11), refusal_on_first=True)).assessments["bags"]
    assert a.status is Status.BROKEN
    assert a.level is None
    assert a.stop is not None
    assert a.options == ()  # rule 17: no options


def test_q2_stopped_revised_record_keeps_revised():
    # bug 7's case: a vague revision with a confirmed dependent stops.
    a = evaluate(_vague_revision(with_dependent=True)).assessments["printer"]
    assert a.status is Status.REVISED
    assert a.level is None


def test_q3_unclear_evidence_after_the_deadline_stays_overdue():
    b = _bags_300_with_note(None)
    late = fx.bundle(
        "Q3", b.sources,
        promises=(replace(b.promises[0], deadline=day(14, 10)),),
        evidence=b.evidence,
    )
    a = evaluate(late).assessments["printer"]
    assert a.status is Status.OVERDUE_UNVERIFIED
    assert a.level is Level.HIGH
    assert a.question == "Did this happen?"


# ------------------------ Q6: a visible note under a stopped upstream


def test_q6_dependent_of_a_stopped_upstream_gets_a_note_and_no_signal():
    a_up = evaluate(_vague_revision(with_dependent=True))
    up = a_up.assessments["printer"]
    c = a_up.assessments["customer"]
    assert up.stop is not None
    assert Signal.S5 not in c.signals  # no new signal
    assert any(
        "Cetak Jaya" in n and up.stop.question in n for n in c.notes
    ), c.notes
