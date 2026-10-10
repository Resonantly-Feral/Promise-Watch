"""PromiseWatch data types.

Inputs (what extraction produces, or what Pass 1 fixtures write by hand) and
outputs (what the rules engine returns). No rules live in this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

MYT = ZoneInfo("Asia/Kuala_Lumpur")

LOW_DISPLAY = "No elevated risk detected in this bundle"
BROKEN_DISPLAY = "Confirmed failure"
OVERDUE_REASON = "deadline passed, no proof"
OVERDUE_QUESTION = "Did this happen?"
DEFAULT_NEAR_WINDOW = timedelta(days=7)


# ---------------------------------------------------------------- inputs


class SourceType(Enum):
    """Rule 1: every fact carries its source type."""

    DOCUMENT = "Document"
    MESSAGE = "Message"
    OWNER_SAID = "Owner-said"
    UNKNOWN = "Unknown"


@dataclass(frozen=True)
class Source:
    """One exact message or document line."""

    id: str
    type: SourceType
    text: str
    party: str | None = None  # who said or issued it


class OutcomeKind(Enum):
    GOODS = "goods"
    PAYMENT = "payment"
    WORK = "work"
    DOCUMENT = "document"


class EvidenceKind(Enum):
    SIGNED_DELIVERY_NOTE = "signed delivery note"  # closes delivery
    TRACKING = "tracking"  # progress proof of dispatch only
    BANK_SLIP = "bank slip"  # transfer initiation, not receipt


@dataclass(frozen=True)
class Outcome:
    kind: OutcomeKind
    description: str
    order_ref: str
    quantity: int | None = None


@dataclass(frozen=True)
class Money:
    """An amount a source states. Never computed."""

    amount_rm: Decimal
    payer: str
    payee: str
    source_id: str


@dataclass(frozen=True)
class UnresolvedDate:
    """Rule 7: a vague date that was not resolved. Never guessed."""

    text: str
    question: str


# A deadline is a datetime (time stated), a date (day only), an unresolved
# vague date, or None when the bundle does not state one.
Deadline = datetime | date | UnresolvedDate | None


@dataclass(frozen=True)
class ExpectedEvidence:
    """Agreed for the fixture before scoring."""

    closes: EvidenceKind  # outcome proof: the only kind that can close it
    progress: tuple[EvidenceKind, ...] = ()  # progress proof: never closes


@dataclass(frozen=True)
class PromiseDraft:
    """A draft promise record before the rules run.

    Status, risk level, the full By-when history and fulfilment evidence are
    rule outputs, so they live on Assessment, not here.
    """

    id: str
    promisor: str  # Who
    promisee: str  # To whom
    what: Outcome
    deadline: Deadline  # the original commitment
    source_id: str
    expected_evidence: ExpectedEvidence
    channel: str
    conditions: str | None = None
    value: Money | None = None


class StatementKind(Enum):
    FULFILMENT_CLAIM = "fulfilment claim"  # words, not evidence
    DATE_STATEMENT = "date statement"  # someone states or proposes a date
    ACCEPTANCE = "acceptance"  # recipient accepts a stated date
    REFUSAL = "refusal"  # promisor says it will not be fulfilled
    FAILURE_CONFIRMED = "failure confirmed"  # a human confirms it failed
    FULFILMENT_DISPUTE = "fulfilment dispute"  # explicit disagreement
    AMBIGUOUS_REFERENCE = "ambiguous reference"  # can't tell which promise
    INSTRUCTION_LIKE = "instruction-like"  # rule 4: flag, never obey
    OUTSIDE_BUNDLE = "outside bundle"  # rule 18: flag, never use
    ALTERNATIVE_OFFERED = "alternative offered"  # e.g. a backup supplier
    REMARK = "remark"  # anything else worth recording


@dataclass(frozen=True)
class Statement:
    """Something said in a source, interpreted by extraction.

    `about` lists the promise ids it may refer to. The speaker is the
    source's party.
    """

    kind: StatementKind
    source_id: str
    about: tuple[str, ...] = ()
    date: Deadline = None
    name: str | None = None
    question: str | None = None  # for ambiguity: the one settling question
    cost: Money | None = None  # Ruling AC: only when a source states it


@dataclass(frozen=True)
class Evidence:
    kind: EvidenceKind
    source_id: str
    order_ref: str
    parties: frozenset[str]
    quantity: int | None = None
    amount_rm: Decimal | None = None
    signed: bool = False
    dated: date | None = None


@dataclass(frozen=True)
class EarlierFulfilment:
    """Rule 10 / Ruling E: an earlier fulfilment in the same channel."""

    channel: str
    carried: frozenset[EvidenceKind]
    source_id: str


@dataclass(frozen=True)
class Link:
    """Rule 11: upstream is a prerequisite of downstream."""

    id: str
    upstream: str
    downstream: str
    confirmed: bool


@dataclass(frozen=True)
class Bundle:
    """Rule 18: one declared bundle at a time."""

    id: str
    user: str  # whose view: payable/receivable is from this party
    now: datetime  # fixed reference time, never the system clock
    sources: tuple[Source, ...]
    promises: tuple[PromiseDraft, ...] = ()
    statements: tuple[Statement, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    history: tuple[EarlierFulfilment, ...] = ()
    links: tuple[Link, ...] = ()
    near_window: timedelta = DEFAULT_NEAR_WINDOW
    vendor_windows: tuple[tuple[str, timedelta], ...] = ()  # set before scoring


# ---------------------------------------------------------------- outputs


class Status(Enum):
    OPEN = "Open"
    REVISED = "Revised"
    KEPT = "Kept"
    OVERDUE_UNVERIFIED = "Overdue unverified"
    BROKEN = "Broken"
    DISPUTED = "Disputed"


class Level(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Signal(Enum):
    S1 = "Contradiction"
    S2 = "Expected proof missing"
    S3 = "Near"
    S4 = "Conflict"
    S5 = "Upstream risk"
    D = "Downstream"


@dataclass(frozen=True)
class Reason:
    """Rule 13. `code` is a Signal name, "REVISION" or "OVERDUE"."""

    code: str
    text: str
    refs: tuple[str, ...] = ()  # promise, source and link ids


@dataclass(frozen=True)
class Revision:
    date: Deadline
    source_id: str
    accepted_by: str | None = None  # source id of the recipient's acceptance


@dataclass(frozen=True)
class ByWhen:
    """Rule 5 / Ruling J: commitment kept separate from forecast."""

    original: Deadline
    agreed: Deadline
    forecast: Deadline  # latest promisor statement; None if never revised
    acceptance_evidenced: bool  # of the latest forecast
    revisions: tuple[Revision, ...] = ()
    unresolved: UnresolvedDate | None = None


class OptionKind(Enum):
    ACCEPT_REVISED_DATE = "accept the revised date"
    CONTACT_ALTERNATIVE = "contact the alternative"
    ACCEPT_RISK = "accept the risk"
    FIND_ANOTHER_WAY = "find another way"  # Ruling N, Broken only
    TELL_DEPENDENT = "tell the dependent recipient"  # Ruling N, Broken only
    ACCEPT_FAILURE = "accept the failure"  # Ruling N, Broken only


@dataclass(frozen=True)
class Option:
    """Rule 16: an option, never an action."""

    kind: OptionKind
    text: str
    name: str | None = None
    cost: Money | None = None  # only where a source states it


@dataclass(frozen=True)
class Stop:
    """Rule 17: what is unclear and the one question that settles it."""

    unclear: str
    question: str


class FlagKind(Enum):
    ANOMALY = "anomaly"
    OUTSIDE_BUNDLE = "outside bundle"
    EVIDENCE_MISMATCH = "evidence mismatch"
    CONFLICT = "conflict"
    MISSING_BY_CHANNEL = "missing by channel"
    UNRESOLVED_DATE = "unresolved date"
    AMBIGUOUS_REFERENCE = "ambiguous reference"


@dataclass(frozen=True)
class Flag:
    kind: FlagKind
    text: str
    source_ids: tuple[str, ...] = ()
    about: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    """Status and level are separate fields (Ruling B)."""

    promise_id: str
    status: Status
    level: Level | None  # None for Kept, Broken and stops
    display: str  # LOW_DISPLAY, BROKEN_DISPLAY, or the level name
    signals: frozenset[Signal]
    reasons: tuple[Reason, ...]
    by_when: ByWhen
    sources: tuple[str, ...]  # source ids behind the status
    recorded: tuple[str, ...] = ()  # claims and remarks: recorded, no effect
    fulfilment_evidence: tuple[str, ...] = ()
    stop: Stop | None = None
    question: str | None = None
    options: tuple[Option, ...] = ()
    if_nobody_acts: str | None = None
    status_label: str = ""  # Ruling AD: "Revised (proposed)" until accepted
    notes: tuple[str, ...] = ()  # Ruling AJ: e.g. a stopped upstream


class Direction(Enum):
    PAYABLE = "payable"  # the user owes it
    RECEIVABLE = "receivable"  # the user is owed it


@dataclass(frozen=True)
class ExposureLine:
    """Ruling D: one line per stated amount. Never summed."""

    promise_id: str
    amount_rm: Decimal
    direction: Direction
    source_id: str


@dataclass(frozen=True)
class BundleResult:
    bundle_id: str
    assessments: dict[str, Assessment] = field(default_factory=dict)
    flags: tuple[Flag, ...] = ()
    exposure: tuple[ExposureLine, ...] = ()
    links: tuple[Link, ...] = ()  # proposed links shown grey
