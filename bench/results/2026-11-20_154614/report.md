# Custom FOC ESC: Test Report

**8 / 12 requirements passed** · 2026-11-20 15:48 · N = 3 runs per test

## Conditions

| | |
|---|---|
| Target | Hardware (Nucleo-G474RE + ESC + GM4108H) |
| Firmware build | Oct 27 2026 09:25:14 (protocol v1) |
| Host commit | `a3aba97` |
| Bus voltage | 12.00 V (KD3005P, 0.5 A limit) |
| Motor | GM4108H-120T, 11 pole pairs, no load |
| Current gains | Kp 2.03, Ki 9773 (from measured R, L) |
| Current loop design bandwidth | 300 Hz |
| Speed gains | Kp 0.0085, Ki 0.13 |

## Requirements

Predicted values come from a model of the firmware's control loops using the R, L, Kt and J measured in this same run, so they test the design math, not just the hardware.

| ID | Requirement | Limit | Predicted | Measured (mean ± std) | Result |
|---|---|---|---|---|---|
| REQ-CUR-01 | Current loop rise time (10-90 %) | < 1.5 ms | 0.744 ms | 0.843 ± 0.068 ms | ✅ PASS |
| REQ-CUR-02 | Current loop overshoot | < 10 % | 0.439 % | 7.67 ± 4.5 % | ✅ PASS |
| REQ-CUR-03 | Current loop settling time (5 % band) | < 3 ms | 1.16 ms | 12.2 ± 9.7 ms | ❌ FAIL |
| REQ-CUR-04 | d/q decoupling: peak q-axis error during a d-axis step | < 20 % of step | ≈ 0 % of step | 5.64 ± 2.3 % of step | ✅ PASS |
| REQ-CUR-05 | Current steady-state noise (std of id, 20 ms after the step onward) | < 10 mA | – | 10.5 ± 4.5 mA | ❌ FAIL |
| REQ-SPD-01 | Speed step overshoot (5 to 15 rad/s) | < 20 % | ≈ 0 % | 17.4 ± 5.2 % | ✅ PASS |
| REQ-SPD-02 | Speed step settling time (5 % band) | < 300 ms | 44.7 ms | 705 ± 1.6 ms | ❌ FAIL |
| REQ-SPD-03 | Speed steady-state error | < 2 % | ≈ 0 % | 0.152 ± 0.13 % | ✅ PASS |
| REQ-SPD-04 | Speed ripple at 10 rad/s (std / mean) | < 5 % | – | 10.2 ± 0.27 % | ❌ FAIL |
| REQ-ENC-01 | Encoder read glitches during slow open-loop rotation (jump > 20 counts) | < 0.1 per s | – | 0 per s | ✅ PASS |
| REQ-SYS-01 | Control ISR worst-case CPU load | < 60 % | – | 47.4 % | ✅ PASS |
| REQ-SAF-01 | Host watchdog disables the drive on link loss | yes | – | yes | ✅ PASS |

## Characterization

| Quantity | Measured |
|---|---|
| Phase resistance R | 5.28 ± 0.18 ohm |
| Phase inductance L | 1.17 ± 0.24 mH |
| Electrical time constant L/R | 0.222 ± 0.051 ms |
| Current Kp for 300 Hz (L wc) | 2.03 V/A |
| Current Ki for 300 Hz (R wc) | 9.77e+03 V/(A s) |
| Torque constant Kt (back-EMF) | 0.195 ± 0.009 N m/A |
| Friction current at 10 rad/s | 0.0401 ± 0.0019 A |
| Rotor inertia J (impulse-momentum over the speed step) | 3.28e-05 ± 6.8e-06 kg m² |
| Speed step peak time | 63 ± 32 ms (model 712 ms) |
| Largest encoder jump between ticks | 3 counts |

## Results

### Current loop step

![Current loop step](plots/cur.png)

> Step metrics use the first 20 ms after the step; anything later is reported separately as steady-state noise (REQ-CUR-05).

> Current sense noise before the step is 2.4 % of the step (1 ADC count = 4 mA), so measured overshoot below about twice that is noise, not ringing.

### Speed loop step

![Speed loop step](plots/spd.png)

> Metrics use a 10 ms moving average of vel_mech; the plot shows the raw signal.

### Speed ripple

![Speed ripple](plots/ripple.png)

### Encoder integrity

![Encoder integrity](plots/enc.png)

### R/L identification

![R/L identification](plots/rl.png)

> tau is only 2.2 samples long at 10.4 kHz, so L is coarse (+/- ~25 %). R is unaffected.

## Method

Run with `python run_bench.py` (see `bench/README.md`). The firmware applies each step at an exact control-loop sample and records 2048 samples to RAM; the host downloads the capture over UART and computes every metric from it. Raw captures are in `raw/` as CSV.
