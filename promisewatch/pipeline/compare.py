"""Pass 2 on the demo bundle: compare each stage with data/EXPECTED.md.

Every check names the stage it belongs to, so a failure points at the first
stage that diverged (CLAUDE.md, Tests). The checks restate EXPECTED.md;
where EXPECTED.md and CLAUDE.md differ, the check follows CLAUDE.md and says
so in its text.

The "after" half confirms the proposed link. In the product a human does
that; here the comparison plays that human step, as EXPECTED.md describes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from promisewatch.model import (
    LOW_DISPLAY,
    Direction,
    FlagKind,
    Level,
    OptionKind,
    Signal,
    Status,
)
from promisewatch.pipeline.build import build, date_in, numbers_in
from promisewatch.pipeline.capture import Captured
from promisewatch.rules import evaluate

STAGES = ["Capture", "Extract", "Validate", "Link", "Score (before)", "Score (after)", "Show"]

CJ, ME, SH = "Cetak Jaya", "Majlis Events", "Syarikat Hijau"


@dataclass(frozen=True)
class Check:
    stage: str
    name: str
    ok: bool
    detail: str = ""


def _find(items, **kv):
    return [i for i in items if all(i.get(k) == v for k, v in kv.items())]


def compare(cap: Captured, drafts: dict | None) -> list[Check]:
    checks: list[Check] = []

    def check(stage, name, ok, detail=""):
        checks.append(Check(stage, name, bool(ok), detail))

    # ------------------------------------------------------------ Capture
    lines = cap.by_id
    chat = [l for l in cap.lines if l.said_at]
    check("Capture", "13 chat lines from 2 chats", len(chat) == 13, f"{len(chat)} lines")
    check("Capture", "job slip photo marked not provided (rule 18)",
          lines["chat_cetak_jaya:5"].not_provided)
    check("Capture", "both PDF attachments matched to their documents",
          lines["chat_cetak_jaya:4"].attachment_of == "CJ-Q-0217"
          and lines["chat_syarikat_hijau:3"].attachment_of == "ME-INV-0311")
    if drafts is None:
        return checks

    # ------------------------------------------------------------ Extract
    ps = drafts["promises"]
    printer = _find(ps, promisor=CJ, promisee=ME)
    customer = _find(ps, promisor=ME, promisee=SH)
    check("Extract", "exactly 2 promises, none of them payment promises",
          len(ps) == 2 and not _find(ps, outcome_kind="payment"),
          ", ".join(f"{p['promisor']} -> {p['promisee']} ({p['outcome_kind']})" for p in ps))

    def promise_checks(label, found, order_ref, deadline, amount, payer, payee, chat_id, doc):
        if len(found) != 1:
            check("Extract", f"{label}: found once", False, f"found {len(found)}")
            return None
        p = found[0]
        check("Extract", f"{label}: 300 gift bags (goods)",
              p["outcome_kind"] == "goods" and p["quantity"] == 300, p["description"])
        if order_ref:
            check("Extract", f"{label}: order {order_ref}", p["order_ref"] == order_ref, p["order_ref"])
        check("Extract", f"{label}: by {deadline}",
              p["deadline"]["date"] == deadline and not p["deadline"]["time"],
              f"{p['deadline']['date']} ({p['deadline']['reasoning']})")
        v = p["value"] or {}
        check("Extract", f"{label}: RM{amount:,.2f}, {payer} pays {payee}, from {doc}",
              v and Decimal(v["amount_rm"].replace(",", "")) == amount
              and v["payer"] == payer and v["payee"] == payee and v["source_id"].startswith(doc),
              str(v))
        ids = [p["source_id"], *p["supporting_source_ids"]]
        cited = "\n".join(cap.by_id[i].source.text for i in ids if i in cap.by_id)
        check("Extract", f"{label}: 300 and {deadline[:5]} are written in its cited lines (rule 8)",
              Decimal(300) in numbers_in(cited)
              and date_in(date(int(deadline[6:]), int(deadline[3:5]), int(deadline[:2])), cited),
              ", ".join(ids))
        check("Extract", f"{label}: sources include {chat_id} and {doc}",
              chat_id in ids and any(i.startswith(doc) for i in ids), ", ".join(ids))
        check("Extract", f"{label}: job slip photo not used (not provided)",
              "chat_cetak_jaya:5" not in ids,
              "EXPECTED.md lists the photo; it is not provided, so rule 18 keeps it out")
        return p["id"]

    pid = promise_checks("printer", printer, "CJ-2611", "13/11/2026", Decimal("8400"),
                         ME, CJ, "chat_cetak_jaya:2", "CJ-Q-0217_quotation")
    cid = promise_checks("customer", customer, None, "27/11/2026", Decimal("11000"),
                         SH, ME, "chat_syarikat_hijau:2", "ME-INV-0311_invoice")

    st = drafts["statements"]
    revision = [s for s in _find(st, kind="date_statement")
                if pid in s["about"] and s["source_id"] in ("chat_cetak_jaya:7", "chat_cetak_jaya:8")]
    check("Extract", "printer proposes 28/11 (14/10 11:46)",
          len(revision) == 1 and revision[0]["date"]["date"] == "28/11/2026"
          and revision[0]["about"] == [pid],
          str([(s["source_id"], (s["date"] or {}).get("date")) for s in revision]))
    others = [s for s in _find(st, kind="date_statement") if s not in revision]
    stray = [s for s in others if (s["date"] or {}).get("date") not in ("13/11/2026", "27/11/2026")]
    check("Extract", "no other date statement that would create a false conflict",
          not stray, str([(s["source_id"], (s["date"] or {}).get("date")) for s in stray]))
    alt = _find(st, kind="alternative_offered")
    check("Extract", "Cetak Murni offered as backup, no cost",
          len(alt) == 1 and alt[0]["name"] == "Cetak Murni" and alt[0]["cost"] is None
          and alt[0]["about"] == [pid], str(alt))
    inj = _find(st, kind="instruction_like")
    check("Extract", "SYSTEM NOTE (14/10 11:52) recorded as instruction-like",
          [s["source_id"] for s in inj] == ["chat_cetak_jaya:10"], str(inj))
    check("Extract", "no evidence, acceptance, refusal or dispute",
          not drafts["evidence"] and not _find(st, kind="acceptance")
          and not _find(st, kind="refusal") and not _find(st, kind="fulfilment_dispute"),
          f"evidence={drafts['evidence']}")
    check("Extract", "link proposed: printer -> customer",
          any(l["upstream"] == pid and l["downstream"] == cid for l in drafts["links"]),
          str([(l["upstream"], l["downstream"], l["reason"]) for l in drafts["links"]]))

    # ----------------------------------------------------------- Validate
    before = build(cap, drafts)
    check("Validate", "no validation issues", not before.issues,
          "; ".join(f"{i.item}: {i.text}" for i in before.issues))
    b = before.bundle
    if pid not in {p.id for p in b.promises} or cid not in {p.id for p in b.promises}:
        check("Validate", "both promises reach the rules", False)
        return checks

    # --------------------------------------------------------------- Link
    link = next((l for l in b.links if (l.upstream, l.downstream) == (pid, cid)), None)
    check("Link", "link starts grey (proposed, not confirmed)", link and not link.confirmed)

    # ----------------------------------------------------- Score (before)
    r = evaluate(b)
    a, c = r.assessments[pid], r.assessments[cid]
    check("Score (before)", "printer Revised (proposed), MEDIUM",
          a.status_label == "Revised (proposed)" and a.level is Level.MEDIUM,
          f"{a.status_label}, {a.display}")
    check("Score (before)", "agreed 13/11 kept, forecast 28/11, acceptance not evidenced",
          a.by_when.original == date(2026, 11, 13) and a.by_when.agreed == date(2026, 11, 13)
          and a.by_when.forecast == date(2026, 11, 28) and not a.by_when.acceptance_evidenced,
          str(a.by_when))
    check("Score (before)", "S1 does not fire (link not confirmed)", Signal.S1 not in a.signals)
    check("Score (before)", "customer Open, LOW, 'No elevated risk detected in this bundle'",
          c.status is Status.OPEN and c.level is Level.LOW and c.display == LOW_DISPLAY,
          f"{c.status_label}, {c.display}")
    anomaly = [f for f in r.flags if f.kind is FlagKind.ANOMALY]
    check("Score (before)", "SYSTEM NOTE flagged, shown, not obeyed",
          [f.source_ids for f in anomaly] == [("chat_cetak_jaya:10",)], str(anomaly))
    check("Score (before)", "printer NOT Kept", a.status is not Status.KEPT)

    # ------------------------------------------------------ Score (after)
    after = build(cap, drafts, confirmed={(pid, cid)})
    r2 = evaluate(after.bundle)
    a2, c2 = r2.assessments[pid], r2.assessments[cid]
    s1 = next((x for x in a2.reasons if x.code == "S1"), None)
    check("Score (after)", "printer Revised (proposed), HIGH, S1 and D",
          a2.status_label == "Revised (proposed)" and a2.level is Level.HIGH
          and {Signal.S1, Signal.D} <= a2.signals, f"{a2.display} {sorted(s.name for s in a2.signals)}")
    check("Score (after)", "S1 reason: 28/11 moves past the confirmed 27/11",
          s1 and "28/11" in s1.text and "27/11" in s1.text, s1.text if s1 else "no S1 reason")
    s5 = next((x for x in c2.reasons if x.code == "S5"), None)
    check("Score (after)", "customer Open, HIGH under S5, not Broken",
          c2.status is Status.OPEN and c2.level is Level.HIGH and Signal.S5 in c2.signals,
          f"{c2.status_label}, {c2.display}")
    check("Score (after)", "S5 reason shows the upstream promise, its source and the link",
          s5 and pid in s5.refs and any(ref.startswith("link-") for ref in s5.refs),
          str(s5.refs) if s5 else "no S5 reason")
    check("Score (after)", "no near-window signals (S2, S3) on either promise",
          not ({Signal.S2, Signal.S3} & (a2.signals | c2.signals)))

    # --------------------------------------------------------------- Show
    lines_ = {(e.amount_rm, e.direction, e.source_id.split(":")[0]) for e in r2.exposure}
    check("Show", "RM8,400 payable (quotation) and RM11,000 receivable (invoice), never summed",
          lines_ == {(Decimal("8400.00"), Direction.PAYABLE, "CJ-Q-0217_quotation"),
                     (Decimal("11000.00"), Direction.RECEIVABLE, "ME-INV-0311_invoice")}
          and len(r2.exposure) == 2, str(r2.exposure))
    kinds = [o.kind for o in a2.options]
    backup = next((o for o in a2.options if o.kind is OptionKind.CONTACT_ALTERNATIVE), None)
    check("Show", "options: accept 28/11, contact Cetak Murni (cost not stated), accept the risk",
          kinds == [OptionKind.ACCEPT_REVISED_DATE, OptionKind.CONTACT_ALTERNATIVE,
                    OptionKind.ACCEPT_RISK]
          and "28/11" in a2.options[0].text
          and backup.name == "Cetak Murni" and backup.cost is None
          and "cost not stated" in backup.text,
          "; ".join(o.text for o in a2.options))
    check("Show", "if nobody acts: 28/11 misses 27/11",
          a2.if_nobody_acts and "28/11" in a2.if_nobody_acts and "27/11" in a2.if_nobody_acts,
          a2.if_nobody_acts or "")
    return checks


def first_divergence(checks: list[Check]) -> str | None:
    for stage in STAGES:
        if any(not c.ok for c in checks if c.stage == stage):
            return stage
    return None
