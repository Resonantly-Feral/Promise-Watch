"""Pipeline step 6, Show: one static HTML page from a saved run.

    python -m promisewatch.page data/runs/<run>.json          # -> docs/demo/<run>.html
    python -m promisewatch.page data/runs/<run>.json -o FILE

The page holds two results, both computed here by the rules engine from the
saved run: before and after a human confirms the proposed links. The
"Confirm link" button only switches which one is visible. Nothing on the
page is computed in the browser, and nothing on it acts: options are shown,
never taken (rule 16). Validation issues sit next to the warnings and are
never hidden, so a record left out is always visible.

No server and no external requests: the page is one self-contained file.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from html import escape
from pathlib import Path

from promisewatch.model import (
    LOW_DISPLAY,
    Assessment,
    BundleResult,
    Direction,
    FlagKind,
    Level,
    UnresolvedDate,
)
from promisewatch.pipeline.build import Built, build
from promisewatch.pipeline.capture import Captured, capture
from promisewatch.rules import evaluate

LEVEL_ORDER = {Level.HIGH: 0, Level.MEDIUM: 1, Level.LOW: 2, None: 3}


def e(x) -> str:
    return escape(str(x), quote=True)


def fmt_deadline(d) -> str:
    if d is None:
        return "not stated"
    if isinstance(d, UnresolvedDate):
        return f"unresolved: “{d.text}” ({d.question})"
    if isinstance(d, datetime):
        return d.strftime("%d/%m/%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d)


class Page:
    def __init__(self, cap: Captured, run_name: str, saved: dict):
        self.cap = cap
        self.lines = cap.by_id
        self.run_name = run_name
        self.saved = saved
        drafts = saved["drafts"]
        before = build(cap, drafts)
        self.proposed = [(l.upstream, l.downstream) for l in before.bundle.links]
        self.states: list[tuple[str, Built, BundleResult]] = [
            ("before", before, evaluate(before.bundle))
        ]
        if self.proposed:
            after = build(cap, drafts, confirmed=set(self.proposed))
            self.states.append(("after", after, evaluate(after.bundle)))

    # ------------------------------------------------------------ pieces

    def quote(self, sid: str, note: str = "") -> str:
        line = self.lines.get(sid)
        if line is None:
            return f'<p class="ref missing">{e(sid)}: not in this bundle</p>'
        s = line.source
        who = line.speaker if line.speaker and line.speaker != s.party else None
        meta = [f"<b>{e(sid)}</b>", e(s.type.value)]
        if s.party:
            meta.append(e(f"{who} ({s.party})" if who else s.party))
        if line.said_at:
            meta.append(e(line.said_at.strftime("%d/%m/%Y %H:%M")))
        extra = f'<span class="tag">{e(note)}</span>' if note else ""
        return (f'<blockquote class="src"><p>{e(s.text)}</p>'
                f'<footer>{" · ".join(meta)}{extra}</footer></blockquote>')

    def promise_name(self, built: Built, pid: str) -> str:
        p = next((p for p in built.bundle.promises if p.id == pid), None)
        if p is None:
            return e(pid)
        return e(f"{p.promisor} to {p.promisee}: {p.what.description}")

    def link_text(self, built: Built, lid: str) -> str:
        l = next((l for l in built.bundle.links if l.id == lid), None)
        if l is None:
            return e(lid)
        state = "confirmed by a human" if l.confirmed else "proposed, not confirmed"
        return (f'<span class="link {"on" if l.confirmed else "off"}">{e(lid)}: '
                f"{self.promise_name(built, l.upstream)} → "
                f"{self.promise_name(built, l.downstream)} ({state})</span>")

    def refs(self, built: Built, refs) -> str:
        pids = {p.id for p in built.bundle.promises}
        out = []
        for r in refs:
            if r in pids:
                out.append(f'<p class="ref">Promise {e(r)}: {self.promise_name(built, r)}</p>')
            elif r.startswith("link-"):
                out.append(f'<p class="ref">{self.link_text(built, r)}</p>')
            else:
                out.append(self.quote(r))
        return "".join(out)

    # ------------------------------------------------------------- card

    def card(self, built: Built, res: BundleResult, a: Assessment) -> str:
        p = next(p for p in built.bundle.promises if p.id == a.promise_id)
        level = a.level.name if a.level else "none"
        what = p.what.description
        if p.what.order_ref:
            what += f" (order {p.what.order_ref})"

        parts = [
            f'<article class="card lv-{level}" id="{e(p.id)}">',
            '<header class="card-head">',
            f'<p class="eyebrow">{e(p.id)} · promise from <b>{e(p.promisor)}</b> '
            f'to <b>{e(p.promisee)}</b></p>',
            f"<h3>{e(what)}</h3>",
            '<p class="marks">',
            f'<span class="status">{e(a.status_label or a.status.value)}</span>',
        ]
        if a.level is not None:
            parts.append(f'<span class="level">{e(a.level.name)}</span>')
        elif a.stop is None:
            parts.append(f'<span class="level plain">{e(a.display)}</span>')
        parts.append("</p></header>")

        parts.append('<h4>What was promised</h4>' + self.quote(p.source_id))

        bw = a.by_when
        rows = [("Original commitment", fmt_deadline(bw.original)),
                ("Agreed deadline", fmt_deadline(bw.agreed))]
        if bw.forecast is not None:
            acc = "acceptance evidenced" if bw.acceptance_evidenced else "acceptance not evidenced"
            rows.append(("Latest forecast", f"{fmt_deadline(bw.forecast)}, {acc}"))
        for r in bw.revisions:
            rows.append(("Revision", f"{fmt_deadline(r.date)} ({r.source_id}"
                         + (f", accepted in {r.accepted_by})" if r.accepted_by else ")")))
        parts.append('<h4>By when</h4><dl class="when">' + "".join(
            f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows) + "</dl>")

        if a.stop is not None:
            parts.append(
                '<div class="stop"><h4>Stopped: not enough information, no level</h4>'
                f"<p>Unclear: {e(a.stop.unclear)}</p>"
                f'<p class="question">{e(a.stop.question)}</p></div>')
        if a.question:
            parts.append(f'<p class="question">{e(a.question)}</p>')

        if a.reasons:
            parts.append("<h4>Reasons</h4><ol class=\"reasons\">")
            for r in a.reasons:
                parts.append(f'<li><p><b class="code">{e(r.code)}</b> {e(r.text)}</p>'
                             f'<div class="cited">{self.refs(built, r.refs)}</div></li>')
            parts.append("</ol>")
        elif a.level is Level.LOW:
            parts.append(f'<p class="calm">{e(LOW_DISPLAY)}</p>')

        cited = {x for r in a.reasons for x in r.refs}
        status_src = [s for s in a.sources if s not in cited and s != p.source_id]
        if status_src:
            parts.append("<h4>Status source</h4>" + "".join(self.quote(s) for s in status_src))
        if a.fulfilment_evidence:
            parts.append("<h4>Fulfilment evidence</h4>"
                         + "".join(self.quote(s) for s in a.fulfilment_evidence))
        for n in a.notes:
            parts.append(f'<p class="note">{e(n)}</p>')
        if a.recorded:
            parts.append("<h4>Recorded, changes no mark</h4>"
                         + "".join(self.quote(s) for s in a.recorded))

        mine = [f for f in res.flags if p.id in f.about]
        missing = [f for f in mine if f.kind is FlagKind.MISSING_BY_CHANNEL]
        if missing:
            heads, tails = [], set()
            for f in missing:
                head, _, tail = f.text.partition(": ")
                heads.append(head)
                tails.add(tail)
            tail = tails.pop() if len(tails) == 1 else ""
            items = heads if tail else [f.text for f in missing]
            parts.append('<div class="missing"><h4>Missing by channel</h4><ul>'
                         + "".join(f"<li>{e(h)}</li>" for h in items) + "</ul>"
                         + (f"<p>{e(tail[:1].upper() + tail[1:])}</p>" if tail else "")
                         + "</div>")
        for f in mine:
            if f.kind is not FlagKind.MISSING_BY_CHANNEL:
                parts.append(f'<div class="flag"><p><b>{e(f.kind.value.capitalize())}</b> '
                             f"{e(f.text)}</p>{''.join(self.quote(s) for s in f.source_ids)}</div>")

        if a.options or a.if_nobody_acts:
            parts.append('<div class="options"><h4>Options <em>you</em> choose from</h4>')
            for o in a.options:
                parts.append(f'<button type="button" class="option">{e(o.text)}</button>')
            parts.append('<p class="option-note" aria-live="polite"></p>')
            if a.if_nobody_acts:
                parts.append(f'<p class="nobody"><b>If nobody acts</b> {e(a.if_nobody_acts)}</p>')
            parts.append("</div>")
        parts.append("</article>")
        return "".join(parts)

    # ------------------------------------------------------------ states

    def issues(self, built: Built) -> str:
        if not built.issues:
            return ('<section class="issues clean"><h2>Validation</h2>'
                    "<p>No validation issues. Every date and figure was found in the line it cites.</p></section>")
        items = "".join(f"<li><b>{e(i.item)}</b> · {e(i.check)}<br>{e(i.text)}</li>"
                        for i in built.issues)
        n = len(built.issues)
        return ('<section class="issues"><h2>Validation: '
                f'{n} item{"s" if n != 1 else ""} left out</h2>'
                "<p>These draft records failed a check against their sources and were "
                "<em>not scored</em>. The warnings below do not include them.</p>"
                f"<ul>{items}</ul></section>")

    def loose_flags(self, built: Built, res: BundleResult) -> str:
        pids = {p.id for p in built.bundle.promises}
        loose = [f for f in res.flags
                 if f.kind is not FlagKind.MISSING_BY_CHANNEL and not (set(f.about) & pids)]
        if not loose:
            return ""
        out = ['<section class="flags"><h2>Flags</h2>']
        for f in loose:
            out.append(f'<div class="flag lv-{e(f.kind.name)}"><p><b>{e(f.kind.value.capitalize())}</b> '
                       f"{e(f.text)}</p>{''.join(self.quote(s) for s in f.source_ids)}</div>")
        out.append("</section>")
        return "".join(out)

    def exposure(self, built: Built, res: BundleResult) -> str:
        if not res.exposure:
            return ('<section class="exposure"><h2>Exposure</h2>'
                    "<p>No amounts on at-risk promises in this result.</p></section>")
        out = ['<section class="exposure"><h2>Exposure, <em>never added together</em></h2>',
               "<p>Each stated amount on its own line, with its source. Read them side by side.</p>"]
        for x in res.exposure:
            label = ("Payable: you owe it" if x.direction is Direction.PAYABLE
                     else "Receivable: you are owed it")
            out.append(f'<div class="money {x.direction.value}">'
                       f'<p class="amount">RM{x.amount_rm:,.2f}</p>'
                       f'<p class="dir">{e(label)}</p>'
                       f'<p class="for">On promise {e(x.promise_id)}: {self.promise_name(built, x.promise_id)}</p>'
                       f"{self.quote(x.source_id)}</div>")
        out.append("</section>")
        return "".join(out)

    def links(self, built: Built) -> str:
        if not built.bundle.links:
            return ""
        out = ['<section class="links"><h2>Links</h2>']
        for l in built.bundle.links:
            out.append(f"<p>{self.link_text(built, l.id)}</p>")
            if l.id in built.link_reasons:
                out.append(f'<p class="why">Proposed because: <em>{e(built.link_reasons[l.id])}</em></p>')
        out.append("</section>")
        return "".join(out)

    def state(self, name: str, built: Built, res: BundleResult) -> str:
        cards = sorted(res.assessments.values(),
                       key=lambda a: (LEVEL_ORDER.get(a.level, 3), a.promise_id))
        hidden = "" if name == "before" else " hidden"
        return (f'<div class="state" data-state="{name}"{hidden}>'
                + self.issues(built)
                + '<section class="warnings"><h2>Promises</h2>'
                + "".join(self.card(built, res, a) for a in cards)
                + "</section>"
                + self.loose_flags(built, res)
                + self.exposure(built, res)
                + self.links(built)
                + "</div>")

    # ------------------------------------------------------------ bundle

    def transcript(self, res: BundleResult) -> str:
        marks: dict[str, str] = {}
        for f in res.flags:
            for sid in f.source_ids:
                if f.kind is FlagKind.ANOMALY:
                    marks[sid] = "Instruction-like text: flagged, not obeyed"
                elif f.kind is FlagKind.OUTSIDE_BUNDLE:
                    marks[sid] = "Outside this bundle: nothing taken from it"
        out = ['<section class="bundle"><h2>The bundle</h2>'
               "<p>Every line PromiseWatch read, with its source id and type.</p>"]
        by_channel: dict[str, list] = {}
        for l in self.cap.lines:
            by_channel.setdefault(l.source.id.rsplit(":", 1)[0], []).append(l)
        for name, lines in by_channel.items():
            is_doc = lines[0].said_at is None
            body = "".join(
                f'<div class="line{" marked" if l.source.id in marks else ""}">'
                + self.quote(l.source.id, marks.get(l.source.id, "")) + "</div>"
                for l in lines)
            out.append(f'<details{"" if is_doc else " open"}><summary>{e(name)}'
                       f' <span>{e(lines[0].source.type.value)}</span></summary>{body}</details>')
        out.append("</section>")
        return "".join(out)

    # -------------------------------------------------------------- page

    def toggle(self) -> str:
        if self.proposed:
            names = ", ".join(f"{u} → {d}" for u, d in self.proposed)
            return ('<div class="confirm"><button type="button" id="confirm" aria-pressed="false" '
                    f'data-off="Confirm link: {e(names)}" data-on="Link confirmed: {e(names)} (undo)">'
                    f"Confirm link: {e(names)}</button>"
                    '<p id="confirm-note">Showing the result <em>before</em> a human confirms the '
                    "proposed link. Both results were computed by the rules engine.</p></div>")
        built = self.states[0][1]
        dropped = any(i.item.startswith("link") for i in built.issues)
        why = ("A proposed link was left out at validation; see Validation below."
               if dropped else "No link was proposed in this run.")
        return ('<div class="confirm"><button type="button" disabled>No link to confirm</button>'
                f"<p>{e(why)}</p></div>")

    def html(self) -> str:
        cap = self.cap
        before_res = self.states[0][2]
        meta = (f"{cap.now.strftime('%A %d/%m/%Y, %H:%M')} Malaysia time · near window "
                f"{cap.near_window.days} days · run {self.run_name}"
                f" · model {self.saved.get('model', 'unknown')}")
        body = (
            '<header class="top">'
            '<p class="brand">PromiseWatch</p>'
            f"<h1>Which promises might break, <em>before</em> the deadline.</h1>"
            f'<p class="meta">Bundle <b>{e(cap.bundle_id)}</b>, seen as <b>{e(cap.user)}</b> · {e(meta)}</p>'
            "</header>"
            + self.toggle()
            + "".join(self.state(n, b, r) for n, b, r in self.states)
            + self.transcript(before_res)
            + '<footer class="end"><p>PromiseWatch shows options. It <em>never</em> acts: '
            "nothing is sent or changed from this page.</p></footer>"
        )
        return TEMPLATE.replace("{{TITLE}}", e(f"PromiseWatch · {self.run_name}")).replace(
            "{{BODY}}", body)


def render(run: Path, bundle: Path = Path("data/bundle.toml")) -> str:
    saved = json.loads(run.read_text())
    return Page(capture(bundle), run.stem, saved).html()


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root {
  --bg: #102c27; --panel: #163a32; --panel-2: #1c463c; --rule: #2f5a4e;
  --ink: #f2f4e9; --soft: #adc3b7; --pale: #cdf194; --on-pale: #14352e;
  --warm: #ffb78c;
  --sans: Arial, Helvetica, sans-serif;
  --serif: Georgia, serif;
}
* { box-sizing: border-box; }
html { background: var(--bg); }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 var(--sans); }
main { max-width: 780px; margin: 0 auto; padding: 32px 16px 64px; }
em { font-family: var(--serif); font-style: italic; font-weight: 400; }
h1, h2, h3, h4 { font-weight: 800; letter-spacing: -0.01em; margin: 0; }
h1 { font-size: clamp(28px, 6vw, 44px); line-height: 1.1; margin: 8px 0 12px; }
h1 em { color: var(--pale); }
h2 { font-size: 22px; margin: 40px 0 12px; }
h2 em { color: var(--pale); }
h3 { font-size: 21px; line-height: 1.25; }
h4 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--soft); margin: 20px 0 8px; }
.brand { font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase; font-size: 13px; color: var(--pale); margin: 0; }
.meta { color: var(--soft); font-size: 14px; margin: 0; }
.confirm { position: sticky; top: 0; z-index: 2; background: var(--bg); padding: 14px 0; margin-top: 20px; border-bottom: 1px solid var(--rule); }
.confirm p { margin: 8px 0 0; color: var(--soft); font-size: 14px; }
button { font: 700 15px/1.2 var(--sans); border-radius: 999px; padding: 11px 18px; cursor: pointer; }
#confirm, .confirm button { background: var(--pale); color: var(--on-pale); border: 2px solid var(--pale); }
#confirm[aria-pressed="true"] { background: transparent; color: var(--pale); }
.confirm button[disabled] { opacity: .55; cursor: not-allowed; }
.issues { border: 2px solid var(--warm); border-radius: 14px; padding: 4px 18px 14px; margin-top: 24px; }
.issues h2 { margin-top: 14px; color: var(--warm); font-size: 19px; }
.issues.clean { border: 1px solid var(--rule); }
.issues.clean h2 { color: var(--soft); }
.issues ul { padding-left: 18px; margin: 8px 0 0; }
.issues li { margin: 6px 0; }
.card { background: var(--panel); border: 1px solid var(--rule); border-radius: 16px; padding: 20px; margin: 16px 0; }
.card.lv-HIGH { border: 2px solid var(--warm); }
.card.lv-MEDIUM { border: 2px solid var(--pale); }
.eyebrow { color: var(--soft); font-size: 14px; margin: 0 0 6px; }
.marks { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0 0; }
.status, .level { font-weight: 800; font-size: 13px; letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 5px 12px; }
.status { border: 1px solid var(--soft); color: var(--ink); }
.level { background: var(--pale); color: var(--on-pale); }
.lv-HIGH .level { background: var(--warm); }
.level.plain { background: transparent; color: var(--soft); text-transform: none; letter-spacing: 0; font-weight: 600; border: 1px solid var(--rule); }
.calm { color: var(--soft); }
dl.when { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }
dl.when dt { color: var(--soft); }
dl.when dd { margin: 0; font-weight: 600; }
ol.reasons { padding-left: 20px; margin: 0; }
ol.reasons li { margin: 0 0 14px; }
ol.reasons p { margin: 0 0 6px; }
.code { display: inline-block; background: var(--panel-2); border: 1px solid var(--rule); border-radius: 6px; padding: 0 7px; margin-right: 4px; font-size: 13px; }
blockquote.src { margin: 6px 0; padding: 8px 12px; border-left: 3px solid var(--pale); background: var(--panel-2); border-radius: 0 10px 10px 0; }
blockquote.src p { margin: 0; font-family: var(--serif); font-style: italic; font-size: 17px; overflow-wrap: anywhere; }
blockquote.src footer { font-size: 12.5px; color: var(--soft); margin-top: 4px; overflow-wrap: anywhere; }
.tag { display: inline-block; margin-left: 8px; color: var(--on-pale); background: var(--warm); font-weight: 800; font-style: normal; border-radius: 6px; padding: 0 6px; }
.ref { margin: 4px 0; font-size: 14px; color: var(--soft); }
.link.on { color: var(--pale); font-weight: 700; }
.link.off { color: #8fa79a; }
.question { font-weight: 800; color: var(--warm); }
.note, .stop { color: var(--warm); }
.missing { border-top: 1px dashed var(--rule); margin-top: 18px; }
.missing ul { margin: 0; padding-left: 18px; }
.missing p { color: var(--soft); font-size: 14px; margin: 6px 0 0; }
.flag { border: 1px solid var(--warm); border-radius: 12px; padding: 4px 14px 10px; margin: 10px 0; }
.options { border-top: 1px solid var(--rule); margin-top: 20px; }
.option { display: block; width: 100%; text-align: left; margin: 8px 0; background: transparent; color: var(--ink); border: 1px solid var(--soft); border-radius: 12px; }
.option:hover, .option:focus-visible { border-color: var(--pale); outline: none; }
.option-note { min-height: 1em; color: var(--pale); font-size: 14px; margin: 4px 0; }
.nobody { margin: 12px 0 0; }
.nobody b { display: block; font-size: 13px; text-transform: uppercase; letter-spacing: .08em; color: var(--warm); }
.money { background: var(--panel); border: 1px solid var(--rule); border-radius: 14px; padding: 14px 16px; margin: 10px 0; }
.money .amount { font-size: 26px; font-weight: 800; margin: 0; }
.money .dir { margin: 0; font-weight: 700; color: var(--pale); }
.money.payable .dir { color: var(--warm); }
.money .for { margin: 4px 0; color: var(--soft); font-size: 14px; }
.links .why { color: var(--soft); margin-top: -6px; }
details { border: 1px solid var(--rule); border-radius: 12px; padding: 8px 14px; margin: 10px 0; }
summary { font-weight: 800; cursor: pointer; }
summary span { color: var(--soft); font-weight: 600; font-size: 13px; margin-left: 6px; }
.line.marked blockquote { border-left-color: var(--warm); }
.end { margin-top: 48px; color: var(--soft); border-top: 1px solid var(--rule); padding-top: 16px; }
[hidden] { display: none !important; }
</style>
</head>
<body>
<main>
{{BODY}}
</main>
<script>
(function () {
  var b = document.getElementById("confirm");
  if (b) b.addEventListener("click", function () {
    var on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.textContent = on ? b.dataset.on : b.dataset.off;
    document.querySelectorAll(".state").forEach(function (s) {
      s.hidden = s.dataset.state !== (on ? "after" : "before");
    });
    document.getElementById("confirm-note").innerHTML = on
      ? "Showing the result <em>after</em> a human confirms the proposed link. Both results were computed by the rules engine."
      : "Showing the result <em>before</em> a human confirms the proposed link. Both results were computed by the rules engine.";
  });
  document.querySelectorAll(".option").forEach(function (o) {
    o.addEventListener("click", function () {
      o.parentNode.querySelector(".option-note").textContent =
        "Nothing was sent or changed. PromiseWatch only shows options; the decision and the action are yours.";
    });
  });
})();
</script>
</body>
</html>
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run", type=Path, help="a saved run in data/runs/")
    ap.add_argument("--bundle", type=Path, default=Path("data/bundle.toml"))
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args(argv)
    out = args.out or Path("docs/demo") / f"{args.run.stem}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(args.run, args.bundle))
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
