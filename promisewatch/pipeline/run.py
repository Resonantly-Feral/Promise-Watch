"""Run Pass 2 on a declared bundle and compare every stage with its answer key.

    python -m promisewatch.pipeline.run                 # call the model, save the run
    python -m promisewatch.pipeline.run --replay FILE   # re-check a saved run, no model call

Each live run is saved under data/runs/ so it can be replayed and scored
again without calling the model.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from promisewatch.pipeline.capture import capture
from promisewatch.pipeline.compare import compare, first_divergence
from promisewatch.pipeline.extract import ExtractionError, extract, load_settings


def next_run_path(runs: Path, model: str) -> Path:
    runs.mkdir(parents=True, exist_ok=True)
    n = len(list(runs.glob(f"{model}-*.json"))) + 1
    return runs / f"{model}-{n:03d}.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bundle", type=Path, default=Path("data/bundle.toml"))
    ap.add_argument("--replay", type=Path, help="a saved run to check instead of calling the model")
    args = ap.parse_args(argv)

    cap = capture(args.bundle)
    if args.replay:
        saved = json.loads(args.replay.read_text())
        drafts, label = saved["drafts"], f"replay of {args.replay}"
    else:
        settings = load_settings()
        try:
            drafts = extract(cap, settings)
        except ExtractionError as e:
            print(f"Extraction did not run: {e}", file=sys.stderr)
            print("Capture-only check follows.\n", file=sys.stderr)
            drafts = None
            label = "capture only"
        else:
            out = next_run_path(args.bundle.parent / "runs", settings.model)
            out.write_text(json.dumps(
                {"provider": settings.provider, "model": settings.model, "drafts": drafts},
                indent=2, ensure_ascii=False,
            ) + "\n")
            label = f"live run with {settings.model}, saved to {out}"

    checks = compare(cap, drafts)
    print(f"Pass 2, bundle '{cap.bundle_id}' ({label})\n")
    stage = None
    for c in checks:
        if c.stage != stage:
            stage = c.stage
            print(f"{stage}")
        print(f"  {'PASS' if c.ok else 'FAIL'}  {c.name}")
        if not c.ok and c.detail:
            print(f"        {c.detail}")
    failed = [c for c in checks if not c.ok]
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks pass.")
    if failed:
        print(f"First divergence: {first_divergence(checks)}")
    return 1 if failed or drafts is None else 0


if __name__ == "__main__":
    sys.exit(main())
