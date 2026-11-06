# ESC test bench

Automated verification of the ESC against written requirements. One command runs every
test on the hardware, computes the metrics from raw captures and writes a report with
pass/fail per requirement.

```
python run_bench.py --port COM5 --tune-current --note "temporary magnet mount"
```

```
[rl] R/L identification (d-axis voltage step)
  rep 1: R = 4.990 ohm, L = 1.950 mH, tau = 0.391 ms
[cur] Current loop step (d-axis)
  applied design gains Kp_i = 3.676, Ki_i = 9416.9
  rep 1: rise 1.02 ms, overshoot 3.9 %, settle 1.45 ms, q-axis 4.1 %
...
10/10 requirements passed. Report: results/2026-10-26_220738/report.md
```

## How it works

```
 PC (Python)                         NUCLEO-G474RE                          ESC + motor
 run_bench.py ── UART commands ──▶  bench.c: parser, watchdog kick
   suite.py   ◀── binary capture ── bench_isr(): 2048-sample RAM capture,
   analysis.py                        step applied at sample 200 ──────▶  foc_isr() @ 10.4 kHz
   report.py
```

- **Step injection in firmware.** The step lands on an exact control-loop sample, so every
  run is aligned to the same t = 0 and repeat runs overlay exactly.
- **Capture to RAM, then download.** UART at 115200 can't stream 4 channels at 10 kHz, so the ISR
  fills a 32 KB buffer and the host pulls it afterwards. The motor is stopped before the download.
- **Watchdog.** The host sends a heartbeat every 100 ms. If the ESC hears nothing for 300 ms while
  the motor is running, the control ISR disables the outputs (`FLT_WATCHDOG`). This covers a
  crashed script, a pulled USB cable and a hung main loop.
- **E-stop.** The blue B1 button on the Nucleo latches `FLT_ESTOP` from any state.
- **Every test leaves the drive idle**, including on errors and Ctrl+C.

## Tests

| Test | What it does | Measures |
|---|---|---|
| `rl` | 1 V d-axis voltage step, rotor free (no torque on the d-axis) | R, L, L/R, current-loop gains for 300 Hz |
| `cur` | d-axis current step 0.05 → 0.25 A | rise, overshoot, settling, d/q decoupling |
| `spd` | speed step 5 → 15 rad/s, slew limit bypassed | overshoot, settling, steady-state error |
| `ripple` | hold 10 rad/s for ~5 revolutions | speed ripple, ripple vs rotor angle, Kt from back-EMF, friction current |
| `wd` | spin at 5 rad/s, host goes silent for 600 ms | watchdog trips |
| `estop` | spin at 5 rad/s, you press B1 (interactive, not in the default hardware run; automatic in SIL) | E-stop trips |
| `isr` | worst-case ISR cycle count over the whole run | CPU load |

Requirements and their limits live in [`spec.py`](spec.py); the report reads them from there.

## Predicted vs measured

Each run also predicts its own results. The current loop model is the firmware's discrete PI
(including the one-sample PWM update delay) on an R-L phase with the R and L measured by `rl`.
The speed loop model is the firmware's speed PI, its 33 Hz speed filter and a rotor with the
Kt from `ripple` and the J identified from the speed step itself:

J (ω(t_pk) − ω0) = Kt ∫ (iq − i_friction(ω)) dt, from the step to the peak of the filtered speed.

At that peak d(vel)/dt = 0, so the filter output equals the true speed and its lag drops out.
Friction is a straight line between the steady states before and after the step.
The model curves are drawn on the plots and the predicted metrics sit next to the measured ones.
On the simulator the identification recovers R, Kt and J within 2 % and L within ~10 %, and the
predicted speed overshoot is within 1.5 points of the measured one.

## Where the numbers come from

**Current loop.** With Kp = L·ωc and Ki = R·ωc the PI zero cancels the motor pole, so the
closed loop is first order: i/i_cmd = ωc / (s + ωc). For ωc = 2π·300 rad/s:
τ = 1/ωc = 0.53 ms, rise (10-90 %) = ln 9 · τ = 1.17 ms, 5 % settling = ln 20 · τ = 1.6 ms, no overshoot.

**Speed loop.** With iq ≈ iq_cmd the plant is Kt / (J s). A PI with ζ = 1 gives
ω/ω_ref = (2ωn s + ωn²) / (s + ωn)², whose step response is 1 − e^(−ωn t) + ωn t e^(−ωn t).
Its derivative is zero at ωn t = 2, so the peak is at 2/ωn and the overshoot is e^(−2) = 13.5 %
(caused by the PI zero, not by low damping).

**R and L.** A d-axis voltage step gives id(t) = (V/R)(1 − e^(−t/τ)): R = V / id(∞), τ from a
straight-line fit of ln(1 − id/id(∞)), L = τR.

**Kt.** At steady speed vq = R·iq + ωe·λ, so λ = (vq − R·iq)/ωe and Kt = (3/2)·p·λ.

## Three targets, one suite

The same `suite.py` runs against three targets. Only the transport changes.

| Target | Flag | What is real | What is modelled | Use it for |
|---|---|---|---|---|
| Hardware | `--port COM5` | firmware, MCU, power stage, motor | nothing | final verification |
| **SIL** | `--sil` | **the firmware C code** (`foc.c`, `foc_math.c`, `bench.c`, unmodified) | MCU peripherals, bridge, motor, encoder, ADC (`sil/plant/`) | every change to the control code, in ~3 s |
| MIL | `--sim` | nothing | a Python re-implementation of the firmware loops and the plant (`sim.py`) | developing host-side analysis |

### SIL: how the firmware runs on the PC

```
 sil_transport.py (ctypes)                 libescsil (gcc/g++)
   write(bytes) ───────────────────────▶  LPUART1 "registers" ─▶ bench.c parser (real)
   readline()/read() ◀──────────────────  TDR writes ◀────────── bench.c replies (real)
   sleep(s) ── sil_run(n ticks) ───────▶  per tick:
                                            1. plant → ADC counts + encoder raw
                                            2. foc_isr() (real) → duties d[k]
                                            3. plant integrates with d[k-1]
```

- **Unmodified firmware.** `foc.c`, `foc_math.c` and `bench.c` are compiled straight from
  `firmware/App/`. Only `main.h` (registers foc.c touches) and `App/drivers/*.c` are replaced, by
  `sil/stubs/`. `bench.c` is built as C++ so its UART registers can be objects that move bytes.
- **Averaged plant** (`sil/plant/plant.c`): phase voltages from the duty cycles,
  `v_x = Vbus (d_x − mean(d))`, then the dq PMSM equations with Coulomb friction and stiction,
  ADC quantization, noise and offsets, encoder eccentricity and optional bit glitches. Electrical
  offset and encoder direction are unknown to the firmware, so ALIGN has to find them.
- **Hardware timing**: sample at the PWM center, one-sample PWM update delay, HRTIM compare
  quantization of the duty, immediate output disable on a trip.
- **Ground truth.** `SilTransport.truth("iq")` returns the plant's real state, so tests can check
  the firmware against what actually happened, not against its own measurements
  (`tests/test_sil.py`: alignment for several offsets and both encoder directions, overcurrent,
  gate-driver fault, watchdog, protocol errors).
- **Not covered by SIL:** ISR timing (REQ-SYS-01 reports NO DATA), peripheral setup, SPI and
  ADC timing. That is what PIL/HIL is for.

With the board's speed gains, SIL measures about 19 % speed overshoot (peak at ~108 ms) against a
model prediction of 18.4 % (peak at 103 ms): the real control code and the loop model agree within a point.

### Next: PIL and HIL

- **PIL**: build the firmware for the STM32 with `-DPIL=1` so `sense`/`mt6701` read from
  `plant.c` running inside the ISR on the G474 instead of the ADC and SPI. Same plant source
  (plain C99), real compiler, real FPU, real cycle counts: REQ-SYS-01 becomes measurable with
  the plant cost subtracted.
- **HIL**: the unmodified board firmware drives a second board that *is* the motor: it captures
  the three PWM signals, runs `plant.c` in real time, outputs the three shunt voltages on DACs into
  the ADC pins and answers the MT6701 SSI reads. A G474 can do it at ~100 kHz; an FPGA can
  emulate the PWM edges and SSI exactly.

## Setup

```
pip install -r requirements.txt
python run_bench.py --list-ports
python run_bench.py --sil                 # whole suite on the real firmware compiled for the PC (needs gcc/g++)
python run_bench.py --sim                 # whole suite against the Python model, no compiler needed
python -m pytest tests                    # metric code against signals with known answers
```

`--sil` needs a host gcc/g++ (or clang). On Windows: MSYS2 `pacman -S mingw-w64-ucrt-x86_64-gcc` and add
`C:\msys64\ucrt64\bin` to PATH, or run from WSL. The library rebuilds when a source file is newer than it. Files copied in with an older date don't
trigger that: delete `sil/build/` to force a rebuild.

To put a run in the main README (table + plots, replacing the previous one):

```
python publish.py results/2026-10-27_101500
```

Options: `-n 5` runs per test, `--tests rl,cur` a subset, `--align` re-align the encoder first,
`--tune-current` load the current gains computed from the measured R and L, `-v` print the traffic.

## Files

| File | |
|---|---|
| `run_bench.py` | command line entry point |
| `suite.py` | test procedures |
| `spec.py` | requirements (IDs, limits) |
| `analysis.py` | step, first-order fit and ripple metrics |
| `report.py` | plots and Markdown report |
| `publish.py` | copies a run's plots to `docs/images/bench/` and rewrites the results block in the main README |
| `esc_link.py` | protocol client, watchdog heartbeat |
| `sim.py` | MIL: Python model of the ESC with the same protocol (dq motor model, firmware loops re-implemented) |
| `sil_transport.py` | SIL: builds `sil/` + `firmware/App` into a shared library and drives it through ctypes |
| `sil/sil.c` | SIL harness: tick order, UART byte queues, plant parameters, ground truth |
| `sil/plant/` | averaged inverter + PMSM + sensor model in plain C99 (reusable for PIL/HIL) |
| `sil/stubs/` | PC replacements for `main.h` and `App/drivers/*.c` |
| `sil/bench_sil.cpp` | compiles the unmodified `bench.c` with C++ register objects for LPUART1 |
| `tests/test_sil.py` | firmware behaviour checked against plant ground truth |
| `PROTOCOL.md` | wire protocol |
| `../firmware/App/bench/` | firmware side |
