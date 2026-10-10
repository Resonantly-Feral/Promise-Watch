"""Build the public site in docs/: demo pages and the scorecard.

    python -m promisewatch.site

docs/index.html (front page) and docs/story.html (the story) are written by
hand. This script writes docs/demo/<run>.html for every saved run and
docs/scorecard.html from results computed now:

- Pass 1: the 25 test-set cases (P01-P24, P17b) run through pytest, plus the
  engine's own result for each case's records.
- Pass 2: the stage comparison for every saved run in data/runs/.

Marks (CLAUDE.md, Tests): R right, F flagged correctly, W wrong with the
error flagged, X wrong with no relevant flag. How each mark is derived is
stated on the page.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from promisewatch.page import TEMPLATE, e, render
from promisewatch.pipeline.build import build
from promisewatch.pipeline.capture import capture
from promisewatch.pipeline.compare import CJ, ME, SH, STAGES, compare, first_divergence
from promisewatch.rules import evaluate

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RUNS = ROOT / "data" / "runs"
BUNDLE = ROOT / "data" / "bundle.toml"
PASS1 = ROOT / "tests" / "test_pass1_rules.py"
# The demo bundle's two expected promises: promisor and promisee.
CASES = {"printer": (CJ, ME), "customer": (ME, SH)}


# ------------------------------------------------------------------ Pass 1


class Collect:
    def __init__(self):
        self.outcomes: dict[str, str] = {}

    def pytest_runtest_logreport(self, report):
        if report.when == "call" or report.outcome != "passed":
            name = report.nodeid.split("::")[-1]
            if self.outcomes.get(name) != "failed":
                self.outcomes[name] = report.outcome


def pass1() -> list[dict]:
    sys.path.insert(0, str(ROOT))
    from tests import fixtures as fx

    plugin = Collect()
    pytest.main([str(PASS1), "-q", "-p", "no:cacheprovider", "--no-header", "-o",
                 "addopts="], plugins=[plugin])
    rows = []
    for name, outcome in sorted(plugin.outcomes.items()):
        m = re.match(r"test_(p\d\d[a-z]?)_(.*)", name)
        if not m:
            continue
        case = m.group(1)[:3].upper() + m.group(1)[3:]  # "p17b" -> "P17b"
        result = evaluate(fx.ALL[case]())
        shown = []
        for a in result.assessments.values():
            if a.stop:
                shown.append(f"{a.promise_id}: {a.status_label}, stopped: {a.stop.question}")
            else:
                shown.append(f"{a.promise_id}: {a.status_label}, {a.display}")
        flags = sorted({f.kind.value for f in result.flags})
        stop_or_flag_only = all(a.stop for a in result.assessments.values())
        if outcome != "passed":
            mark = "W/X"
        else:
            mark = "F" if stop_or_flag_only else "R"
        rows.append(dict(case=case, title=m.group(2).replace("_", " "), outcome=outcome,
                         mark=mark, shown=shown, flags=flags))
    return sorted(rows, key=lambda r: (int(r["case"][1:3]), r["case"]))


# ------------------------------------------------------------------ Pass 2


def pass2(run: Path) -> dict:
    cap = capture(BUNDLE)
    saved = json.loads(run.read_text())
    drafts = saved["drafts"]
    checks = compare(cap, drafts)
    # The full list of checks, from a run where every stage was reached.
    reference = [c.name for c in compare(cap, _reference_drafts())]
    by_name = {c.name: c for c in checks}
    issues = build(cap, drafts).issues
    marks = {}
    for case, parties in CASES.items():
        names = [n for n in reference if case in n]
        ok = all(n in by_name and by_name[n].ok for n in names)
        own = own_issues(drafts, issues, parties)
        marks[case] = "R" if ok else ("W" if own else "X")
    stages = []
    for stage in STAGES:
        mine = [c for c in checks if c.stage == stage]
        stages.append(dict(stage=stage, passed=sum(c.ok for c in mine), total=len(mine),
                           failed=[(c.name, c.detail) for c in mine if not c.ok]))
    return dict(run=run.stem, model=saved.get("model", "unknown"), stages=stages,
                marks=marks, divergence=first_divergence(checks),
                passed=sum(c.ok for c in checks), total=len(checks),
                issues=[f"{i.item}: {i.text}" for i in issues])


def own_issues(drafts: dict, issues, parties: tuple[str, str]) -> list:
    """Validation issues that name this case's own promise, or a link to or
    from it. Only these make a wrong case W; any other issue leaves it X."""
    pids = {p["id"] for p in drafts.get("promises", [])
            if (p["promisor"], p["promisee"]) == parties}
    items = {f"promise {pid}" for pid in pids}
    for n, l in enumerate(drafts.get("links", []), 1):
        if l["upstream"] in pids or l["downstream"] in pids:
            items.add(f"link {n}")
    return [i for i in issues if i.item in items]


def _reference_drafts() -> dict:
    sys.path.insert(0, str(ROOT))
    from tests.test_demo_bundle import drafts

    return drafts()


# -------------------------------------------------------------------- page


def counts(marks) -> str:
    marks = list(marks)
    return " · ".join(f"{k} {marks.count(k)}" for k in ("R", "F", "W", "X")) + f" · of {len(marks)}"


def scorecard(p1: list[dict], p2: list[dict]) -> str:
    out = ['<header class="top"><p class="brand"><a href="index.html">PromiseWatch</a></p>',
           "<h1>Scorecard, <em>every case counted.</em></h1>",
           '<p class="meta">Computed by <code>python -m promisewatch.site</code> from the tests and '
           "the saved runs. Reference time Thursday 15/10/2026, 09:00 Malaysia time.</p></header>",
           '<section class="legend"><h2>Marks</h2><dl class="when">'
           "<dt>R</dt><dd>right</dd><dt>F</dt><dd>flagged correctly: the right answer is a stop or a flag, "
           "and the engine gave it</dd><dt>W</dt><dd>wrong, with the specific error flagged</dd>"
           "<dt>X</dt><dd>wrong, with no relevant flag</dd></dl></section>"]

    out.append(f'<section><h2>Pass 1, <em>rules only</em></h2><p class="big">{e(counts(r["mark"] for r in p1))}</p>'
               "<p><b>These 25 are rules-only.</b> No AI is involved: hand-written records for each "
               "test-set case go straight to the rules engine. "
               "A case passes when its test asserts the complete expected result. "
               "Passed cases are marked F when every record in the case stopped (rule 17) "
               "or the case has flags only, and R otherwise. A failed case would need a "
               "person to mark it W or X.</p>"
               '<table class="p1"><thead><tr><th>Case</th><th>Test</th><th>Mark</th><th>Engine result</th></tr></thead><tbody>')
    for r in p1:
        shown = "<br>".join(e(s) for s in r["shown"]) or "<i>no promise record</i>"
        if r["flags"]:
            shown += f'<br><span class="dim">flags: {e(", ".join(r["flags"]))}</span>'
        out.append(f'<tr><td><b>{e(r["case"])}</b></td><td>{e(r["title"])}<br>'
                   f'<span class="dim">{e(r["outcome"])}</span></td>'
                   f'<td class="mark m-{e(r["mark"][0])}">{e(r["mark"])}</td><td>{shown}</td></tr>')
    out.append("</tbody></table></section>")

    out.append('<section><h2>Pass 2, <em>full pipeline</em></h2>'
               "<p><b>One bundle, two runs.</b> The demo bundle's raw messages and documents go through "
               "the whole system, AI included, once per saved run. "
               "Each run was made once and kept; none was re-rolled. A case is R when every "
               "check that names it passes. Otherwise it is W if a validation issue shown next to "
               "the warnings names that case's own promise or its link, and X if none does.</p>")
    for r in p2:
        out.append(f'<div class="run"><h3>Run {e(r["run"][-3:])} <span class="dim">· {e(r["model"])}</span></h3>'
                   f'<p class="big">{e(counts(r["marks"].values()))}</p>'
                   f'<p>{r["passed"]} of {r["total"]} checks pass'
                   + (f' · first divergence: <b>{e(r["divergence"])}</b>' if r["divergence"] else "")
                   + f' · <a href="demo/{e(r["run"])}.html">open the demo page</a></p>'
                   '<table><thead><tr><th>Stage</th><th>Checks</th><th>Failed</th></tr></thead><tbody>')
        for s in r["stages"]:
            total = f'{s["passed"]} / {s["total"]}' if s["total"] else '<span class="dim">not reached</span>'
            failed = "<br>".join(f"{e(n)}<br><span class=\"dim\">{e(d)}</span>" for n, d in s["failed"])
            out.append(f'<tr><td>{e(s["stage"])}</td><td>{total}</td><td>{failed}</td></tr>')
        out.append("</tbody></table>")
        out.append("<p>" + " · ".join(f'{e(c)}: <b class="m-{e(m)}">{e(m)}</b>'
                                      for c, m in r["marks"].items()) + "</p>")
        if r["issues"]:
            out.append('<p class="dim">Validation issues shown on the page: '
                       + "; ".join(e(i) for i in r["issues"]) + "</p>")
        out.append("</div>")
    out.append("</section>")
    style = """<style>
table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 14px; }
th, td { text-align: left; vertical-align: top; padding: 10px 8px; border-top: 1px solid var(--rule); }
th { color: var(--soft); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
.mark { font-weight: 800; font-size: 18px; }
.m-R, .m-F { color: var(--pale); } .m-W, .m-X { color: var(--warm); }
.big { font-size: 26px; font-weight: 800; margin: 6px 0; }
.dim { color: var(--soft); font-size: 13px; }
.run { background: var(--panel); border: 1px solid var(--rule); border-radius: 16px; padding: 18px; margin: 16px 0; overflow-x: auto; }
.brand a { text-decoration: none; color: inherit; }
a { color: var(--pale); }
@media (max-width: 600px) { .p1 th:nth-child(2), .p1 td:nth-child(2) { display: none; } }
</style>"""
    return (TEMPLATE.replace("{{TITLE}}", "PromiseWatch · Scorecard")
            .replace("{{BODY}}", style + "".join(out)
                     + '<footer class="end"><p><a href="index.html">Back to the front page</a></p></footer>'))


def main() -> int:
    (DOCS / "demo").mkdir(parents=True, exist_ok=True)
    runs = sorted(RUNS.glob("*.json"))
    for run in runs:
        (DOCS / "demo" / f"{run.stem}.html").write_text(render(run, BUNDLE))
    p1 = pass1()
    p2 = [pass2(run) for run in runs]
    (DOCS / "scorecard.html").write_text(scorecard(p1, p2))
    print(f"Pass 1: {counts(r['mark'] for r in p1)}")
    for r in p2:
        print(f"Pass 2 {r['run']}: {counts(r['marks'].values())}, {r['passed']}/{r['total']} checks")
    print(f"Wrote docs/demo/ ({len(runs)} runs) and docs/scorecard.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
