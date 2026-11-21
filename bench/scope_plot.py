#!/usr/bin/env python3
"""Replot WaveForms (Analog Discovery) scope exports in the bench's plot style.

In WaveForms: Scope > File > Export > Data, CSV. Then:

    python scope_plot.py svpwm.csv --title "SVPWM: phase voltage and line-to-line" \\
        --labels "phase A (filtered)" "phase B (filtered)" --diff "A - B" -o svpwm.png
    python scope_plot.py ia.csv --title "Phase current via DAC" --labels "i_a" \\
        --scale 0.5 --offset 1.65 --unit A -o ia.png        # undo 1.65 V + 2 V/A

--diff adds channel 1 - channel 2 as a third trace (line-to-line voltage).
--offset is subtracted, then --scale multiplies (both applied to every channel).
"""
from __future__ import annotations

import argparse
import csv
import sys

import numpy as np

import report  # sets the shared style and palette
import matplotlib.pyplot as plt


def load_waveforms_csv(path: str) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Skip '#' metadata lines, take the first non-numeric row as the header."""
    header, rows = None, []
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.reader(f):
            if not row or row[0].lstrip().startswith("#"):
                continue
            try:
                rows.append([float(x) for x in row if x.strip() != ""])
            except ValueError:
                if header is None and not rows:
                    header = [h.strip() for h in row]
    a = np.array([r for r in rows if len(r) == len(rows[0])])
    if a.ndim != 2 or a.shape[1] < 2:
        raise ValueError(f"{path}: no time + channel columns found")
    names = header[1:a.shape[1]] if header else [f"Channel {i}" for i in range(1, a.shape[1])]
    return a[:, 0], a[:, 1:], names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("-o", "--out", default=None, help="png path (default: next to the csv)")
    ap.add_argument("--title", default="")
    ap.add_argument("--labels", nargs="*", default=None)
    ap.add_argument("--diff", default=None, metavar="LABEL", help="also plot ch1 - ch2 with this label")
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--unit", default="V")
    ap.add_argument("--tunit", default="ms", choices=["s", "ms", "us"])
    ap.add_argument("--smooth", type=int, default=1, help="moving average, samples")
    args = ap.parse_args(argv)

    t, y, names = load_waveforms_csv(args.csv)
    y = (y - args.offset) * args.scale
    if args.smooth > 1:
        k = np.ones(args.smooth) / args.smooth
        y = np.column_stack([np.convolve(y[:, i], k, mode="same") for i in range(y.shape[1])])
    ts = {"s": 1.0, "ms": 1e3, "us": 1e6}[args.tunit]
    labels = args.labels or names
    colors = [report.S1, report.S2, report.S3]

    fig, ax = plt.subplots(figsize=(9.0, 3.2))
    for i in range(y.shape[1]):
        ax.plot((t - t[0]) * ts, y[:, i], color=colors[i % 3], lw=1.3,
                label=labels[i] if i < len(labels) else names[i])
    if args.diff and y.shape[1] >= 2:
        ax.plot((t - t[0]) * ts, y[:, 0] - y[:, 1], color=report.INK_2, lw=1.3, ls=(0, (4, 2)), label=args.diff)
    ax.set_xlabel(f"time [{args.tunit}]")
    ax.set_ylabel(f"[{args.unit}]")
    if args.title:
        ax.set_title(args.title, pad=18)
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, 0.98), ncol=4)
    fig.tight_layout()
    out = args.out or args.csv.rsplit(".", 1)[0] + ".png"
    fig.savefig(out, dpi=160)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
