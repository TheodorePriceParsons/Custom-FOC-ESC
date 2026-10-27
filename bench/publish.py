#!/usr/bin/env python3
"""Put a bench run into the repo README.

    python bench/publish.py bench/results/2026-10-27_101500

Copies the run's plots to docs/images/bench/ and rewrites the block between
<!-- bench:start --> and <!-- bench:end --> in README.md with the requirements
table, the plots and a link to the full report. Run it only for runs you want to show;
commit the run folder along with the README.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from report import requirement_rows  # noqa: E402

ROOT = os.path.dirname(HERE)
README = os.path.join(ROOT, "README.md")
IMG_DIR = os.path.join(ROOT, "docs", "images", "bench")
START, END = "<!-- bench:start -->", "<!-- bench:end -->"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="results folder of the run to publish")
    ap.add_argument("--allow-sim", action="store_true", help="publish a simulator run (testing only)")
    args = ap.parse_args()

    run = os.path.abspath(args.run)
    with open(os.path.join(run, "results.json")) as f:
        res = json.load(f)
    meta = res["meta"]
    if meta.get("sim") and not args.allow_sim:
        sys.exit("refusing to publish a simulator run (use --allow-sim to test)")

    os.makedirs(IMG_DIR, exist_ok=True)
    plots = [p for p in ("cur", "spd", "ripple") if os.path.exists(os.path.join(run, "plots", f"{p}.png"))]
    for p in plots:
        shutil.copyfile(os.path.join(run, "plots", f"{p}.png"), os.path.join(IMG_DIR, f"{p}.png"))

    rows = requirement_rows(res["metrics"], meta["tests"])
    passed = sum(r["verdict"] is True for r in rows)
    report_rel = os.path.relpath(os.path.join(run, "report.md"), ROOT).replace(os.sep, "/")

    B = [START, ""]
    B.append(f"**{passed} / {len(rows)} requirements passed** on {meta['date']} "
             f"(firmware `{meta['git']}`, {res.get('conditions', {}).get('vbus', 12):.1f} V bus, "
             f"N = {meta.get('reps', 3)} runs per test{', ' + meta['note'] if meta.get('note') else ''}). "
             f"[Full test report]({report_rel})")
    B.append("")
    B.append("| ID | Requirement | Limit | Predicted | Measured | Result |")
    B.append("|---|---|---|---|---|---|")
    for r in rows:
        B.append(f"| {r['id']} | {r['text']} | {r['limit']} | {r['predicted']} | {r['measured']} | {r['result']} |")
    B.append("")
    imgs = {"cur": "Current loop step", "spd": "Speed loop step", "ripple": "Speed ripple"}
    if plots:
        B.append("<p>")
        for p in plots[:2]:
            B.append(f'  <img src="docs/images/bench/{p}.png" alt="{imgs[p]}" width="49%">')
        B.append("</p>")
        if "ripple" in plots:
            B.append("")
            B.append('<img src="docs/images/bench/ripple.png" alt="Speed ripple" width="98%">')
    B.append("")
    B.append(END)

    with open(README, encoding="utf-8") as f:
        text = f.read()
    if START not in text or END not in text:
        sys.exit(f"README.md has no {START} ... {END} block")
    text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: "\n".join(B), text, flags=re.S)
    with open(README, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"README updated: {passed}/{len(rows)} passed, plots: {', '.join(plots)}")
    print(f"commit: README.md docs/images/bench/ {os.path.relpath(run, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
