#!/usr/bin/env python3
"""Automated ESC test bench.

    python run_bench.py --port COM5                 # full suite on the board
    python run_bench.py --port COM5 --tests rl,cur  # a subset
    python run_bench.py --sim                       # against the plant simulator
    python run_bench.py --list-ports

Ctrl+C at any time stops the motor (ramp to 0, IDLE, watchdog off).
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import report  # noqa: E402
import suite   # noqa: E402
from esc_link import EscLink, EscError, SerialTransport  # noqa: E402


def git_rev() -> str:
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=here,
                                      stderr=subprocess.DEVNULL).decode().strip()
        dirty = subprocess.call(["git", "diff", "--quiet"], cwd=here, stderr=subprocess.DEVNULL)
        return rev + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port of the Nucleo (e.g. COM5, /dev/ttyACM0)")
    ap.add_argument("--sim", action="store_true", help="run against the simulator")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("-n", "--reps", type=int, default=3, help="runs per test (default 3)")
    ap.add_argument("--tests", default=",".join(suite.DEFAULT_ORDER),
                    help=f"comma list from {','.join(suite.TESTS)} (estop is interactive)")
    ap.add_argument("--tune-current", action="store_true",
                    help="set current PI gains from the measured R and L before the current test")
    ap.add_argument("--align", action="store_true", help="re-run encoder alignment first")
    ap.add_argument("--note", default="", help="free text for the report, e.g. 'temporary magnet mount'")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "results"))
    ap.add_argument("-v", "--verbose", action="store_true", help="print every command and reply")
    args = ap.parse_args()

    if args.list_ports:
        from serial.tools import list_ports
        for p in list_ports.comports():
            print(f"{p.device:12s} {p.description}")
        return 0
    if not args.sim and not args.port:
        ap.error("give --port or --sim")

    tests = [t.strip() for t in args.tests.split(",") if t.strip()]
    for t in tests:
        if t not in suite.TESTS:
            ap.error(f"unknown test '{t}'")
    if "isr" in tests:                         # ISR load is the max over the whole run: do it last
        tests = [t for t in tests if t != "isr"] + ["isr"]

    if args.sim:
        from sim import SimTransport
        transport = SimTransport()
    else:
        transport = SerialTransport(args.port)

    link = EscLink(transport, log=print if args.verbose else None)
    ctx = suite.Ctx(link=link, reps=args.reps, model_delay=0 if args.sim else 1)
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ran = []
    try:
        info = link.open()
        print(f"ESC: build {info.get('build')}, protocol v{info.get('proto')}, "
              f"loop {info.get('f_loop')} Hz, watchdog {link.watchdog_ms} ms")
        print("preflight")
        suite.preflight(ctx, force_align=args.align)
        for t in tests:
            title, fn = suite.TESTS[t]
            print(f"[{t}] {title}")
            if t == "cur" and args.tune_current:
                if "kp_i_design" in ctx.metrics:
                    suite.apply_current_gains(ctx)
                else:
                    print("  --tune-current needs the rl test first; using firmware gains")
            try:
                fn(ctx)
                ran.append(t)
            except EscError as e:
                print(f"  ERROR: {e}")
                link.safe_stop()
                link.cmd(f"WD {link.watchdog_ms}")
    except KeyboardInterrupt:
        print("\ninterrupted: stopping motor")
    except EscError as e:
        print(f"ERROR: {e}")
    finally:
        link.safe_stop()
        transport.close()

    if not ran:
        return 1
    out_dir = os.path.join(args.out, stamp + ("_sim" if args.sim else ""))
    meta = {"date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "build": link.info.get("build", "?"),
            "proto": link.info.get("proto", "?"), "git": git_rev(), "note": args.note,
            "tuned": args.tune_current, "sim": args.sim, "tests": ran,
            "pole_pairs": link.info.get("pole_pairs", 11)}
    passed, total = report.write(ctx, out_dir, meta, ran)
    print(f"\n{passed}/{total} requirements passed. Report: {os.path.join(out_dir, 'report.md')}")
    return 0 if passed == total else 2


if __name__ == "__main__":
    sys.exit(main())
