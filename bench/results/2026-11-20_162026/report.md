# Custom FOC ESC: Test Report

**2 / 4 requirements passed** · 2026-11-20 16:21 · N = 3 runs per test

## Conditions

| | |
|---|---|
| Target | Hardware (Nucleo-G474RE + ESC + GM4108H) |
| Firmware build | Nov 20 2026 16:18:25 (protocol v1) |
| Host commit | `a3aba97-dirty` |
| Bus voltage | 12.00 V (KD3005P, 0.5 A limit) |
| Motor | GM4108H-120T, 11 pole pairs, no load |
| Current gains | Kp 1, Ki 4886 (firmware defaults) |
| Speed gains | Kp 0.0085, Ki 0.13 |

## Requirements

Predicted values come from a model of the firmware's control loops using the R, L, Kt and J measured in this same run, so they test the design math, not just the hardware.

| ID | Requirement | Limit | Predicted | Measured (mean ± std) | Result |
|---|---|---|---|---|---|
| REQ-SPD-01 | Speed step overshoot (5 to 15 rad/s) | < 20 % | ≈ 0 % | 16.3 ± 4.2 % | ✅ PASS |
| REQ-SPD-02 | Speed step settling time (5 % band) | < 300 ms | 52 ms | 690 ± 25 ms | ❌ FAIL |
| REQ-SPD-03 | Speed steady-state error | < 2 % | ≈ 0 % | 0.245 ± 0.2 % | ✅ PASS |
| REQ-SPD-04 | Speed ripple at 10 rad/s (std / mean) | < 5 % | – | 7.65 ± 0.17 % | ❌ FAIL |

## Characterization

| Quantity | Measured |
|---|---|
| Torque constant Kt (back-EMF) | 0.219 ± 0.0038 N m/A |
| Friction current at 10 rad/s | 0.04 ± 0.00078 A |
| Rotor inertia J (impulse-momentum over the speed step) | 3.55e-05 ± 3.9e-06 kg m² |
| Speed step peak time | 68.9 ± 28 ms (model 712 ms) |

## Results

### Speed loop step

![Speed loop step](plots/spd.png)

> Metrics use a 10 ms moving average of vel_mech; the plot shows the raw signal.

### Speed ripple

![Speed ripple](plots/ripple.png)

> R was not measured in this run, so Kt ignores the R*iq drop (upper bound).

## Method

Run with `python run_bench.py` (see `bench/README.md`). The firmware applies each step at an exact control-loop sample and records 2048 samples to RAM; the host downloads the capture over UART and computes every metric from it. Raw captures are in `raw/` as CSV.
