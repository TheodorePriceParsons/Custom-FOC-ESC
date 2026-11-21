# Custom FOC ESC: Test Report

**10 / 12 requirements passed** · 2026-11-20 17:11 · N = 3 runs per test

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
| Notes | cogging feedforward learned in-run |

## Requirements

Predicted values come from a model of the firmware's control loops using the R, L, Kt and J measured in this same run, so they test the design math, not just the hardware.

| ID | Requirement | Limit | Predicted | Measured (mean ± std) | Result |
|---|---|---|---|---|---|
| REQ-CUR-01 | Current loop rise time (10-90 %) | < 2.5 ms | 1.84 ms | 1.86 ± 0.04 ms | ✅ PASS |
| REQ-CUR-02 | Current loop overshoot | < 10 % | ≈ 0 % | 4.55 ± 1.5 % | ✅ PASS |
| REQ-CUR-03 | Current loop settling time (5 % band) | < 4 ms | 2.79 ms | 8.82 ± 8.5 ms | ❌ FAIL |
| REQ-CUR-04 | d/q decoupling: peak q-axis error during a d-axis step | < 20 % of step | ≈ 0 % of step | 4.96 ± 1.3 % of step | ✅ PASS |
| REQ-CUR-05 | Current steady-state noise (std of id, 20 ms after the step onward) | < 10 mA | – | 6.44 ± 1.8 mA | ✅ PASS |
| REQ-SPD-01 | Speed step overshoot (5 to 15 rad/s) | < 20 % | ≈ 0 % | 11 ± 1.8 % | ✅ PASS |
| REQ-SPD-02 | Speed step settling time (5 % band) | < 300 ms | 131 ms | 603 ± 88 ms | ❌ FAIL |
| REQ-SPD-03 | Speed steady-state error | < 2 % | ≈ 0 % | 0.237 ± 0.16 % | ✅ PASS |
| REQ-SPD-04 | Speed ripple at 10 rad/s (std / mean) | < 5 % | – | 3.22 ± 0.85 % | ✅ PASS |
| REQ-ENC-01 | Encoder read glitches during slow open-loop rotation (jump > 20 counts) | < 0.1 per s | – | 0 per s | ✅ PASS |
| REQ-SYS-01 | Control ISR worst-case CPU load | < 60 % | – | 50.2 % | ✅ PASS |
| REQ-SAF-01 | Host watchdog disables the drive on link loss | yes | – | yes | ✅ PASS |

## Characterization

| Quantity | Measured |
|---|---|
| Phase resistance R | 5.15 ± 0.023 ohm |
| Phase inductance L | 1.11 ± 0.13 mH |
| Electrical time constant L/R | 0.216 ± 0.025 ms |
| Current Kp for 300 Hz (L wc) | 2.12 V/A |
| Current Ki for 300 Hz (R wc) | 9.71e+03 V/(A s) |
| Torque constant Kt (back-EMF) | 0.202 ± 0.0035 N m/A |
| Friction current at 10 rad/s | 0.0396 ± 0.0028 A |
| Rotor inertia J (impulse-momentum over the speed step) | 2.24e-05 ± 7e-06 kg m² |
| Speed step peak time | 40.2 ± 3.6 ms (model 712 ms) |
| Largest encoder jump between ticks | 3 counts |
| Speed ripple at 10 rad/s without cogging feedforward | 9.77 % |
| Speed ripple at 10 rad/s after learning | 2.14 % |
| Rotor inertia J (from the learning step's response) | 2.1e-05 kg m² |
| Largest feedforward harmonic | 0.0253 A |
| Phase current amplitude mismatch (max - min) / mean | 1.34 ± 0.088 % |
| Worst phase spacing error from 120° | 0.178 ± 0.069 deg |
| Largest phase current DC offset in closed loop | 5.82 ± 1.2 mA |

## Results

### Current loop step

![Current loop step](plots/cur.png)

> Step metrics use the first 20 ms after the step; anything later is reported separately as steady-state noise (REQ-CUR-05).

> Current sense noise before the step is 2.9 % of the step (1 ADC count = 4 mA), so measured overshoot below about twice that is noise, not ringing.

### Speed loop step

![Speed loop step](plots/spd.png)

> Metrics use a 10 ms moving average of vel_mech; the plot shows the raw signal.

### Speed ripple

![Speed ripple](plots/ripple.png)

### Cogging feedforward

![Cogging feedforward](plots/cog.png)

> Learned in 5 updates at 10 rad/s, harmonics 1, 2, 11, 22, 24, 33, 44, 48 per revolution. Later speed tests in this run use it.

### Phase currents

![Phase currents](plots/phase.png)

> 300 mA on the d-axis (no torque) while holding 10 rad/s, so the waveform is large compared with the 4 mA ADC step. Cogging feedforward off for this capture.

### Encoder integrity

![Encoder integrity](plots/enc.png)

### R/L identification

![R/L identification](plots/rl.png)

> tau is only 2.3 samples long at 10.4 kHz, so L is coarse (+/- ~25 %). R is unaffected.

## Method

Run with `python run_bench.py` (see `bench/README.md`). The firmware applies each step at an exact control-loop sample and records 2048 samples to RAM; the host downloads the capture over UART and computes every metric from it. Raw captures are in `raw/` as CSV.
