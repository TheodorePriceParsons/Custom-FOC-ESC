# Custom FOC ESC: Test Report

**4 / 4 requirements passed** · 2026-11-20 16:35 · N = 3 runs per test

## Conditions

| | |
|---|---|
| Target | Hardware (Nucleo-G474RE + ESC + GM4108H) |
| Firmware build | Nov 20 2026 16:32:03 (protocol v2) |
| Host commit | `a3aba97-dirty` |
| Bus voltage | 12.00 V (KD3005P, 0.5 A limit) |
| Motor | GM4108H-120T, 11 pole pairs, no load |
| Current gains | Kp 1, Ki 4886 (firmware defaults) |
| Speed gains | Kp 0.0085, Ki 0.13 |

## Requirements

Predicted values come from a model of the firmware's control loops using the R, L, Kt and J measured in this same run, so they test the design math, not just the hardware.

| ID | Requirement | Limit | Predicted | Measured (mean ± std) | Result |
|---|---|---|---|---|---|
| REQ-SPD-01 | Speed step overshoot (5 to 15 rad/s) | < 20 % | 17.2 % | 7.66 ± 2.1 % | ✅ PASS |
| REQ-SPD-02 | Speed step settling time (5 % band) | < 300 ms | 107 ms | 94.6 ± 45 ms | ✅ PASS |
| REQ-SPD-03 | Speed steady-state error | < 2 % | ≈ 0 % | 0.291 ± 0.15 % | ✅ PASS |
| REQ-SPD-04 | Speed ripple at 10 rad/s (std / mean) | < 5 % | – | 2.37 ± 0.22 % | ✅ PASS |

## Characterization

| Quantity | Measured |
|---|---|
| Torque constant Kt (back-EMF) | 0.228 ± 0.0019 N m/A |
| Friction current at 10 rad/s | 0.038 ± 0.0012 A |
| Rotor inertia J (impulse-momentum over the speed step) | 2.93e-05 ± 7e-06 kg m² |
| Speed step peak time | 60.5 ± 29 ms (model 43.2 ms) |
| Speed ripple at 10 rad/s without cogging feedforward | 7.77 % |
| Speed ripple at 10 rad/s after learning | 2.5 % |
| Rotor inertia J (from the learning step's response) | 2.42e-05 kg m² |
| Largest feedforward harmonic | 0.0251 A |

## Results

### Speed loop step

![Speed loop step](plots/spd.png)

> Metrics use a 10 ms moving average of vel_mech; the plot shows the raw signal.

### Speed ripple

![Speed ripple](plots/ripple.png)

> R was not measured in this run, so Kt ignores the R*iq drop (upper bound).

### Cogging feedforward

![Cogging feedforward](plots/cog.png)

> Learned in 5 updates at 10 rad/s, harmonics 1, 2, 11, 22, 24, 33, 44, 48 per revolution. Later speed tests in this run use it.

## Method

Run with `python run_bench.py` (see `bench/README.md`). The firmware applies each step at an exact control-loop sample and records 2048 samples to RAM; the host downloads the capture over UART and computes every metric from it. Raw captures are in `raw/` as CSV.
