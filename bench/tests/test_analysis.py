"""Checks the metric code against signals with known answers: python -m pytest bench/tests"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import analysis as an  # noqa: E402

T = np.arange(2048) / 10377.0
TS = 200 / 10377.0


def first_order(tau, y0=0.05, y1=0.25):
    y = np.full_like(T, y0)
    m = T >= TS
    y[m] = y0 + (y1 - y0) * (1 - np.exp(-(T[m] - TS) / tau))
    return y


def test_first_order_tau_and_rise():
    tau = 0.53e-3
    y = first_order(tau)
    fit = an.fit_first_order(T, y, TS)
    assert abs(fit["tau_s"] - tau) / tau < 0.02
    m = an.step_metrics(T, y, TS)
    assert abs(m["rise_s"] - 2.197 * tau) / (2.197 * tau) < 0.05      # 10-90 % = ln(9) tau
    assert m["overshoot_pct"] < 0.1
    assert abs(m["settle_s"] - 3.0 * tau) < 2 / 10377.0              # 5 % band = ln(20) tau


def test_pi_speed_loop_overshoot():
    # w(t) = 1 - e^(-wn t) + wn t e^(-wn t): overshoot e^-2 = 13.5 % at t = 2/wn
    wn = 2 * math.pi * 5
    t = np.arange(2048) * 4 / 10377.0
    ts = 200 * 4 / 10377.0
    tau = np.clip(t - ts, 0, None)
    y = 5 + 10 * (1 - np.exp(-wn * tau) + wn * tau * np.exp(-wn * tau))
    m = an.step_metrics(t, y, ts, tail=0.05)
    assert abs(m["overshoot_pct"] - 100 * math.exp(-2)) < 0.3
    assert abs(m["peak_s"] - 2 / wn) < 4 / 10377.0 * 2


def test_falling_step_is_handled():
    y = first_order(1e-3, y0=0.25, y1=0.05)
    m = an.step_metrics(T, y, TS)
    assert m["step"] < 0 and m["overshoot_pct"] < 0.1


def test_ripple_percent():
    y = 10 + 0.5 * np.sin(np.linspace(0, 20 * np.pi, 4000))
    r = an.ripple(y)
    assert abs(r["std_pct"] - 100 * 0.5 / math.sqrt(2) / 10) < 0.05
