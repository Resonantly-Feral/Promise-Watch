"""The fixed rules. Same bundle in, same result out.

The engine reads draft records and statements, decides status, signals and
risk level, and lists options. It never acts: it returns a result and
changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta

from promisewatch.model import (
    BROKEN_DISPLAY,
    LOW_DISPLAY,
    MYT,
    OVERDUE_QUESTION,
    OVERDUE_REASON,
    Assessment,
    Bundle,
    BundleResult,
    ByWhen,
    Deadline,
    Direction,
    Evidence,
    EvidenceKind,
    ExposureLine,
    Flag,
    FlagKind,
    Level,
    Link,
    Option,
    OptionKind,
    OutcomeKind,
    PromiseDraft,
    Reason,
    Revision,
    Signal,
    SourceType,
    Statement,
    StatementKind,
    Status,
    Stop,
    UnresolvedDate,
)

ACTIVE = (Status.OPEN, Status.REVISED, Status.DISPUTED)

# Statements that can change a mark. If one could refer to more than one
# promise, it is applied to none of them and every candidate stops (Ruling O).
# Claims, remarks, instruction-like and outside-bundle text change no mark
# (rules 2, 3, 4, 18), so they never stop anything.
MARK_CHANGING = (
    StatementKind.DATE_STATEMENT,
    StatementKind.ACCEPTANCE,
    StatementKind.REFUSAL,
    StatementKind.FAILURE_CONFIRMED,
    StatementKind.FULFILMENT_DISPUTE,
)


# ------------------------------------------------------------------ dates


def deadline_end(d: Deadline) -> datetime | None:
    """Ruling V: a day-only deadline means the end of that day, Malaysia time."""
    if isinstance(d, datetime):
        return d
    if isinstance(d, date):
        return datetime.combine(d + timedelta(days=1), time(0), MYT)
    return None


def is_past(forecast: Deadline, deadline: Deadline) -> bool:
    """Rulings W and AK: compare exact times only when both state a time.
    Otherwise compare days, and the same day is not past."""
    if isinstance(forecast, datetime) and isinstance(deadline, datetime):
        return forecast > deadline
    days = []
    for d in (forecast, deadline):
        if isinstance(d, datetime):
            days.append(d.astimezone(MYT).date())
        elif isinstance(d, date):
            days.append(d)
        else:
            return False  # unresolved: handled as a stop, never guessed
    return days[0] > days[1]


def fmt(d: Deadline) -> str:
    if isinstance(d, datetime):
        return d.astimezone(MYT).strftime("%d/%m/%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    if isinstance(d, UnresolvedDate):
        return f'"{d.text}" (unresolved)'
    return "not stated"


def window_label(w: timedelta) -> str:
    if w.seconds == 0 and w.days:
        return f"{w.days}-day"
    return f"{int(w.total_seconds() // 3600)}-hour"


# ------------------------------------------------------------ working state


@dataclass
class Work:
    """Everything worked out for one promise before levels are set."""

    p: PromiseDraft
    by_when: ByWhen
    status: Status
    sources: list[str]
    recorded: list[str]
    closing: list[str]  # source ids of matching outcome evidence
    disputes: list[str] = field(default_factory=list)  # dispute source ids
    notes: list[str] = field(default_factory=list)
    signals: set[Signal] = field(default_factory=set)
    reasons: list[Reason] = field(default_factory=list)
    stop: Stop | None = None
    level: Level | None = None
    window: timedelta = timedelta()
    window_text: str = ""


class Engine:
    def __init__(self, bundle: Bundle):
        self.b = bundle
        self.sources = {s.id: s for s in bundle.sources}
        self.promises = {p.id: p for p in bundle.promises}
        self.flags: list[Flag] = []
        self.confirmed = [
            l for l in bundle.links
            if l.confirmed and l.upstream in self.promises and l.downstream in self.promises
        ]

    def speaker(self, st: Statement) -> str | None:
        return self.sources[st.source_id].party

    def about(self, pid: str, *kinds: StatementKind) -> list[Statement]:
        """Statements about this promise. Ambiguous mark-changing ones are left out."""
        return [
            s for s in self.b.statements
            if pid in s.about and s.kind in kinds
            and not (s.kind in MARK_CHANGING and len(s.about) > 1)
        ]

    def ambiguous(self, pid: str) -> list[Statement]:
        return [
            s for s in self.b.statements
            if pid in s.about and len(s.about) > 1
            and (s.kind is StatementKind.AMBIGUOUS_REFERENCE or s.kind in MARK_CHANGING)
        ]

    # ------------------------------------------------------------- run

    def run(self) -> BundleResult:
        self.flag_untrusted_text()
        self.flag_unmatched_evidence()
        self.flag_outside_links()
        work = {pid: self.base(p) for pid, p in self.promises.items()}
        for p in self.b.promises:
            self.list_missing_by_channel(p)
        self.stop_cycles(work)
        for w in work.values():
            if w.stop is None and w.status in ACTIVE:
                self.signals(w, work)
        self.propagate(work)
        for w in work.values():
            if w.stop is None:
                continue
            for _, d in self.downstream(w.p.id):
                work[d.id].notes.append(
                    f"Upstream: {w.p.promisor}'s promise of {w.p.what.description} is "
                    f"stopped, so no risk is passed on from it. Open question: "
                    f"{w.stop.question}"
                )
        assessments = {pid: self.assess(w, work) for pid, w in work.items()}
        return BundleResult(
            bundle_id=self.b.id,
            assessments=assessments,
            flags=tuple(self.flags),
            exposure=self.exposure(work),
            links=self.b.links,
        )

    # ---------------------------------------------------- bundle-level flags

    def flag_untrusted_text(self):
        """Rules 4 and 18: flag, never obey, never use, never drop."""
        for st in self.b.statements:
            text = self.sources[st.source_id].text
            if st.kind is StatementKind.INSTRUCTION_LIKE:
                self.flags.append(Flag(
                    FlagKind.ANOMALY,
                    f'Instruction-like text, not obeyed: "{text}"',
                    (st.source_id,), st.about,
                ))
            elif st.kind is StatementKind.OUTSIDE_BUNDLE:
                self.flags.append(Flag(
                    FlagKind.OUTSIDE_BUNDLE,
                    f'Points outside this bundle, nothing taken from it: "{text}"',
                    (st.source_id,), st.about,
                ))

    def flag_unmatched_evidence(self):
        """Rule 2 / Ruling H: evidence for an order no promise has is kept and flagged."""
        refs = {p.what.order_ref for p in self.b.promises}
        for ev in self.b.evidence:
            if ev.order_ref not in refs:
                self.flags.append(Flag(
                    FlagKind.EVIDENCE_MISMATCH,
                    f"{ev.kind.value.capitalize()} is for order {ev.order_ref}, "
                    "which matches no promise in this bundle. It closes nothing.",
                    (ev.source_id,),
                ))

    def flag_outside_links(self):
        """Rule 18: a link to a promise not in this bundle is flagged, never used."""
        for l in self.b.links:
            missing = tuple(x for x in (l.upstream, l.downstream) if x not in self.promises)
            if missing:
                self.flags.append(Flag(
                    FlagKind.OUTSIDE_BUNDLE,
                    f"Link {l.id} points to a promise outside this bundle "
                    f"({', '.join(missing)}). Not used.",
                    (), missing,
                ))

    # ------------------------------------------------------ evidence match

    def match(self, ev: Evidence, p: PromiseDraft) -> str:
        """Rule 2: "match", "mismatch", "unclear", or "other" (another order).

        Order, both parties and a signature (for a delivery note) must match.
        A quantity the promise states must match; an amount must match for a
        payment. If the evidence leaves a stated figure out, the match is
        unclear, not assumed.
        """
        if ev.order_ref != p.what.order_ref:
            return "other"
        if self.sources[ev.source_id].type not in (SourceType.DOCUMENT, SourceType.MESSAGE):
            return "untrusted"  # Ruling AL: recorded, changes no mark (rule 3)
        wrong, unclear = [], False
        if not {p.promisor, p.promisee} <= ev.parties:
            wrong.append("parties")
        if ev.kind is EvidenceKind.SIGNED_DELIVERY_NOTE and not ev.signed:
            wrong.append("signature")
        if p.what.quantity is not None:
            if ev.quantity is None:
                unclear = True
            elif ev.quantity != p.what.quantity:
                wrong.append("quantity")
        if p.what.kind is OutcomeKind.PAYMENT and p.value is not None:
            if ev.amount_rm is None:
                unclear = True
            elif ev.amount_rm != p.value.amount_rm:
                wrong.append("amount")
        if wrong:
            self.add_flag_once(Flag(
                FlagKind.EVIDENCE_MISMATCH,
                f"{ev.kind.value.capitalize()} names order {ev.order_ref} but its "
                f"{', '.join(wrong)} do not match. It closes nothing.",
                (ev.source_id,), (p.id,),
            ))
            return "mismatch"
        return "unclear" if unclear else "match"

    def present(self, p: PromiseDraft) -> dict[EvidenceKind, list[str]]:
        """Evidence that counts. Progress proof with an unclear figure still
        shows progress; it can never close the promise anyway."""
        found: dict[EvidenceKind, list[str]] = {}
        for ev in self.b.evidence:
            m = self.match(ev, p)
            if m == "match" or (m == "unclear" and ev.kind is not p.expected_evidence.closes):
                found.setdefault(ev.kind, []).append(ev.source_id)
        return found

    def unclear_closing(self, p: PromiseDraft) -> list[Evidence]:
        return [
            ev for ev in self.b.evidence
            if ev.kind is p.expected_evidence.closes and self.match(ev, p) == "unclear"
        ]

    # -------------------------------------------------------- base record

    def base(self, p: PromiseDraft) -> Work:
        by_when = self.by_when(p)
        sources = [p.source_id] + [r.source_id for r in by_when.revisions]
        recorded = [
            s.source_id
            for s in self.about(p.id, StatementKind.FULFILMENT_CLAIM, StatementKind.REMARK)
        ]
        evidence = self.present(p)
        closing = evidence.get(p.expected_evidence.closes, [])
        recorded += [ev.source_id for ev in self.b.evidence if self.match(ev, p) == "untrusted"]

        refusals = [
            s for s in self.about(p.id, StatementKind.REFUSAL)
            if self.speaker(s) == p.promisor
        ] + [
            s for s in self.about(p.id, StatementKind.FAILURE_CONFIRMED)
            if self.speaker(s) == self.b.user
        ]
        disputes = self.about(p.id, StatementKind.FULFILMENT_DISPUTE)
        end = deadline_end(by_when.agreed)

        # Status precedence:
        # - Broken, unless the failure itself is disputed (Ruling AB: Disputed).
        # - Overdue unverified once the agreed deadline passes with no
        #   uncontested proof; it beats Revised and Disputed (Ruling AA).
        # - Disputed beats Kept. Then Kept, Revised, Open.
        dispute_ids = [s.source_id for s in disputes]
        passed = end is not None and end <= self.b.now
        if refusals and not disputes:
            status = Status.BROKEN
            sources += [s.source_id for s in refusals]
        elif passed and (not closing or disputes):
            status = Status.OVERDUE_UNVERIFIED
            sources += closing + dispute_ids
        elif disputes:
            status = Status.DISPUTED
            sources += closing + [s.source_id for s in refusals] + dispute_ids
        elif closing:
            status = Status.KEPT
            sources += closing
        elif by_when.revisions:
            status = Status.REVISED
        else:
            status = Status.OPEN

        w = Work(p, by_when, status, sources, recorded,
                 closing if status is Status.KEPT else [])
        if disputes:
            w.disputes = closing + dispute_ids
        w.window, w.window_text = self.near_window(p)
        for r in by_when.revisions:
            if isinstance(r.date, UnresolvedDate):
                self.add_flag_once(Flag(
                    FlagKind.UNRESOLVED_DATE,
                    f'Vague revised date not resolved, not guessed: "{r.date.text}"',
                    (r.source_id,), (p.id,),
                ))
        if status in ACTIVE:
            w.stop = self.stop_for(p, by_when)
        else:  # Ruling AI: an ambiguous statement stops settled records too
            w.stop = self.ambiguity_stop(p)
        return w

    def by_when(self, p: PromiseDraft) -> ByWhen:
        """Rule 5 / Ruling J: only the promisor revises; only acceptance agrees."""
        revisions: list[Revision] = []
        agreed = p.deadline
        for s in self.about(p.id, StatementKind.DATE_STATEMENT, StatementKind.ACCEPTANCE):
            if s.kind is StatementKind.DATE_STATEMENT:
                current = revisions[-1].date if revisions else agreed
                restated = s.date == current or (
                    deadline_end(s.date) is not None
                    and deadline_end(s.date) == deadline_end(current)
                )
                if self.speaker(s) == p.promisor and not restated:
                    revisions.append(Revision(s.date, s.source_id))
                continue
            # Acceptance must come from the recipient and name a proposed date.
            if self.speaker(s) != p.promisee or isinstance(s.date, UnresolvedDate):
                continue
            for i in range(len(revisions) - 1, -1, -1):
                if revisions[i].date == s.date and revisions[i].accepted_by is None:
                    revisions[i] = replace(revisions[i], accepted_by=s.source_id)
                    agreed = s.date
                    break
        return ByWhen(
            original=p.deadline,
            agreed=agreed,
            forecast=revisions[-1].date if revisions else None,
            acceptance_evidenced=bool(revisions) and revisions[-1].accepted_by is not None,
            revisions=tuple(revisions),
            unresolved=p.deadline if isinstance(p.deadline, UnresolvedDate) else None,
        )

    def near_window(self, p: PromiseDraft) -> tuple[timedelta, str]:
        for vendor, w in self.b.vendor_windows:
            if vendor == p.promisor:
                return w, f"this vendor's {window_label(w)} window"
        w = self.b.near_window
        return w, f"the default {window_label(w)} window"

    # --------------------------------------------------------------- stops

    def stop_for(self, p: PromiseDraft, by_when: ByWhen) -> Stop | None:
        """Rule 17: too unclear to evaluate."""
        stop = self.ambiguity_stop(p)
        if stop is not None:
            return stop
        return self.unclear_record_stop(p, by_when)

    def ambiguity_stop(self, p: PromiseDraft) -> Stop | None:
        """Ruling O: a statement that could mean several promises stops them all."""
        for s in self.ambiguous(p.id):
            self.add_flag_once(Flag(
                FlagKind.AMBIGUOUS_REFERENCE,
                f'Can\'t tell which promise this means: "{self.sources[s.source_id].text}"',
                (s.source_id,), s.about,
            ))
            return Stop(
                "A message could refer to more than one promise, "
                "so none of them can be scored.",
                s.question or "Which promise does this refer to?",
            )
        return None

    def unclear_record_stop(self, p: PromiseDraft, by_when: ByWhen) -> Stop | None:
        if by_when.unresolved is not None:
            self.add_flag_once(Flag(
                FlagKind.UNRESOLVED_DATE,
                f'Vague date not resolved, not guessed: "{by_when.unresolved.text}"',
                (p.source_id,), (p.id,),
            ))
            return Stop(f'The date "{by_when.unresolved.text}" is unresolved.',
                        by_when.unresolved.question)
        if by_when.agreed is None:
            return Stop("No deadline is stated in this bundle.", "By when was this promised?")
        for ev in self.unclear_closing(p):
            if p.what.kind is OutcomeKind.PAYMENT:
                figure = f"the full RM{p.value.amount_rm:,}"
            else:
                figure = f"all {p.what.quantity} {p.what.description}"
            return Stop(
                f"The {ev.kind.value} ({ev.source_id}) does not state the figure "
                "the promise states, so it can't be matched.",
                f"Does the {ev.kind.value} cover {figure}?",
            )
        if isinstance(by_when.forecast, UnresolvedDate) and self.downstream(p.id):
            return Stop(
                f'The revised date "{by_when.forecast.text}" is unresolved, so it '
                "can't be checked against the promise that depends on it.",
                by_when.forecast.question,
            )
        return None

    def add_flag_once(self, flag: Flag):
        if flag not in self.flags:
            self.flags.append(flag)

    def stop_cycles(self, work: dict[str, Work]):
        """S5: stop if a dependency cycle prevents evaluation."""
        graph: dict[str, list[str]] = {}
        for l in self.confirmed:
            graph.setdefault(l.upstream, []).append(l.downstream)

        def reaches(start, target, seen):
            for nxt in graph.get(start, []):
                if nxt == target or (nxt not in seen and reaches(nxt, target, seen | {nxt})):
                    return True
            return False

        for pid, w in work.items():
            if reaches(pid, pid, {pid}):
                w.stop = Stop("Confirmed links form a cycle, so risk can't be traced.",
                              "Which of these promises really comes first?")

    # ------------------------------------------------------------- signals

    def downstream(self, pid: str) -> list[tuple[Link, PromiseDraft]]:
        return [(l, self.promises[l.downstream]) for l in self.confirmed
                if l.upstream == pid and l.downstream in self.promises]

    def signals(self, w: Work, work: dict[str, Work]):
        p, now = w.p, self.b.now
        end = deadline_end(w.by_when.agreed)
        near = end is not None and now < end <= now + w.window

        # S1: the latest promisor forecast moves fulfilment past a confirmed
        # downstream deadline (Ruling W: the same day is not past).
        for l, d in self.downstream(p.id):
            if w.by_when.forecast is not None and is_past(
                w.by_when.forecast, work[d.id].by_when.agreed
            ):
                w.signals.add(Signal.S1)
                w.reasons.append(Reason(
                    "S1",
                    f"{p.promisor}'s latest statement moves {p.what.description} to "
                    f"{fmt(w.by_when.forecast)}, past the confirmed deadline of "
                    f"{fmt(work[d.id].by_when.agreed)} for the promise to {d.promisee}.",
                    (d.id, w.by_when.revisions[-1].source_id, l.id),
                ))

        # S2 and rule 10: expected evidence missing inside the near window.
        if near:
            present = self.present(p)
            kinds = (p.expected_evidence.closes, *p.expected_evidence.progress)
            for kind in kinds:
                if kind in present:
                    continue
                if self.normally_carries(p.channel, kind):
                    w.signals.add(Signal.S2)
                    w.reasons.append(Reason(
                        "S2",
                        f"Expected {kind.value} is missing. Every earlier fulfilment in "
                        "this channel carried it. This is a precaution, not a missed "
                        "proof deadline.",
                        (p.id,),
                    ))
            w.signals.add(Signal.S3)
            w.reasons.append(Reason(
                "S3", f"Deadline {fmt(w.by_when.agreed)} is within {w.window_text}.", (p.id,)
            ))

        # S4: someone other than the promisor states a date, or an explicit dispute.
        on_record = {deadline_end(w.by_when.agreed), deadline_end(w.by_when.forecast)}
        for s in self.about(p.id, StatementKind.DATE_STATEMENT):
            same = s.date is not None and deadline_end(s.date) in on_record
            if self.speaker(s) != p.promisor and not same:
                w.signals.add(Signal.S4)
                text = (f"{self.speaker(s) or 'Unknown'} says {fmt(s.date)}; only "
                        f"{p.promisor} can change the date, so it stays "
                        f"{fmt(w.by_when.agreed)}.")
                w.reasons.append(Reason("S4", text, (s.source_id,)))
                self.add_flag_once(Flag(FlagKind.CONFLICT, text, (s.source_id,), (p.id,)))
        for s in self.about(p.id, StatementKind.FULFILMENT_DISPUTE):
            w.signals.add(Signal.S4)
            w.reasons.append(Reason(
                "S4", "Fulfilment is explicitly disputed. Both sides are shown.",
                tuple(w.sources[1:]),
            ))
        for s in self.about(p.id, StatementKind.REFUSAL, StatementKind.FAILURE_CONFIRMED):
            if s.source_id not in w.sources:  # said by someone who can't break it
                w.signals.add(Signal.S4)
                w.reasons.append(Reason(
                    "S4", f"{self.speaker(s) or 'Unknown'} reports a failure, but only "
                    f"{p.promisor} or a person confirming it can make it Broken.",
                    (s.source_id,),
                ))

        # D: at least one confirmed promise depends on this one.
        deps = self.downstream(p.id)
        if deps:
            w.signals.add(Signal.D)
            names = ", ".join(f"the promise to {d.promisee}" for _, d in deps)
            w.reasons.append(Reason(
                "D", f"Confirmed dependent: {names}.",
                tuple(x for l, d in deps for x in (d.id, l.id)),
            ))

        # Rule 6: a revision stays on record as a risk signal.
        if w.by_when.revisions:
            covered = " S1 covers it." if Signal.S1 in w.signals else ""
            w.reasons.append(Reason(
                "REVISION",
                f"{p.promisor} proposed {fmt(w.by_when.forecast)}. "
                + ("Acceptance is evidenced." if w.by_when.acceptance_evidenced else
                   f"Acceptance is not evidenced, so the agreed deadline stays "
                   f"{fmt(w.by_when.agreed)}.")
                + covered,
                (w.by_when.revisions[-1].source_id,),
            ))
        w.level = self.level(w)

    def list_missing_by_channel(self, p: PromiseDraft):
        """Rule 10 / Ruling Z: always listed, never raises risk."""
        present = self.present(p)
        for kind in (p.expected_evidence.closes, *p.expected_evidence.progress):
            if kind not in present and not self.normally_carries(p.channel, kind):
                self.add_flag_once(Flag(
                    FlagKind.MISSING_BY_CHANNEL,
                    f"No {kind.value}: missing by channel, this channel has not "
                    "carried it before. Listed, does not raise risk.",
                    (), (p.id,),
                ))

    def normally_carries(self, channel: str, kind: EvidenceKind) -> bool:
        """Ruling E: every earlier fulfilment carried it, and there was at least one."""
        earlier = [h for h in self.b.history if h.channel == channel]
        return bool(earlier) and all(kind in h.carried for h in earlier)

    @staticmethod
    def level(w: Work) -> Level:
        """Ruling C: top to bottom, first match wins."""
        s = w.signals
        S1, S2, S3, S4, S5, D = (Signal.S1, Signal.S2, Signal.S3,
                                 Signal.S4, Signal.S5, Signal.D)
        if S1 in s or S5 in s or {S2, D} <= s or {S2, S4} <= s:
            return Level.HIGH
        uncovered_revision = bool(w.by_when.revisions) and S1 not in s
        if S2 in s or S4 in s or uncovered_revision or {S3, D} <= s:
            return Level.MEDIUM
        return Level.LOW

    # ------------------------------------------------------- propagation

    def propagate(self, work: dict[str, Work]):
        """S5 through confirmed links only. Kept stops it; Broken and HIGH carry it."""
        def carries(w: Work) -> bool:
            if w.stop is not None:
                return False  # Ruling AJ: a note on the dependent instead
            if w.status is Status.BROKEN:
                return True
            if w.status is Status.OVERDUE_UNVERIFIED:
                return True  # always HIGH
            return w.stop is None and w.level is Level.HIGH

        changed = True
        while changed:
            changed = False
            for l in self.confirmed:
                up, down = work.get(l.upstream), work.get(l.downstream)
                if not up or not down or not carries(up):
                    continue
                if down.status not in ACTIVE or down.stop is not None:
                    continue
                if Signal.S5 in down.signals:
                    continue
                state = "Confirmed failure" if up.status is Status.BROKEN else "HIGH risk"
                up_source = up.sources[-1] if up.status is Status.BROKEN else up.p.source_id
                down.signals.add(Signal.S5)
                down.reasons.append(Reason(
                    "S5",
                    f"Depends on {up.p.promisor}'s promise of {up.p.what.description} "
                    f"({state}) through a confirmed link.",
                    (up.p.id, up_source, l.id),
                ))
                down.level = self.level(down)
                changed = True

    # ------------------------------------------------------------ output

    def assess(self, w: Work, work: dict[str, Work]) -> Assessment:
        level, display, question = w.level, "", None
        reasons = tuple(w.reasons)
        options: tuple[Option, ...] = ()
        if_nobody = None

        if w.stop is not None:  # Ruling AI: status kept, level withheld
            level, display, reasons = None, "Level withheld", ()
        elif w.status is Status.KEPT:
            level, display = None, Status.KEPT.value
        elif w.status is Status.BROKEN:
            level, display = None, BROKEN_DISPLAY
            options, if_nobody = self.broken_options(w)
        elif w.status is Status.OVERDUE_UNVERIFIED:
            level, display, question = Level.HIGH, Level.HIGH.value, OVERDUE_QUESTION
            reasons = (Reason("OVERDUE", OVERDUE_REASON, (w.p.source_id,)),)
            if w.disputes:  # Ruling AA: the dispute stays in the reasons
                w.signals = {Signal.S4}
                reasons += (Reason(
                    "S4", "Fulfilment is explicitly disputed. Both sides are shown.",
                    tuple(w.disputes),
                ),)
        else:
            display = LOW_DISPLAY if level is Level.LOW else level.value
            if level is Level.HIGH:
                options, if_nobody = self.high_options(w)

        label = w.status.value
        if w.status is Status.REVISED and not w.by_when.acceptance_evidenced:
            label = "Revised (proposed)"
        return Assessment(
            promise_id=w.p.id,
            status=w.status,
            status_label=label,
            level=level,
            display=display,
            signals=frozenset(w.signals) if level is not None else frozenset(),
            reasons=reasons,
            by_when=w.by_when,
            sources=tuple(dict.fromkeys(w.sources)),
            recorded=tuple(w.recorded),
            fulfilment_evidence=tuple(w.closing),
            stop=w.stop,
            question=question,
            options=options,
            if_nobody_acts=if_nobody,
            notes=tuple(w.notes),
        )

    def alternatives(self, p: PromiseDraft) -> list[Option]:
        opts = []
        for s in self.about(p.id, StatementKind.ALTERNATIVE_OFFERED):
            if s.cost is not None:  # Ruling AC: only a cost a source states
                text = f"Contact {s.name} (RM{s.cost.amount_rm:,}, source {s.cost.source_id})"
            else:
                text = f"Contact {s.name} (cost not stated)"
            opts.append(Option(OptionKind.CONTACT_ALTERNATIVE, text, name=s.name, cost=s.cost))
        return opts

    def high_options(self, w: Work) -> tuple[tuple[Option, ...], str]:
        """Rule 16, as in P18: options, never actions."""
        opts = []
        if w.by_when.forecast is not None and not w.by_when.acceptance_evidenced:
            opts.append(Option(OptionKind.ACCEPT_REVISED_DATE,
                               f"Accept the revised date of {fmt(w.by_when.forecast)}"))
        opts += self.alternatives(w.p)
        opts.append(Option(OptionKind.ACCEPT_RISK, "Accept the risk"))
        risks = " ".join(r.text for r in w.reasons if r.code in ("S1", "S2", "S5"))
        return tuple(opts), f"Nothing changes. {risks}".strip()

    def broken_options(self, w: Work) -> tuple[tuple[Option, ...], str]:
        """Ruling N: the approved list, built from the bundle only."""
        p = w.p
        opts = [Option(OptionKind.FIND_ANOTHER_WAY,
                       f"Find another way to get the {p.what.description} (cost not stated)")]
        opts += self.alternatives(p)
        for _, d in self.downstream(p.id):
            opts.append(Option(OptionKind.TELL_DEPENDENT, f"Tell {d.promisee}"))
        opts.append(Option(OptionKind.ACCEPT_FAILURE, "Accept the failure"))
        if p.what.kind is OutcomeKind.GOODS:
            text = (f"The {p.what.description} from {p.promisor} will not arrive, "
                    "and nothing replaces them.")
        else:
            text = (f"{p.what.description.capitalize()} by {p.promisor} will not "
                    "happen, and nothing replaces it.")
        return tuple(opts), text

    def exposure(self, work: dict[str, Work]) -> tuple[ExposureLine, ...]:
        """Ruling D: at-risk promises and their confirmed dependents, one line each."""
        shown: list[str] = []
        for pid, w in work.items():
            at_risk = w.status is Status.OVERDUE_UNVERIFIED or (
                w.status in ACTIVE and w.level in (Level.MEDIUM, Level.HIGH)
            )
            if w.stop is None and at_risk:
                for x in [pid] + [d.id for _, d in self.downstream(pid)]:
                    if x not in shown:
                        shown.append(x)
        lines = []
        for pid in shown:
            v = self.promises[pid].value
            if v is None:
                continue
            if v.payer == self.b.user:
                direction = Direction.PAYABLE
            elif v.payee == self.b.user:
                direction = Direction.RECEIVABLE
            else:
                continue
            lines.append(ExposureLine(pid, v.amount_rm, direction, v.source_id))
        return tuple(lines)


def evaluate(bundle: Bundle) -> BundleResult:
    return Engine(bundle).run()
