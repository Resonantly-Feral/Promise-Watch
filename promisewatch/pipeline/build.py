"""Pipeline steps 3 and 4, Validate and Link: drafts -> a Bundle for the rules.

Validation is fixed rules, no AI. Every draft item is checked against the
captured sources. An item that fails is left out of the bundle and listed as
an issue, never dropped silently:

- cites a source that does not exist                      (rules 1, 18)
- cites an attachment that is not provided                (rule 18)
- uses a source marked instruction-like for anything else (rule 4)
- a promise whose promisor is not the party who said it   (rule 5)
- a date, quantity or amount not found in its sources     (rules 7, 8)

Links: the AI only proposes. Every link enters unconfirmed (grey) unless a
human has confirmed it (rule 11).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from promisewatch.model import (
    MYT,
    Bundle,
    EarlierFulfilment,
    Evidence,
    EvidenceKind,
    ExpectedEvidence,
    Link,
    Money,
    Outcome,
    OutcomeKind,
    PromiseDraft,
    Statement,
    StatementKind,
    UnresolvedDate,
)
from promisewatch.pipeline.capture import Captured

# Expected evidence agreed for the fixture before scoring (CLAUDE.md,
# Promise record). Not chosen by the AI.
EXPECTED_EVIDENCE = {
    OutcomeKind.GOODS: ExpectedEvidence(
        EvidenceKind.SIGNED_DELIVERY_NOTE, (EvidenceKind.TRACKING,)
    ),
    OutcomeKind.PAYMENT: ExpectedEvidence(EvidenceKind.BANK_SLIP),
}

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


@dataclass(frozen=True)
class Issue:
    item: str
    check: str
    text: str


@dataclass
class Built:
    bundle: Bundle
    issues: list[Issue] = field(default_factory=list)
    date_reasoning: dict[str, str] = field(default_factory=dict)  # item -> reasoning
    supporting: dict[str, tuple[str, ...]] = field(default_factory=dict)  # promise -> ids
    link_reasons: dict[str, str] = field(default_factory=dict)  # link id -> reason


# ------------------------------------------------------------ text checks


def numbers_in(text: str) -> set[Decimal]:
    found = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            found.add(Decimal(raw.replace(",", "")))
        except InvalidOperation:
            pass
    return found


def date_in(d: date, text: str) -> bool:
    """The day and month of d are written in the text (any common form)."""
    t = text.lower()
    day = str(d.day)
    forms = [
        rf"\b0?{day}/0?{d.month}\b",
        rf"\b0?{day}\s*{MONTHS[d.month - 1]}",
        rf"{MONTHS[d.month - 1]}\w*\s*0?{day}\b",
    ]
    return any(re.search(f, t) for f in forms)


def given(v):
    """An empty string counts as missing, exactly like None."""
    return None if v == "" else v


def to_deadline(obj: dict | None):
    if obj is None:
        return None
    if given(obj.get("date")):
        d = datetime.strptime(obj["date"], "%d/%m/%Y").date()
        if given(obj.get("time")):
            hh, mm = obj["time"].split(":")
            return datetime.combine(d, time(int(hh), int(mm)), MYT)
        return d
    if given(obj.get("vague_text")):
        return UnresolvedDate(obj["vague_text"], given(obj.get("question")) or "Which date is meant?")
    return None


def day_of(dl) -> date | None:
    if isinstance(dl, datetime):
        return dl.date()
    if isinstance(dl, date):
        return dl
    return None


# ------------------------------------------------------------------ build


def build(cap: Captured, drafts: dict, confirmed: set[tuple[str, str]] = frozenset()) -> Built:
    lines = cap.by_id
    issues: list[Issue] = []
    order = {l.source.id: i for i, l in enumerate(cap.lines)}

    instruction_ids = {
        s["source_id"] for s in drafts.get("statements", []) if s["kind"] == "instruction_like"
    }

    def bad_sources(item: str, ids, allow_instruction=False, allow_missing=False) -> bool:
        for sid in ids:
            if sid not in lines:
                issues.append(Issue(item, "unknown source", f"cites {sid}, which is not in the bundle"))
                return True
            if lines[sid].not_provided and not allow_missing:
                issues.append(Issue(item, "not provided", f"cites {sid}, an attachment that is not provided"))
                return True
            if sid in instruction_ids and not allow_instruction:
                issues.append(Issue(item, "instruction-like source",
                                    f"uses {sid}, which is instruction-like text (rule 4)"))
                return True
        return False

    def texts(ids) -> str:
        return "\n".join(lines[i].source.text for i in ids if i in lines)

    def money(item: str, m: dict | None) -> Money | None | bool:
        """A stated amount, or False if it fails validation."""
        if m is None:
            return None
        if any(given(m.get(k)) is None for k in ("amount_rm", "payer", "payee", "source_id")):
            issues.append(Issue(item, "incomplete amount",
                                "an amount with a field left blank is not a stated figure (rule 8)"))
            return False
        if bad_sources(item, [m["source_id"]]):
            return False
        amount = Decimal(m["amount_rm"].replace(",", ""))
        if amount not in numbers_in(lines[m["source_id"]].source.text):
            issues.append(Issue(item, "figure not in source",
                                f"RM{amount:,} is not in {m['source_id']} (rule 8)"))
            return False
        return Money(amount, m["payer"], m["payee"], m["source_id"])

    built = Built(bundle=None)  # type: ignore[arg-type]

    # ---- promises
    promises: list[PromiseDraft] = []
    for p in drafts.get("promises", []):
        item = f"promise {p['id']}"
        ids = [p["source_id"], *p.get("supporting_source_ids", [])]
        if bad_sources(item, ids):
            continue
        said_by = lines[p["source_id"]].source.party
        if said_by != p["promisor"]:
            issues.append(Issue(item, "not the promisor",
                                f"{p['source_id']} was said by {said_by}, not {p['promisor']} (rule 5)"))
            continue
        kind = OutcomeKind(p["outcome_kind"])
        if kind not in EXPECTED_EVIDENCE:
            issues.append(Issue(item, "no expected evidence",
                                f"no expected evidence is agreed for {kind.value} promises"))
            continue
        deadline = to_deadline(p["deadline"])
        d = day_of(deadline)
        if d is not None and not date_in(d, texts(ids)):
            issues.append(Issue(item, "date not in source",
                                f"{d:%d/%m} is not written in {', '.join(ids)} (rule 7)"))
            continue
        if p["quantity"] is not None and Decimal(p["quantity"]) not in numbers_in(texts(ids)):
            issues.append(Issue(item, "figure not in source",
                                f"quantity {p['quantity']} is not in its sources (rule 8)"))
            continue
        value = money(item, p.get("value"))
        if value is False:
            continue
        promises.append(PromiseDraft(
            id=p["id"],
            promisor=p["promisor"],
            promisee=p["promisee"],
            what=Outcome(kind, p["description"], p["order_ref"], p["quantity"]),
            deadline=deadline,
            source_id=p["source_id"],
            expected_evidence=EXPECTED_EVIDENCE[kind],
            channel=lines[p["source_id"]].channel,
            conditions=given(p.get("conditions")),
            value=value,
        ))
        built.date_reasoning[item] = p["deadline"]["reasoning"]
        built.supporting[p["id"]] = tuple(p.get("supporting_source_ids", []))
    kept_ids = {p.id for p in promises}

    # ---- statements (capture's outside-bundle lines first, then the AI's)
    statements: list[Statement] = list(cap.statements)
    seen = {(s.kind, s.source_id) for s in statements}
    for n, s in enumerate(drafts.get("statements", []), 1):
        item = f"statement {n} ({s['kind']})"
        kind = StatementKind[s["kind"].upper()]
        if (kind, s["source_id"]) in seen:
            continue
        is_flag = kind in (StatementKind.INSTRUCTION_LIKE, StatementKind.OUTSIDE_BUNDLE)
        if bad_sources(item, [s["source_id"]], allow_instruction=is_flag, allow_missing=is_flag):
            continue
        missing = [a for a in s.get("about", []) if a not in kept_ids]
        if missing and not is_flag:
            issues.append(Issue(item, "unknown promise", f"is about {', '.join(missing)}, not in the bundle"))
            continue
        dl = to_deadline(s.get("date"))
        d = day_of(dl)
        if d is not None and not date_in(d, lines[s["source_id"]].source.text):
            issues.append(Issue(item, "date not in source",
                                f"{d:%d/%m} is not written in {s['source_id']} (rule 7)"))
            continue
        cost = money(item, s.get("cost"))
        if cost is False:
            continue
        statements.append(Statement(
            kind=kind,
            source_id=s["source_id"],
            about=tuple(a for a in s.get("about", []) if a in kept_ids),
            date=dl,
            name=given(s.get("name")),
            question=given(s.get("question")),
            cost=cost,
        ))
        seen.add((kind, s["source_id"]))
        if s.get("date"):
            built.date_reasoning[item] = s["date"]["reasoning"]

    # Rule 5 reads "latest" from statement order: sort by when it was said.
    def when(st: Statement):
        l = lines[st.source_id]
        return (l.said_at or cap.now.replace(year=1), order[st.source_id])

    statements.sort(key=when)

    # ---- evidence
    evidence: list[Evidence] = []
    for n, e in enumerate(drafts.get("evidence", []), 1):
        item = f"evidence {n} ({e['kind']})"
        if bad_sources(item, [e["source_id"]]):
            continue
        evidence.append(Evidence(
            kind=EvidenceKind[e["kind"].upper()],
            source_id=e["source_id"],
            order_ref=e["order_ref"],
            parties=frozenset(e["parties"]),
            quantity=e["quantity"],
            amount_rm=Decimal(e["amount_rm"].replace(",", "")) if given(e["amount_rm"]) else None,
            signed=e["signed"],
            dated=datetime.strptime(e["dated"], "%d/%m/%Y").date() if given(e["dated"]) else None,
        ))

    # ---- earlier fulfilments (rule 10)
    history: list[EarlierFulfilment] = []
    for n, h in enumerate(drafts.get("earlier_fulfilments", []), 1):
        if bad_sources(f"earlier fulfilment {n}", [h["source_id"]]):
            continue
        history.append(EarlierFulfilment(
            lines[h["source_id"]].channel,
            frozenset(EvidenceKind[k.upper()] for k in h["carried"]),
            h["source_id"],
        ))

    # ---- links: proposed by the AI, confirmed only by a human (rule 11)
    links: list[Link] = []
    for n, l in enumerate(drafts.get("links", []), 1):
        item = f"link {n}"
        if l["upstream"] not in kept_ids or l["downstream"] not in kept_ids:
            issues.append(Issue(item, "unknown promise",
                                f"links {l['upstream']} -> {l['downstream']}, not both in the bundle"))
            continue
        if bad_sources(item, l.get("source_ids", [])):
            continue
        link_id = f"link-{n}"
        links.append(Link(link_id, l["upstream"], l["downstream"],
                          confirmed=(l["upstream"], l["downstream"]) in confirmed))
        built.link_reasons[link_id] = l["reason"]

    built.bundle = Bundle(
        id=cap.bundle_id,
        user=cap.user,
        now=cap.now,
        sources=tuple(l.source for l in cap.lines),
        promises=tuple(promises),
        statements=tuple(statements),
        evidence=tuple(evidence),
        history=tuple(history),
        links=tuple(links),
        near_window=cap.near_window,
    )
    built.issues = issues
    return built
