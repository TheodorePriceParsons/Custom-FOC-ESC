#!/usr/bin/env python3
"""Hold the motor in a steady state for scope captures, with an internal signal on the DAC.

    python scope_setup.py --port COM3 --signal ia --speed 10 --id 0.3     # phase current hero shot
    python scope_setup.py --port COM3 --signal off --speed 25             # SVPWM saddle (scope the phases)
    python scope_setup.py --port COM3 --signal theta_e --speed 10         # electrical angle sawtooth

The DAC is PA4 (Nucleo A2): 1.65 V + gain * signal, so with --gain 2 a 0.3 A sine is +-0.6 V.
Keeps the host watchdog fed until Ctrl+C (or --seconds), then ramps down and goes idle.
Probe grounds go to the supply minus, never to a switch node.
"""
from __future__ import annotations

import argparse
import sys
import time

import suite
from esc_link import EscLink, SerialTransport

SIGNALS = {"off": 0, "ia": 1, "ib": 2, "ic": 3, "iq": 4, "id": 5, "theta_e": 6, "iq_ff": 7, "vel": 8}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="serial port of the Nucleo")
    ap.add_argument("--sil", action="store_true", help="run against the SIL build instead (dry run)")
    ap.add_argument("--signal", default="ia", choices=SIGNALS)
    ap.add_argument("--gain", type=float, default=2.0, help="DAC volts per amp (or per rad/s for vel)")
    ap.add_argument("--speed", type=float, default=10.0, help="mech rad/s, |w| <= 30")
    ap.add_argument("--id", type=float, default=0.0, help="d-axis current to inject, A (no torque)")
    ap.add_argument("--no-cog", action="store_true", help="turn the cogging feedforward off")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until Ctrl+C)")
    args = ap.parse_args(argv)
    if bool(args.port) == bool(args.sil):
        ap.error("give exactly one of --port, --sil")

    if args.sil:
        from sil_transport import SilTransport
        transport = SilTransport()
    else:
        transport = SerialTransport(args.port)
    link = EscLink(transport)
    try:
        link.open()
        if int(link.info.get("proto", 1)) < 2:
            print("firmware is protocol v1: flash the build with the scope DAC first")
            return 1
        suite.preflight(suite.Ctx(link=link, reps=1))
        if args.no_cog:
            link.cmd("COG OFF")
        link.set("dac_gain", args.gain)
        link.set("dac", SIGNALS[args.signal])
        link.set("w", args.speed)
        link.mode("SPEED")
        link.hold(1.0)
        if args.id:
            link.set("id", args.id)
            link.hold(0.3)
        g = link.get()
        print(f"running: {g['vel']:.2f} rad/s, iq {g['iq'] * 1e3:.0f} mA, id {g['id'] * 1e3:.0f} mA, "
              f"DAC = {args.signal} at {args.gain:g} V/unit around 1.65 V. Ctrl+C to stop.")
        t0 = time.monotonic()
        while not args.seconds or time.monotonic() - t0 < args.seconds:
            link.hold(0.5)
    except KeyboardInterrupt:
        print()
    finally:
        try:
            link.set("dac", 0)
        except Exception:
            pass
        link.safe_stop()
        transport.close()
        print("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
