"""Plots, raw data and the Markdown test report."""
from __future__ import annotations

import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import analysis as an
from spec import REQUIREMENTS, CHARACTERIZATION

# palette (validated categorical slots 1-3, light surface) + neutral ink for references
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
S1, S2, S3 = "#2a78d6", "#eb6834", "#1baf7a"
BAND = "#2a78d6"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
    "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 9, "xtick.color": INK_2, "ytick.color": INK_2,
    "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.spines.top": False, "axes.spines.right": False,
    "legend.frameon": False, "legend.fontsize": 8, "legend.labelcolor": INK_2,
    "lines.linewidth": 1.5, "font.family": "DejaVu Sans",
})


def _ref(ax, t, y, label):
    ax.plot(t, y, color=INK_2, lw=1.2, ls=(0, (4, 3)), label=label, zorder=3)


def _reps(ax, caps, col, color, label, scale=1.0, tscale=1e3, shift=True):
    for i, c in enumerate(caps):
        tt = (c.t - (c.t_step if shift else 0)) * tscale
        ax.plot(tt, c.data[:, col] * scale, color=color, alpha=1.0 if i == 0 else 0.35,
                lw=1.5 if i == 0 else 1.0, label=label if i == 0 else None, zorder=4 - i * 0.01)


def _model(ax, t, y, t_step, win=None):
    tt = (t - t_step) * 1e3
    m = slice(None) if win is None else win
    ax.plot(tt[m], y[m], color=S3, lw=1.6, ls=(0, (1.5, 1.5)), label="model prediction", zorder=5)


def plot_cur(caps, path, model=None):
    fig, ax = plt.subplots(figsize=(7.2, 3.6))
    c0 = caps[0]
    win = (c0.t - c0.t_step > -0.002) & (c0.t - c0.t_step < 0.012)
    sub = [type(c)(c.name, c.t[win], c.t_step, c.data[win], c.channels) for c in caps]
    y0, y1 = sub[0].data[0, 0], sub[0].data[-1, 0]
    dy = y1 - y0
    tt = (sub[0].t - sub[0].t_step) * 1e3
    ax.axhspan(y1 - 0.05 * dy, y1 + 0.05 * dy, color=BAND, alpha=0.08, lw=0, label="5 % band")
    _ref(ax, tt, sub[0].data[:, 0], "id command")
    _reps(ax, sub, 1, S1, f"id measured ({len(caps)} runs)")
    _reps(ax, sub, 2, S2, "iq (should stay at 0)")
    if model is not None:
        _model(ax, model[0], model[1], c0.t_step, win)
    ax.set_xlabel("time from step [ms]")
    ax.set_ylabel("current [A]")
    ax.set_title("Current loop: d-axis step response")
    ax.legend(loc="center right")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_spd(caps, path, model=None):
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.2, 4.8), sharex=True,
                                 gridspec_kw={"height_ratios": [2.2, 1]})
    c0 = caps[0]
    tt = (c0.t - c0.t_step) * 1e3
    y1 = c0.data[-1, 0]
    y0 = c0.data[0, 0]
    dy = y1 - y0
    a1.axhspan(y1 - 0.05 * dy, y1 + 0.05 * dy, color=BAND, alpha=0.08, lw=0, label="5 % band")
    _ref(a1, tt, c0.data[:, 0], "speed command")
    _reps(a1, caps, 1, S1, f"measured speed ({len(caps)} runs)")
    if model is not None:
        _model(a1, model[0], model[1], c0.t_step)
    a1.set_ylabel("speed [rad/s]")
    a1.set_title("Speed loop: 5 to 15 rad/s step")
    a1.legend(loc="lower right")
    _reps(a2, caps, 2, S2, "iq command")
    a2.set_ylabel("iq cmd [A]")
    a2.set_xlabel("time from step [ms]")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_ripple(caps, path, model=None):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 3.4), gridspec_kw={"width_ratios": [1.5, 1]})
    c0 = caps[0]
    _ref(a1, c0.t, c0.data[:, 0], "command")
    a1.plot(c0.t, c0.data[:, 1], color=S1, lw=1.0, label="measured")
    a1.set_xlabel("time [s]")
    a1.set_ylabel("speed [rad/s]")
    a1.set_title("Speed held at 10 rad/s", pad=18)
    a1.legend(loc="lower right", bbox_to_anchor=(1.0, 0.98), ncol=2)

    th = np.concatenate([c.data[:, 3] for c in caps])
    v = np.concatenate([c.data[:, 1] for c in caps])
    a2.scatter(np.degrees(th), v, s=2, color=S1, alpha=0.12, lw=0)
    centers, means = an.bin_by_angle(th, v)
    a2.plot(np.degrees(centers), means, color=S2, lw=1.8, label="mean per 5°")
    a2.set_xlim(0, 360)
    a2.set_xticks([0, 90, 180, 270, 360])
    a2.set_xlabel("rotor angle [deg]")
    a2.set_title("Speed vs rotor angle", pad=18)
    a2.legend(loc="lower right", bbox_to_anchor=(1.0, 0.98))
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def plot_rl(caps, path, model=None):
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    c0 = caps[0]
    win = (c0.t - c0.t_step > -0.001) & (c0.t - c0.t_step < 0.008)
    sub = [type(c)(c.name, c.t[win], c.t_step, c.data[win], c.channels) for c in caps]
    _reps(ax, sub, 1, S1, f"id ({len(caps)} runs)")
    ax.set_xlabel("time from 1 V d-axis step [ms]")
    ax.set_ylabel("current [A]")
    ax.set_title("R/L identification: d-axis voltage step")
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


PLOTS = {"cur": plot_cur, "spd": plot_spd, "ripple": plot_ripple, "rl": plot_rl}


def _fmt(vals, digits=3):
    m, s = an.mean_std(vals)
    if not math.isfinite(m):
        return "n/a"
    if len(vals) > 1:
        return f"{m:.{digits}g} ± {s:.2g}"
    return f"{m:.{digits}g}"


def write(ctx, out_dir, meta, ran):
    os.makedirs(os.path.join(out_dir, "plots"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "raw"), exist_ok=True)

    for test, caps in ctx.captures.items():
        for i, c in enumerate(caps):
            np.savetxt(os.path.join(out_dir, "raw", f"{test}_{i + 1}.csv"),
                       np.column_stack([c.t, c.data]), delimiter=",",
                       header="t [s]," + ",".join(c.channels), comments="")
        if test in PLOTS:
            PLOTS[test](caps, os.path.join(out_dir, "plots", f"{test}.png"), ctx.models.get(test))

    rows, passed, total = [], 0, 0
    for r in REQUIREMENTS:
        if r.test not in ran:
            continue
        vals = ctx.metrics.get(r.metric, [])
        mean, _ = an.mean_std(vals)
        verdict = r.check(mean) if vals else None
        if r.op == "==":
            meas = "yes" if mean == 1 else "no"
        else:
            meas = f"{_fmt(vals)} {r.unit}"
        res = {True: "✅ PASS", False: "❌ FAIL", None: "⚠️ NO DATA"}[verdict]
        total += 1
        passed += verdict is True
        pv = ctx.metrics.get(r.metric + "_model")
        pred = f"{pv[0]:.3g} {r.unit}" if pv and math.isfinite(pv[0]) else "–"
        rows.append(f"| {r.id} | {r.text} | {r.limit_text} | {pred} | {meas} | {res} |")

    char = []
    for key, text, unit, test in CHARACTERIZATION:
        if key in ctx.metrics:
            pv = ctx.metrics.get(key + "_model")
            pred = f" (model {pv[0]:.3g} {unit})" if pv and math.isfinite(pv[0]) else ""
            char.append(f"| {text} | {_fmt(ctx.metrics[key])} {unit}{pred} |")

    c = ctx.conditions
    L = []
    L.append("# Custom FOC ESC: Test Report\n")
    L.append(f"**{passed} / {total} requirements passed** · {meta['date']} · "
             f"N = {ctx.reps} runs per test\n")
    L.append("## Conditions\n")
    L.append("| | |\n|---|---|")
    L.append(f"| Firmware build | {meta['build']} (protocol v{meta['proto']}) |")
    L.append(f"| Host commit | `{meta['git']}` |")
    L.append(f"| Bus voltage | {c.get('vbus', float('nan')):.2f} V (KD3005P, 0.5 A limit) |")
    L.append(f"| Motor | GM4108H-120T, {meta.get('pole_pairs', 11)} pole pairs, no load |")
    L.append(f"| Current gains | Kp {c.get('kp_i', float('nan')):.3g}, Ki {c.get('ki_i', float('nan')):.4g}"
             f"{' (from measured R, L)' if meta.get('tuned') else ' (firmware defaults)'} |")
    L.append(f"| Speed gains | Kp {c.get('kp_w', float('nan')):.3g}, Ki {c.get('ki_w', float('nan')):.3g} |")
    if meta.get("note"):
        L.append(f"| Notes | {meta['note']} |")
    L.append("")
    L.append("## Requirements\n")
    L.append("Predicted values come from a model of the firmware's control loops using the "
             "R, L, Kt and J measured in this same run, so they test the design math, not just the hardware.\n")
    L.append("| ID | Requirement | Limit | Predicted | Measured (mean ± std) | Result |")
    L.append("|---|---|---|---|---|---|")
    L.extend(rows)
    L.append("")
    if char:
        L.append("## Characterization\n")
        L.append("| Quantity | Measured |\n|---|---|")
        L.extend(char)
        L.append("")
    L.append("## Results\n")
    titles = {"rl": "R/L identification", "cur": "Current loop step", "spd": "Speed loop step",
              "ripple": "Speed ripple"}
    for test in ("cur", "spd", "ripple", "rl"):
        if test in ctx.captures:
            L.append(f"### {titles[test]}\n")
            L.append(f"![{titles[test]}](plots/{test}.png)\n")
            for n in ctx.notes.get(test, []):
                L.append(f"> {n}\n")
    L.append("## Method\n")
    L.append("Run with `python run_bench.py` (see `bench/README.md`). The firmware applies each step "
             "at an exact control-loop sample and records 2048 samples to RAM; the host downloads "
             "the capture over UART and computes every metric from it. Raw captures are in `raw/` "
             "as CSV.\n")
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump({"meta": meta, "conditions": c, "metrics": ctx.metrics}, f, indent=2, default=float)
    return passed, total
