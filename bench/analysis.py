"""Signal metrics for the bench. Pure numpy so it can be unit-tested on synthetic data."""
from __future__ import annotations

import numpy as np


def smooth(y: np.ndarray, w: int) -> np.ndarray:
    """Centered moving average (w odd). w <= 1 returns y unchanged."""
    if w <= 1:
        return y.astype(float)
    k = np.ones(w) / w
    pad = w // 2
    yp = np.pad(y.astype(float), pad, mode="edge")
    return np.convolve(yp, k, mode="valid")


def _first_crossing(t: np.ndarray, y: np.ndarray, level: float, rising: bool) -> float:
    """Time of the first crossing of `level`, linearly interpolated. NaN if never."""
    above = y >= level if rising else y <= level
    idx = np.flatnonzero(above)
    if idx.size == 0:
        return float("nan")
    i = idx[0]
    if i == 0:
        return float(t[0])
    y0, y1 = y[i - 1], y[i]
    if y1 == y0:
        return float(t[i])
    return float(t[i - 1] + (level - y0) / (y1 - y0) * (t[i] - t[i - 1]))


def step_metrics(t: np.ndarray, y: np.ndarray, t_step: float, band: float = 0.05,
                 tail: float = 0.25, smooth_w: int = 1, window: float | None = None) -> dict:
    """Rise time (10-90 %), overshoot, peak time and settling time of a step response.

    t       sample times [s]
    y       measured response
    t_step  time the step was applied [s]
    band    settling band as a fraction of the step size
    tail    fraction of the record (at the end) used as the final value
    window  if given, only [t_step - pre, t_step + window] is analysed, so disturbances long
            after the transient (measured separately) don't count as overshoot or settling
    """
    if window is not None:
        keep = t <= t_step + window
        t, y = t[keep], y[keep]
    ys = smooth(y, smooth_w)
    pre = ys[(t < t_step)][-min(50, int(np.sum(t < t_step))):]
    y0 = float(np.mean(pre))
    n_tail = max(1, int(len(ys) * tail))
    y1 = float(np.mean(ys[-n_tail:]))
    dy = y1 - y0
    if abs(dy) < 1e-12:
        raise ValueError("no step in signal")
    rising = dy > 0

    m = t >= t_step
    ta, ya = t[m] - t_step, ys[m]
    norm = (ya - y0) / dy                         # 0 -> 1 regardless of direction

    t10 = _first_crossing(ta, norm, 0.1, True)
    t90 = _first_crossing(ta, norm, 0.9, True)
    i_pk = int(np.argmax(norm))
    overshoot = max(0.0, (norm[i_pk] - 1.0) * 100.0)

    outside = np.flatnonzero(np.abs(norm - 1.0) > band)
    t_settle = float(ta[outside[-1] + 1]) if outside.size and outside[-1] + 1 < len(ta) else (
        float("nan") if outside.size else 0.0)

    return {
        "y0": y0, "y1": y1, "step": dy, "rising": rising,
        "rise_s": t90 - t10, "t10_s": t10, "t90_s": t90,
        "overshoot_pct": overshoot, "peak_s": float(ta[i_pk]),
        "settle_s": t_settle,
    }


def fit_first_order(t: np.ndarray, y: np.ndarray, t_step: float, tail: float = 0.25,
                    lo: float = 0.1, hi: float = 0.85) -> dict:
    """Fit y = y0 + A (1 - exp(-(t - td)/tau)) to a step response.

    tau comes from a least-squares line through ln(1 - norm) for norm in [lo, hi];
    the intercept absorbs any transport delay (one-sample PWM update delay).
    """
    pre = y[t < t_step]
    y0 = float(np.mean(pre[-min(50, pre.size):]))
    n_tail = max(1, int(len(y) * tail))
    y_inf = float(np.mean(y[-n_tail:]))
    A = y_inf - y0
    m = t >= t_step
    ta, norm = t[m] - t_step, (y[m] - y0) / A
    # use samples up to the first time the response reaches `hi` (noise later on is meaningless)
    reach = np.flatnonzero(norm >= hi)
    end = reach[0] if reach.size else len(norm)
    sel = np.flatnonzero((norm[:end + 1] > lo) & (norm[:end + 1] < hi))
    if sel.size < 2:
        return {"y0": y0, "y_inf": y_inf, "amp": A, "tau_s": float("nan"), "n_fit": int(sel.size)}
    slope, _ = np.polyfit(ta[sel], np.log(1.0 - norm[sel]), 1)
    tau = -1.0 / slope if slope < 0 else float("nan")
    return {"y0": y0, "y_inf": y_inf, "amp": A, "tau_s": float(tau), "n_fit": int(sel.size)}


def ripple(y: np.ndarray) -> dict:
    mean = float(np.mean(y))
    std = float(np.std(y))
    return {
        "mean": mean, "std": std, "pkpk": float(np.ptp(y)),
        "std_pct": 100.0 * std / abs(mean) if mean else float("nan"),
        "pkpk_pct": 100.0 * float(np.ptp(y)) / abs(mean) if mean else float("nan"),
    }


def bin_by_angle(theta: np.ndarray, y: np.ndarray, bins: int = 72) -> tuple[np.ndarray, np.ndarray]:
    """Mean of y in equal angle bins over one mechanical revolution [0, 2pi)."""
    th = np.mod(theta, 2 * np.pi)
    edges = np.linspace(0, 2 * np.pi, bins + 1)
    idx = np.clip(np.digitize(th, edges) - 1, 0, bins - 1)
    centers = 0.5 * (edges[:-1] + edges[1:])
    means = np.array([np.mean(y[idx == b]) if np.any(idx == b) else np.nan for b in range(bins)])
    return centers, means


def mean_std(values: list[float]) -> tuple[float, float]:
    a = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    if a.size == 0:
        return float("nan"), float("nan")
    return float(a.mean()), float(a.std(ddof=1)) if a.size > 1 else 0.0


# ---------------------------------------------------------------- models (predictions)
def model_current_step(t: np.ndarray, t_step: float, y0: float, y1: float, R: float, L: float,
                       kp: float, ki: float, f_loop: float, delay: int = 2) -> np.ndarray:
    """Predicted current step response of the firmware's discrete PI on an R-L phase.

    Mirrors foc.c: PI at f_loop with conditional integration, plant discretized with a
    zero-order hold. `delay` samples between computing a voltage and it acting on the
    measured current (1 for the computation, 1 for the HRTIM compare preload).
    """
    Ts = 1.0 / f_loop
    a = np.exp(-R * Ts / L)
    b = (1.0 - a) / R
    n = len(t)
    k_step = int(round(t_step * f_loop))
    i = y0
    integ = R * y0                               # steady state: PI output = R * i
    v_hist = [R * y0] * (delay + 1)
    out = np.empty(n)
    for k in range(n):
        out[k] = i
        r = y1 if k > k_step else y0             # step is written after control on sample k_step
        e = r - i
        u = kp * e + integ
        integ += ki * e * Ts
        v_hist.append(u)
        i = a * i + b * v_hist[-1 - delay]
        v_hist.pop(0)
    return out


def model_speed_step(t: np.ndarray, t_step: float, w0: float, w1: float, kt: float, J: float,
                     kp: float, ki: float, i_fric: float, f_loop: float, spd_div: int = 10,
                     lpf_alpha: float = 0.02, iq_max: float = 0.3, fric_slope: float = 0.0) -> np.ndarray:
    """Predicted speed step: ideal current loop (iq = iq_cmd), friction current
    i_fric + fric_slope (w - w0), the firmware's 33 Hz speed-estimate filter and the
    speed PI every spd_div ticks."""
    Ts = 1.0 / f_loop
    n_full = int(round(t[-1] * f_loop)) + 1
    k_step = int(round(t_step * f_loop))
    w = vel = w0
    integ = i_fric
    iq = i_fric
    trace = np.empty(n_full)
    for k in range(n_full):
        trace[k] = vel
        w += (kt * (iq - i_fric - fric_slope * (w - w0))) / J * Ts
        vel += lpf_alpha * (w - vel)
        if k % spd_div == 0:
            ref = w1 if k > k_step else w0
            e = ref - vel
            u = kp * e + integ
            us = min(max(u, -iq_max), iq_max)
            if u == us or e * u < 0:
                integ += ki * e * Ts * spd_div
            iq = us
    idx = np.clip(np.round(t * f_loop).astype(int), 0, n_full - 1)
    return trace[idx]


def estimate_inertia(t: np.ndarray, t_step: float, vel: np.ndarray, iq: np.ndarray, kt: float) -> float:
    """J from the impulse-momentum balance of a speed step:

        J (w(t_pk) - w0) = Kt * integral_{t_step}^{t_pk} (iq - iq_before) dt

    taken up to the peak of the filtered speed. At that instant d(vel)/dt = 0, so the
    first-order speed filter output equals the true speed and its lag drops out.
    The integral form averages the current noise instead of differentiating speed.
    Friction is taken as linear in speed between the two steady states (before the step
    and the end of the record), so viscous friction doesn't inflate J.
    """
    f = friction_line(t, t_step, vel, iq)
    vs = smooth(vel, 9)
    after = np.flatnonzero(t >= t_step)
    k_pk = after[int(np.argmax(vs[after]))]
    seg = slice(after[0], k_pk + 1)
    i_f = f["i0"] + f["slope"] * (vs[seg] - f["w0"])
    trap = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    impulse = float(trap(iq[seg] - i_f, t[seg]))
    dw = float(vs[k_pk]) - f["w0"]
    return kt * impulse / dw if dw > 0 else float("nan")


def friction_line(t, t_step, vel, iq, tail=0.25):
    """Friction current vs speed, from the steady state before the step and at the end."""
    pre = t < t_step
    n = max(1, int(len(t) * tail))
    w0, i0 = float(np.mean(vel[pre][-50:])), float(np.mean(iq[pre][-50:]))
    w1, i1 = float(np.mean(vel[-n:])), float(np.mean(iq[-n:]))
    slope = (i1 - i0) / (w1 - w0) if w1 != w0 else 0.0
    return {"w0": w0, "i0": i0, "slope": slope}
