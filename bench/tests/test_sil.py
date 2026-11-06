"""Firmware tests that run the real foc.c / bench.c on the PC (SIL) and check them against the
plant's ground truth. Skipped if no host C/C++ compiler is installed.

    python -m pytest tests/test_sil.py -v
"""
import math
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not any(shutil.which(c) for c in ("g++", "clang++", "c++")):
    pytest.skip("no host C++ compiler for SIL", allow_module_level=True)

from esc_link import EscLink, EscError, MODES, FAULTS  # noqa: E402
from sil_transport import SilTransport  # noqa: E402

POLE_PAIRS = 11


def make(**params):
    t = SilTransport(params=params)
    link = EscLink(t)
    link.open()
    return t, link


def align(link):
    link.cmd("MODE ALIGN")
    link.hold(2.0)
    st = link.get()
    assert st["aligned"] == 1 and MODES[st["mode"]] == "IDLE", st


@pytest.mark.parametrize("theta0,enc_dir", [(0.9, 1), (4.0, 1), (2.5, -1)])
def test_align_then_current_lands_on_d_axis(theta0, enc_dir):
    """After ALIGN, a d-axis current command must produce current on the TRUE d-axis and
    (almost) no torque. A wrong offset or direction would put part of it on q and spin."""
    t, link = make(theta0=theta0, enc_dir=enc_dir)
    align(link)
    link.set("id", 0.3)
    link.mode("CURRENT")
    link.hold(0.2)
    id_true, iq_true = t.truth("id"), t.truth("iq")
    link.safe_stop()
    assert id_true == pytest.approx(0.3, abs=0.03)
    assert abs(iq_true) < 0.03, f"{iq_true:.3f} A on q: offset or direction wrong"


def test_speed_mode_tracks_true_speed():
    t, link = make()
    align(link)
    link.set("kp_w", 0.02)
    link.set("ki_w", 0.31)
    link.set("w", 10.0)
    link.mode("SPEED")
    link.hold(1.5)
    w_true = t.truth("w")
    link.safe_stop()
    assert w_true == pytest.approx(10.0, rel=0.03)


def test_current_mode_refused_before_alignment():
    t, link = make()
    with pytest.raises(EscError):
        link.mode("CURRENT")
    st = link.get()
    assert FAULTS[st["fault"]] == "NOT_ALIGNED"
    assert t.truth("on") == 0                     # bridge never enabled


def test_overcurrent_trips_and_disables_bridge():
    t, link = make(R=0.5)                         # 3 V on the d-axis into 0.5 ohm: 6 A > I_TRIP (4 A)
    align(link)
    link.set("vd", 3.0)
    link.cmd("MODE VOLTAGE")
    link.hold(0.05)
    st = link.get()
    assert FAULTS[st["fault"]] == "OVERCURRENT"
    assert t.truth("on") == 0


def test_gate_driver_fault_trips():
    t, link = make()
    align(link)
    link.set("w", 5.0)
    link.mode("SPEED")
    t.param("nfault", 1)
    link.hold(0.01)
    st = link.get()
    assert FAULTS[st["fault"]] == "DRV_NFAULT"
    assert t.truth("on") == 0


def test_watchdog_trips_on_silence():
    t, link = make()
    align(link)
    link.set("w", 5.0)
    link.mode("SPEED")
    t.sleep(0.6)                                  # no heartbeat
    st = link.get()
    assert FAULTS[st["fault"]] == "WATCHDOG"
    assert t.truth("on") == 0


def test_protocol_rejects_out_of_range_and_bad_args():
    t, link = make()
    for bad in ("SET w 31", "SET id 1.5", "SET kp_i -1", "MODE FLY", "CAP VD 0", "FOO"):
        with pytest.raises(EscError):
            link.cmd(bad)
    t.write(b"X" * 80 + b"\n")                    # longer than LINE_MAX
    assert t.readline().startswith(b"ERR LONG")
