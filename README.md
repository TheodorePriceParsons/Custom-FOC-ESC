


# Custom FOC ESC

A field-oriented-control motor controller designed from scratch: a 4-layer power board, STM32G474 firmware with cascaded current and speed loops, and an automated hardware-in-the-loop test bench that verifies the drive against written requirements.




https://github.com/user-attachments/assets/c9957159-f915-4ab0-a1e7-d9c9039c102c



*First closed-loop FOC spin (Oct 2026); kept for sentimental value.*

![FOC ESC 3D render](images/ESC_final_rev.png)

## Highlights

- **Hardware:** DRV8305 gate driver, AON7544 MOSFETs, 5 mΩ low-side shunts on all three phases, MT6701 magnetic encoder, 4-layer stackup with dedicated ground and power planes.
- **Firmware:** sensored FOC at 10.4 kHz on the STM32G474's high-resolution timer, min/max SVPWM, PI current loops with conditional-integration anti-windup, and an outer speed loop. Worst-case ISR load is 37 to 46 % of the cycle budget.
- **Verification:** one command runs every test on the hardware, identifies the motor (R, L, Kt, J), predicts each result from those parameters, and reports predicted vs measured with pass/fail per requirement.
- **Safety:** host watchdog in the control ISR, latched E-stop, overcurrent and gate-driver fault trips.

## Test results

<!-- bench:start -->
Results are published here from the test bench with `python bench/publish.py <run folder>`.
<!-- bench:end -->

## How it works

```
 NUCLEO-G474RE                                        ESC board                    GM4108H motor
 ┌──────────────────────────────────────────┐        ┌─────────────────────┐
 │ HRTIM ── 3 x PWM (center-aligned) ───────┼──────▶ │ DRV8305 → 3 half-   │ ───▶ phases A/B/C
 │   └─ ADC trigger at PWM center           │        │ bridges (AON7544)   │
 │ ADC1 + DMA ◀── 3 shunt amplifiers ───────┼─────── │ 5 mΩ shunts, 40 V/V │
 │ SPI3 (shared bus) ◀──────────────────────┼─────── │ DRV8305 config/stat │
 │                  ◀──────────────────────┼─────── │ MT6701 encoder (SSI)│ ◀── magnet on rotor
 │ foc_isr() @ 10.38 kHz                    │        └─────────────────────┘
 │ LPUART1 ◀──▶ test bench (PC)             │
 └──────────────────────────────────────────┘
```

Each control period:

1. The HRTIM triggers the ADC at the PWM center, when all low-side switches are on and the shunts carry the phase currents.
2. The ISR reads the encoder, converts the mechanical angle to the electrical angle, and transforms the phase currents into the rotor frame (Clarke, then Park), where they are DC.
3. Two PI controllers regulate $i_d$ to 0 and $i_q$ to the torque command. Every 10th tick the speed PI sets the $i_q$ command.
4. The voltage command is transformed back (inverse Park) and turned into three duty cycles with min/max SVPWM, which reaches the full $V_{bus}/\sqrt{3}$ phase voltage.

The derivations, including the PI design by pole-zero cancellation, the speed loop design and the expected step responses, are in [docs/control-math.md](docs/control-math.md).

## Test bench

The bench (in [`bench/`](bench/)) drives the ESC over UART from Python:

```
python bench/run_bench.py --port COM5 --tune-current
```

- The firmware injects each step at an exact control-loop sample and records 2048 samples to RAM; the PC downloads the capture and computes every metric from it.
- It measures R and L from a d-axis voltage step, computes current-loop gains for 300 Hz bandwidth, then verifies the loop it just tuned.
- Each result is predicted from the parameters measured in the same run, so the report checks the design math as well as the hardware.
- Requirements have IDs and limits in [`bench/spec.py`](bench/spec.py); each test runs N times and reports mean ± std.
- The host software is checked against a plant simulator with the same protocol (`--sim`), and the metric code has unit tests.

Details: [bench/README.md](bench/README.md), wire protocol: [bench/PROTOCOL.md](bench/PROTOCOL.md).

## Hardware

| | |
|---|---|
| Gate driver | TI DRV8305, 3-PWM mode, SPI configuration, integrated current-sense amplifiers (40 V/V) |
| Power stage | AON7544 N-channel MOSFETs, 3 half-bridges |
| Current sensing | 5 mΩ low-side shunts on all three phases (±8 A sense range), sampled at PWM center |
| Position | MT6701 14-bit magnetic encoder over SSI, sharing one SPI bus with the DRV8305 |
| Stackup | 4 layers: power stage, solid ground, PVDD plane, signals |
| Power | 3S LiPo (12 V), XT60; 2 mm bullet connectors for swappable motor leads |
| Controller | NUCLEO-G474RE (Cortex-M4F, 170 MHz) |
| Motor | GM4108H-120T gimbal motor, 11 pole pairs |

KiCad projects are in `hardware/` and motor mounts in `mechanical/`.

## Bring-up notes

Four wiring and configuration mistakes took most of the bring-up time:

1. The board ground was on the bench supply's earth terminal, so PVDD was never powered. The Nucleo back-fed 3.3 V into the DRV8305's regulator pin, which made PWRGD look healthy while SPI read all zeros.
2. The nFAULT jumper was on the wrong Nucleo pin, so the MCU read a floating input.
3. PWM went to the INL inputs; in 3-PWM mode the DRV8305 ignores INL, so every low-side gate sat on.
4. One ADC pin on the Nucleo gave a large drifting offset. Swapping channels proved the board signal was clean, and moving phase C to another pin fixed it.

## Repository

| Folder | Contents |
|---|---|
| `firmware/` | STM32CubeIDE project. Control code in `App/foc/`, drivers in `App/drivers/`, bench interface in `App/bench/` |
| `hardware/` | KiCad projects for each board revision |
| `mechanical/` | Motor and encoder mounts (STEP) |
| `bench/` | Automated test bench, requirements, reports |
| `docs/` | Control math and figures |
