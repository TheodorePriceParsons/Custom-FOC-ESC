"""Requirements the ESC is verified against. Single source of truth for the report.

Targets were derived before testing (see README.md, "Where the numbers come from"):
  current loop designed for 300 Hz bandwidth, first order: tau = 1/(2 pi 300) = 0.53 ms
    rise (10-90 %) = 2.2 tau = 1.17 ms, 5 % settling = 3 tau = 1.6 ms, overshoot 0 %
  speed loop zeta = 1, wn = 2 pi 5: overshoot = e^-2 = 13.5 % (PI zero), peak at 2/wn = 64 ms
"""
from __future__ import annotations

from dataclasses import dataclass
import math

SYSCLK_HZ = 170e6
CURRENT_BW_HZ = 300.0                      # design bandwidth for the current loop
SPEED_WN = 2 * math.pi * 5.0               # speed loop natural frequency, rad/s


@dataclass(frozen=True)
class Req:
    id: str
    text: str
    metric: str
    op: str                                # "<", ">", "=="
    limit: float
    unit: str
    test: str

    def check(self, value: float) -> bool | None:
        if value is None or not math.isfinite(value):
            return None
        return {"<": value < self.limit, ">": value > self.limit,
                "==": value == self.limit}[self.op]

    @property
    def limit_text(self) -> str:
        if self.op == "==":
            return "yes" if self.limit == 1 else str(self.limit)
        return f"{self.op} {self.limit:g} {self.unit}".strip()


REQUIREMENTS = [
    Req("REQ-CUR-01", "Current loop rise time (10-90 %)", "cur_rise_ms", "<", 1.5, "ms", "cur"),
    Req("REQ-CUR-02", "Current loop overshoot", "cur_overshoot_pct", "<", 10, "%", "cur"),
    Req("REQ-CUR-03", "Current loop settling time (5 % band)", "cur_settle_ms", "<", 3.0, "ms", "cur"),
    Req("REQ-CUR-04", "d/q decoupling: peak q-axis error during a d-axis step", "cur_xcouple_pct", "<", 20, "% of step", "cur"),
    Req("REQ-SPD-01", "Speed step overshoot (5 to 15 rad/s)", "spd_overshoot_pct", "<", 20, "%", "spd"),
    Req("REQ-SPD-02", "Speed step settling time (5 % band)", "spd_settle_ms", "<", 300, "ms", "spd"),
    Req("REQ-SPD-03", "Speed steady-state error", "spd_sse_pct", "<", 2, "%", "spd"),
    Req("REQ-SPD-04", "Speed ripple at 10 rad/s (std / mean)", "ripple_pct", "<", 5, "%", "ripple"),
    Req("REQ-SYS-01", "Control ISR worst-case CPU load", "isr_load_pct", "<", 60, "%", "isr"),
    Req("REQ-SAF-01", "Host watchdog disables the drive on link loss", "wd_tripped", "==", 1, "", "wd"),
    Req("REQ-SAF-02", "E-stop button disables the drive", "estop_tripped", "==", 1, "", "estop"),
]

# measured and reported, not pass/fail
CHARACTERIZATION = [
    ("R_ph_ohm", "Phase resistance R", "ohm", "rl"),
    ("L_ph_mH", "Phase inductance L", "mH", "rl"),
    ("tau_ms", "Electrical time constant L/R", "ms", "rl"),
    ("kp_i_design", "Current Kp for 300 Hz (L wc)", "V/A", "rl"),
    ("ki_i_design", "Current Ki for 300 Hz (R wc)", "V/(A s)", "rl"),
    ("Kt_Nm_per_A", "Torque constant Kt (back-EMF)", "N m/A", "ripple"),
    ("i_friction_A", "Friction current at 10 rad/s", "A", "ripple"),
    ("J_kgm2", "Rotor inertia J (impulse-momentum over the speed step)", "kg m²", "spd"),
    ("spd_peak_ms", "Speed step peak time", "ms", "spd"),
]
