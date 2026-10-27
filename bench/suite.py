"""Test procedures. Each test leaves the drive in IDLE, whether it passes, fails or raises."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

import analysis as an
from esc_link import EscLink, EscError, MODES, FAULTS
from spec import SYSCLK_HZ, CURRENT_BW_HZ

# test conditions (also printed in the report)
VD_STEP = 1.0            # V, d-axis voltage step for R/L identification
ID_FROM, ID_TO = 0.05, 0.25   # A, d-axis current step
W_FROM, W_TO = 5.0, 15.0      # rad/s, speed step
W_RIPPLE = 10.0               # rad/s
CUR_WINDOW = 0.020            # s analysed after a current step (> 30 design time constants)
POLE_PAIRS = 11


@dataclass
class Capture:
    name: str
    t: np.ndarray
    t_step: float
    data: np.ndarray            # (n, 4)
    channels: list[str]


@dataclass
class Ctx:
    link: EscLink
    reps: int = 3
    tune_current: bool = False
    current_bw: float = CURRENT_BW_HZ
    log: callable = print
    metrics: dict = field(default_factory=dict)       # metric -> list of values (one per rep)
    captures: dict = field(default_factory=dict)      # test -> list[Capture]
    notes: dict = field(default_factory=dict)         # test -> list of strings
    conditions: dict = field(default_factory=dict)
    models: dict = field(default_factory=dict)        # test -> (t, predicted response)
    model_delay: int = 1                              # samples of PWM update delay (0 in the simulator)

    def add(self, key, value):
        self.metrics.setdefault(key, []).append(float(value))

    def keep(self, test, cap):
        self.captures.setdefault(test, []).append(cap)

    def note(self, test, text):
        self.notes.setdefault(test, []).append(text)


def _idle(link: EscLink):
    link.safe_stop()
    link.cmd(f"WD {link.watchdog_ms}")      # safe_stop disarms; re-arm for the next test


def _stop_spinning(link: EscLink, wait=0.8):
    link.set("w", 0)
    link.hold(wait)
    link.cmd("MODE IDLE")
    link.hold(0.1)


# ---------------------------------------------------------------- preflight
def preflight(ctx: Ctx, force_align=False):
    link = ctx.link
    st = link.get()
    if MODES.get(st["mode"]) == "FAULT":
        ctx.log(f"  clearing latched fault {FAULTS.get(st['fault'])}")
        link.cmd("MODE IDLE")
        link.hold(0.05)
        st = link.get()
    if not 10.5 <= st["vbus"] <= 13.5:
        raise EscError(f"bus voltage {st['vbus']:.2f} V outside 10.5-13.5 V")
    if force_align or not st["aligned"]:
        ctx.log("  aligning encoder (rotor will move)")
        link.cmd("MODE ALIGN")
        link.hold(2.0)
        st = link.get()
        if not st["aligned"] or MODES.get(st["mode"]) != "IDLE":
            raise EscError(f"alignment failed: fault {FAULTS.get(st['fault'])}")
    link.cmd("CLRMAX")
    ctx.conditions.update(vbus=st["vbus"], kp_i=st["kp_i"], ki_i=st["ki_i"],
                          kp_w=st["kp_w"], ki_w=st["ki_w"])


# ---------------------------------------------------------------- R / L identification
def test_rl(ctx: Ctx):
    link = ctx.link
    t, ts = link.time_axis(1)
    for r in range(ctx.reps):
        try:
            link.set("vd", 0); link.set("vq", 0)
            link.mode("VOLTAGE")
            link.hold(0.3)
            link.record("VD", 1, VD_STEP)
            _idle(link)
            link.hold(0.3)
            d = link.dump()
        finally:
            _idle(link)
        fit = an.fit_first_order(t, d[:, 1], ts)
        R = VD_STEP / fit["amp"]
        L = fit["tau_s"] * R
        ctx.add("R_ph_ohm", R)
        ctx.add("L_ph_mH", L * 1e3)
        ctx.add("tau_ms", fit["tau_s"] * 1e3)
        ctx.keep("rl", Capture("rl", t, ts, d, ["vd_cmd [V]", "id [A]", "iq [A]", "vel [rad/s]"]))
        ctx.log(f"  rep {r + 1}: R = {R:.3f} ohm, L = {L * 1e3:.3f} mH, tau = {fit['tau_s'] * 1e3:.3f} ms"
                f" ({fit['n_fit']} pts in fit)")
    R = float(np.nanmedian(ctx.metrics["R_ph_ohm"]))
    L = float(np.nanmedian(ctx.metrics["L_ph_mH"])) * 1e-3
    wc = 2 * math.pi * ctx.current_bw
    ctx.metrics["kp_i_design"] = [L * wc]
    ctx.metrics["ki_i_design"] = [R * wc]
    ctx.conditions["R_for_kt"] = R
    samples = np.nanmedian(ctx.metrics["tau_ms"]) * 1e-3 * link.info.get("f_loop", 10377)
    if samples < 4:
        ctx.note("rl", f"tau is only {samples:.1f} samples long at 10.4 kHz, so L is coarse "
                       "(+/- ~25 %). R is unaffected.")


def apply_current_gains(ctx: Ctx):
    kp, ki = ctx.metrics["kp_i_design"][0], ctx.metrics["ki_i_design"][0]
    R = ctx.conditions["R_for_kt"]
    if not (0.5 <= R <= 50 and 0.01 <= kp <= 50 and ki <= 1e5 and math.isfinite(kp)):
        ctx.log(f"  design gains look wrong (Kp {kp:.3g}, Ki {ki:.3g}); keeping firmware gains")
        return
    ctx.link.set("kp_i", kp)
    ctx.link.set("ki_i", ki)
    ctx.conditions.update(kp_i=kp, ki_i=ki)
    ctx.log(f"  applied design gains Kp_i = {kp:.3f}, Ki_i = {ki:.1f}")


# ---------------------------------------------------------------- current loop step
def test_cur(ctx: Ctx):
    link = ctx.link
    t, ts = link.time_axis(1)
    for r in range(ctx.reps):
        try:
            link.set("iq", 0); link.set("id", ID_FROM)
            link.mode("CURRENT")
            link.hold(0.3)
            link.record("ID", 1, ID_TO)
            _idle(link)
            d = link.dump()
        finally:
            _idle(link)
        m = an.step_metrics(t, d[:, 1], ts, band=0.05, smooth_w=3, window=CUR_WINDOW)
        step = ID_TO - ID_FROM
        after = t >= ts
        iq_pre = np.mean(d[~after, 2][-50:])
        iq_s = an.smooth(d[:, 2], 3)
        xw = after & (t < ts + 0.005)
        xc = 100 * np.max(np.abs(iq_s[xw] - iq_pre)) / step
        noise = 1e3 * np.std(d[t > ts + CUR_WINDOW, 1])
        ctx.add("cur_noise_mA", noise)
        ctx.add("cur_rise_ms", m["rise_s"] * 1e3)
        ctx.add("cur_overshoot_pct", m["overshoot_pct"])
        ctx.add("cur_settle_ms", m["settle_s"] * 1e3)
        ctx.add("cur_xcouple_pct", xc)
        ctx.keep("cur", Capture("cur", t, ts, d, ["id_cmd [A]", "id [A]", "iq [A]", "vd [V]"]))
        ctx.log(f"  rep {r + 1}: rise {m['rise_s'] * 1e3:.2f} ms, overshoot {m['overshoot_pct']:.1f} %, "
                f"settle {m['settle_s'] * 1e3:.2f} ms, q-axis {xc:.1f} %, noise {noise:.1f} mA")

    c0 = ctx.captures["cur"][0]
    noise = 100 * np.std(c0.data[c0.t < ts, 1][-100:]) / (ID_TO - ID_FROM)
    ctx.note("cur", f"Step metrics use the first {CUR_WINDOW * 1e3:.0f} ms after the step; "
                    "anything later is reported separately as steady-state noise (REQ-CUR-05).")
    ctx.note("cur", f"Current sense noise before the step is {noise:.1f} % of the step (1 ADC count = 4 mA), "
                    "so measured overshoot below about twice that is noise, not ringing.")

    # prediction from the measured R, L and the gains actually used
    R = ctx.conditions.get("R_for_kt")
    if R and "L_ph_mH" in ctx.metrics:
        L = float(np.nanmedian(ctx.metrics["L_ph_mH"])) * 1e-3
        y = an.model_current_step(t, ts, ID_FROM, ID_TO, R, L, ctx.conditions["kp_i"],
                                  ctx.conditions["ki_i"], link.info.get("f_loop", 10377),
                                  delay=ctx.model_delay)
        pm = an.step_metrics(t, y, ts, band=0.05, window=CUR_WINDOW)
        ctx.metrics["cur_rise_ms_model"] = [pm["rise_s"] * 1e3]
        ctx.metrics["cur_overshoot_pct_model"] = [pm["overshoot_pct"]]
        ctx.metrics["cur_settle_ms_model"] = [pm["settle_s"] * 1e3]
        ctx.metrics["cur_xcouple_pct_model"] = [0.0]
        ctx.models["cur"] = (t, y)
        ctx.log(f"  model (measured R, L): rise {pm['rise_s'] * 1e3:.2f} ms, "
                f"overshoot {pm['overshoot_pct']:.1f} %, settle {pm['settle_s'] * 1e3:.2f} ms")
    else:
        ctx.note("cur", "No model prediction: run the rl test in the same session.")


# ---------------------------------------------------------------- speed step
def test_spd(ctx: Ctx):
    link = ctx.link
    decim = 4
    t, ts = link.time_axis(decim)
    for r in range(ctx.reps):
        try:
            link.set("w", W_FROM)
            link.mode("SPEED")
            link.hold(1.5)
            link.record("W", decim, W_TO)
            _stop_spinning(link)
            d = link.dump()
        finally:
            _idle(link)
        m = an.step_metrics(t, d[:, 1], ts, band=0.05, smooth_w=25)
        sse = 100 * abs(m["y1"] - W_TO) / W_TO
        ctx.add("spd_overshoot_pct", m["overshoot_pct"])
        ctx.add("spd_settle_ms", m["settle_s"] * 1e3)
        ctx.add("spd_sse_pct", sse)
        ctx.add("spd_peak_ms", m["peak_s"] * 1e3)
        ctx.keep("spd", Capture("spd", t, ts, d, ["w_ref [rad/s]", "vel [rad/s]", "iq_cmd [A]", "iq [A]"]))
        kt = np.nanmedian(ctx.metrics["Kt_Nm_per_A"]) if "Kt_Nm_per_A" in ctx.metrics else None
        if kt:
            ctx.add("J_kgm2", an.estimate_inertia(t, ts, d[:, 1], d[:, 3], kt))
        ctx.log(f"  rep {r + 1}: overshoot {m['overshoot_pct']:.1f} %, settle {m['settle_s'] * 1e3:.0f} ms, "
                f"ss error {sse:.2f} %, peak {m['peak_s'] * 1e3:.0f} ms"
                + (f", J {ctx.metrics['J_kgm2'][-1]:.2e} kg m^2" if kt else ""))

    # prediction: J from the initial acceleration, Kt from the ripple test, gains as used
    if "J_kgm2" in ctx.metrics:
        J = float(np.nanmedian(ctx.metrics["J_kgm2"]))
        kt = float(np.nanmedian(ctx.metrics["Kt_Nm_per_A"]))
        d0 = ctx.captures["spd"][0].data
        fr = an.friction_line(t, ts, d0[:, 1], d0[:, 3])
        y = an.model_speed_step(t, ts, W_FROM, W_TO, kt, J, ctx.conditions["kp_w"],
                                ctx.conditions["ki_w"], fr["i0"], link.info.get("f_loop", 10377),
                                fric_slope=fr["slope"])
        pm = an.step_metrics(t, y, ts, band=0.05)
        ctx.metrics["spd_overshoot_pct_model"] = [pm["overshoot_pct"]]
        ctx.metrics["spd_settle_ms_model"] = [pm["settle_s"] * 1e3]
        ctx.metrics["spd_sse_pct_model"] = [0.0]
        ctx.metrics["spd_peak_ms_model"] = [pm["peak_s"] * 1e3]
        ctx.models["spd"] = (t, y)
        ctx.log(f"  model (J, Kt measured): overshoot {pm['overshoot_pct']:.1f} %, "
                f"settle {pm['settle_s'] * 1e3:.0f} ms, peak {pm['peak_s'] * 1e3:.0f} ms")
    else:
        ctx.note("spd", "No model prediction: needs Kt from the ripple test (run it before spd).")
    ctx.note("spd", "Metrics use a 10 ms moving average of vel_mech; the plot shows the raw signal.")


# ---------------------------------------------------------------- ripple + Kt
def test_ripple(ctx: Ctx):
    link = ctx.link
    decim = 16
    t, _ = link.time_axis(decim)
    R = ctx.conditions.get("R_for_kt")
    for r in range(ctx.reps):
        try:
            link.set("w", W_RIPPLE)
            link.mode("SPEED")
            link.hold(2.0)
            link.record("NONE", decim)
            gets = []
            for _ in range(10):
                gets.append(link.get())
                link.hold(0.05)
            _stop_spinning(link)
            d = link.dump()
        finally:
            _idle(link)
        rp = an.ripple(d[:, 1])
        vq = np.mean([g["vq"] for g in gets])
        iq = np.mean([g["iq"] for g in gets])
        vel = np.mean([g["vel"] for g in gets])
        we = POLE_PAIRS * vel
        lam = (vq - (R or 0.0) * iq) / we
        kt = 1.5 * POLE_PAIRS * lam
        ctx.add("ripple_pct", rp["std_pct"])
        ctx.add("Kt_Nm_per_A", kt)
        ctx.add("i_friction_A", iq)
        ctx.keep("ripple", Capture("ripple", t, 0.0, d, ["w_ref [rad/s]", "vel [rad/s]", "iq [A]", "theta [rad]"]))
        ctx.log(f"  rep {r + 1}: ripple {rp['std_pct']:.2f} % (pk-pk {rp['pkpk_pct']:.1f} %), "
                f"Kt {kt:.3f} N m/A, friction {iq * 1e3:.1f} mA")
    if R is None:
        ctx.note("ripple", "R was not measured in this run, so Kt ignores the R*iq drop (upper bound).")


# ---------------------------------------------------------------- encoder integrity
ENC_CPR = 16384
ENC_GLITCH_COUNTS = 20        # one tick at 30 rad/s is 7.5 counts, so 20 is never real motion


def test_enc(ctx: Ctx):
    """Turn the rotor slowly in open loop (no encoder in the loop) and record the encoder angle
    every tick. Real motion moves ~1.4 counts per tick; any bigger jump is a bad read."""
    link = ctx.link
    decim = 1
    t, _ = link.time_axis(decim)
    total_s, glitches, worst = 0.0, 0, 0
    for r in range(ctx.reps * 6):            # each capture covers ~65 deg; ~3 revolutions total
        try:
            link.set("ol_v", 1.5)             # margin over ~0.85 V back-EMF at this speed
            link.set("ol_speed", 62.8)        # electrical rad/s -> 5.7 rad/s mechanical
            link.mode("OPENLOOP")
            link.hold(0.5)
            link.record("NONE", decim)
            _idle(link)
            d = link.dump()
        finally:
            _idle(link)
        th = d[:, 3]
        dc = np.diff(th) / (2 * np.pi) * ENC_CPR
        dc = (dc + ENC_CPR / 2) % ENC_CPR - ENC_CPR / 2          # unwrap
        bad = np.abs(dc) > ENC_GLITCH_COUNTS
        glitches += int(np.sum(bad))
        worst = max(worst, int(np.max(np.abs(dc))))
        total_s += t[-1]
        ctx.keep("enc", Capture("enc", t, 0.0, np.column_stack([th, np.r_[0, dc], d[:, 1], d[:, 2]]),
                                ["theta [rad]", "delta [counts]", "vel [rad/s]", "iq [A]"]))
        if r == 0 or bad.any():
            ctx.log(f"  capture {r + 1}: {int(np.sum(bad))} jumps > 20 counts, largest {int(np.max(np.abs(dc)))} counts")
    rate = glitches / total_s
    ctx.metrics["enc_glitch_rate"] = [rate]
    ctx.metrics["enc_worst_counts"] = [float(worst)]
    ctx.log(f"  {glitches} jumps in {total_s:.1f} s = {rate:.2f} per s; largest {worst} counts "
            f"({worst / ENC_CPR * 360:.1f} deg mech, {worst / ENC_CPR * 360 * POLE_PAIRS:.0f} deg electrical)")


# ---------------------------------------------------------------- ISR load
def test_isr(ctx: Ctx):
    st = ctx.link.get()
    budget = SYSCLK_HZ / ctx.link.info.get("f_loop", 10377)
    load = 100 * st["isr_max"] / budget
    ctx.metrics["isr_load_pct"] = [load]
    ctx.log(f"  worst-case ISR {st['isr_max']} cycles of {budget:.0f} = {load:.1f} % (over the whole run)")


# ---------------------------------------------------------------- watchdog
def test_wd(ctx: Ctx):
    link = ctx.link
    try:
        link.set("w", 5.0)
        link.mode("SPEED")
        link.hold(1.0)
        before = link.get()
        silence = 2 * link.watchdog_ms / 1000
        link.t.sleep(silence)                  # host goes quiet: no heartbeats
        after = link.get()
    finally:
        link.cmd("MODE IDLE")
        _idle(link)
    ok = (MODES.get(before["mode"]) == "SPEED" and MODES.get(after["mode"]) == "FAULT"
          and FAULTS.get(after["fault"]) == "WATCHDOG")
    ctx.metrics["wd_tripped"] = [1.0 if ok else 0.0]
    ctx.log(f"  running before: {MODES.get(before['mode'])}; after {silence * 1e3:.0f} ms silence: "
            f"{MODES.get(after['mode'])} / {FAULTS.get(after['fault'])}")


# ---------------------------------------------------------------- E-stop (interactive)
def test_estop(ctx: Ctx, timeout=15.0):
    link = ctx.link
    tripped = False
    try:
        link.set("w", 5.0)
        link.mode("SPEED")
        link.hold(0.5)
        ctx.log("  >>> press the blue B1 button on the Nucleo now <<<")
        waited = 0.0
        while waited < timeout:
            st = link.get()
            if MODES.get(st["mode"]) == "FAULT":
                tripped = FAULTS.get(st["fault"]) == "ESTOP"
                break
            link.hold(0.1)
            waited += 0.1
    finally:
        link.cmd("MODE IDLE")
        _idle(link)
    ctx.metrics["estop_tripped"] = [1.0 if tripped else 0.0]
    ctx.log(f"  E-stop {'tripped' if tripped else 'NOT detected'}")


TESTS = {
    "rl": ("R/L identification (d-axis voltage step)", test_rl),
    "cur": ("Current loop step (d-axis)", test_cur),
    "spd": ("Speed loop step", test_spd),
    "ripple": ("Speed ripple and torque constant", test_ripple),
    "wd": ("Host watchdog", test_wd),
    "estop": ("E-stop button", test_estop),
    "enc": ("Encoder read integrity", test_enc),
    "isr": ("Control ISR load", test_isr),
}
DEFAULT_ORDER = ["enc", "rl", "cur", "ripple", "spd", "wd", "isr"]   # ripple gives Kt for the speed model
