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
    model_delay: int = 1                              # samples of PWM update delay (0 in the --sim model)

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


# ---------------------------------------------------------------- cogging feedforward
COG_KS = (1, 2, 11, 22, 24, 33, 44, 48)   # per mech rev: eccentricity, pole pairs, poles, slots, multiples
COG_ITERS = 5                             # learning updates (each one is a 3 s record at 10 rad/s)
COG_GAIN = 0.8                            # fraction of the estimated error corrected per update
COG_F_MAX = 0.1                           # A, per harmonic
J_GUESS = 2.5e-5                          # kg m^2, only seeds the first update; refined from data
VEL_ALPHA = 0.02                          # VEL_LPF_ALPHA in board.h


def _cog_send(link, ks, F):
    for k, f in zip(ks, F):
        link.cmd(f"COG {k} {f.real:.6g} {-f.imag:.6g}")    # iq_ff = a cos + b sin, a = Re F, b = -Im F
    link.cmd("COG ON")


def cog_table_h(ks, F) -> str:
    rows = ", ".join(f"{{{k}, {f.real:.6f}f, {-f.imag:.6f}f}}" for k, f in zip(ks, F))
    return f"#define COG_TABLE       {{ {rows} }}\n#define COG_ENABLE      1\n"


def test_cog(ctx: Ctx):
    """Learn a feedforward that cancels position-dependent torque (cogging), by iteration.

    At a steady speed w0, per harmonic k of the rotor angle (phasors, theta = w0 t):
        J (j k w0) W_k = Kt (I_k - C_k)
    W = speed ripple, I = measured iq ripple, C = cogging expressed as amps. So
        C_k = I_k - (j k w0 / beta) W_k,    beta = Kt / J
    Each update moves the feedforward F toward C. beta is first guessed, then measured from how W
    responded to the first update: W1 - W0 = (beta / (j k w0)) (I1 - I0). A beta error only
    scales the update, so the iteration still converges (0 < gain * error ratio < 2).
    """
    link = ctx.link
    if int(link.info.get("proto", 1)) < 2:
        ctx.note("cog", "Skipped: firmware has no COG command (protocol v2 needed).")
        ctx.log("  skipped: firmware protocol < 2")
        return
    decim = 16
    t, _ = link.time_axis(decim)
    f_loop = float(link.info.get("f_loop", 10377))
    ks = np.array(COG_KS, dtype=float)
    F = np.zeros(len(ks), complex)
    R = ctx.conditions.get("R_for_kt")
    J_seed = float(np.nanmedian(ctx.metrics["J_kgm2"])) if "J_kgm2" in ctx.metrics else J_GUESS

    def measure():
        link.record("NONE", decim)
        d = link.dump()
        th, vel, iq = d[:, 3], d[:, 1], d[:, 2]
        w0 = float(np.mean(vel))
        H = an.vel_meas_response(ks * w0 / (2 * np.pi), VEL_ALPHA, f_loop)
        W = an.harmonics(th, vel, ks) / H
        I = an.harmonics(th, iq, ks)
        return d, w0, W, I

    link.cmd("COG CLR")
    try:
        link.set("w", W_RIPPLE)
        link.mode("SPEED")
        link.hold(2.0)
        gets = []
        for _ in range(10):
            gets.append(link.get())
            link.hold(0.05)
        vq = np.mean([g["vq"] for g in gets]); iq0 = np.mean([g["iq"] for g in gets])
        vel0 = np.mean([g["vel"] for g in gets])
        kt = 1.5 * POLE_PAIRS * (vq - (R or 0.0) * iq0) / (POLE_PAIRS * vel0)
        beta = kt / J_seed
        beta_measured = False

        hist = []
        for it in range(COG_ITERS + 1):
            d, w0, W, I = measure()
            rp = an.ripple(d[:, 1])["std_pct"]
            hist.append((W, I))
            ctx.keep("cog", Capture("cog", t, 0.0, d, ["w_ref [rad/s]", "vel [rad/s]", "iq [A]", "theta [rad]"]))
            if it == 1:                                    # measure beta from the first update
                A = (hist[1][1] - hist[0][1]) / (1j * ks * w0)
                B = hist[1][0] - hist[0][0]
                b_fit = float(np.real(np.sum(np.conj(A) * B)) / np.sum(np.abs(A) ** 2))
                big = np.sum(np.abs(hist[1][1] - hist[0][1])) > 3e-3     # > 3 mA of change to fit on
                if big and np.isfinite(b_fit) and b_fit > 0:
                    beta = float(np.clip(b_fit, 0.2 * beta, 5.0 * beta))
                    beta_measured = True
            amp = " ".join(f"{int(k)}:{abs(w):.2f}" for k, w in zip(ks, W) if abs(w) > 0.05)
            ctx.log(f"  iter {it}: ripple {rp:.2f} %   speed harmonics [rad/s] {amp or '-'}")
            if it == 0:
                ctx.add("cog_ripple_before_pct", rp)
            if it == COG_ITERS:
                ctx.add("cog_ripple_after_pct", rp)
                break
            C = I - (1j * ks * w0 / beta) * W
            # drive the measured current (not the command) to C: the current loop lags a few
            # degrees at these frequencies, and correcting on I removes that bias too
            F = F + COG_GAIN * (C - I)
            F = np.where(np.abs(F) > COG_F_MAX, F / np.abs(F) * COG_F_MAX, F)
            _cog_send(link, ks.astype(int), F)
            link.hold(1.0)                                 # let the speed loop settle
        _stop_spinning(link)
    except Exception:
        try:
            link.cmd("COG CLR")
        except Exception:
            pass
        raise
    finally:
        _idle(link)
    if beta_measured:
        ctx.add("cog_J_kgm2", kt / beta)
    ctx.add("cog_peak_A", float(np.max(np.abs(F))))
    ctx.conditions["cog_table_h"] = cog_table_h(ks.astype(int), F)
    if beta_measured:
        ctx.log(f"  J from the learning step: {kt / beta:.2e} kg m^2 (Kt {kt:.3f} N m/A)")
    else:
        ctx.log("  almost no position-dependent torque found, so J couldn't be measured from it")
    ctx.log("  feedforward stays on for the rest of this run. To keep it, paste into board.h:")
    for line in ctx.conditions["cog_table_h"].splitlines():
        ctx.log("    " + line)
    ctx.note("cog", f"Learned in {COG_ITERS} updates at {W_RIPPLE:g} rad/s, harmonics {', '.join(map(str, COG_KS))} "
                    "per revolution. Later speed tests in this run use it.")


# ---------------------------------------------------------------- three-phase currents
PHASE_ID = 0.3              # A, d-axis current injected so the waveform sits well above the noise


def test_phase(ctx: Ctx):
    """Phase currents at 10 rad/s with a d-axis current injected (no torque, so the speed loop
    is undisturbed). Checks the three sense channels agree in amplitude and sit 120 deg apart."""
    link = ctx.link
    if int(link.info.get("proto", 1)) < 2:
        ctx.note("phase", "Skipped: firmware has no IABC capture (protocol v2 needed).")
        return
    decim = 2
    t, _ = link.time_axis(decim)
    for r in range(ctx.reps):
        cog_was_on = bool(link.get().get("cog", 0))
        try:
            link.cmd("COG OFF")           # the feedforward is a 2x-electrical iq ripple: it would
            link.set("w", W_RIPPLE)       # unbalance the fundamentals and fake a sense mismatch
            link.mode("SPEED")
            link.hold(1.0)
            link.set("id", PHASE_ID)
            link.hold(0.5)
            link.record("IABC", decim)
            link.set("id", 0.0)
            _stop_spinning(link)
            d = link.dump()
        finally:
            _idle(link)
            if cog_was_on:
                link.cmd("COG ON")
        fits = [an.sine_fit(d[:, 3], d[:, k]) for k in range(3)]
        amps = np.array([f["amp"] for f in fits])
        ph = np.array([f["phase"] for f in fits])
        spacing = np.degrees(np.angle(np.exp(1j * (ph - np.roll(ph, -1)))))   # a-b, b-c, c-a: +120 each
        ctx.add("phase_amp_A", float(np.mean(amps)))
        ctx.add("phase_amp_mismatch_pct", 100 * float(np.ptp(amps) / np.mean(amps)))
        ctx.add("phase_spacing_err_deg", float(np.max(np.abs(np.abs(spacing) - 120.0))))
        ctx.add("phase_offset_mA", 1e3 * float(np.max(np.abs([f["offset"] for f in fits]))))
        ctx.keep("phase", Capture("phase", t, 0.0, d, ["ia [A]", "ib [A]", "ic [A]", "theta_e [rad]"]))
        ctx.log(f"  rep {r + 1}: amplitude a/b/c {amps[0] * 1e3:.0f}/{amps[1] * 1e3:.0f}/{amps[2] * 1e3:.0f} mA, "
                f"spacing {spacing[0]:.1f}/{spacing[1]:.1f}/{spacing[2]:.1f} deg")
    ctx.note("phase", f"{PHASE_ID * 1e3:.0f} mA on the d-axis (no torque) while holding 10 rad/s, so the "
                      "waveform is large compared with the 4 mA ADC step. Cogging feedforward off for this capture.")


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
    if getattr(ctx.link.t, "is_sil", False):
        ctx.metrics["isr_load_pct"] = [float("nan")]
        ctx.log("  not measurable in SIL (PC timing); run on the board or in PIL")
        return
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
        if hasattr(link.t, "press_estop"):
            ctx.log("  SIL: harness presses B1")
            link.t.press_estop()
        else:
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
    "cog": ("Cogging feedforward (learned)", test_cog),
    "phase": ("Three-phase currents", test_phase),
    "wd": ("Host watchdog", test_wd),
    "estop": ("E-stop button", test_estop),
    "enc": ("Encoder read integrity", test_enc),
    "isr": ("Control ISR load", test_isr),
}
DEFAULT_ORDER = ["enc", "rl", "cur", "cog", "ripple", "spd", "phase", "wd", "isr"]
# cog first: ripple and spd then measure the drive with the feedforward on; ripple gives Kt for the speed model
