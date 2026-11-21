# Scope traces

Four captures with the Analog Discovery 3. The first two go in the main README; the other two
belong in the bring-up notes. Export every capture as CSV (Scope > File > Export > Data) and
replot it with `bench/scope_plot.py`, so the scope figures match the bench report.

**Rules for every shot**
- All probe grounds go to the supply minus (the XT60 negative), never to a switch node.
- Supply current limit at 0.5 A, as for the bench runs.
- Run the bench `cog` test (or paste the learned `COG_TABLE` into `board.h`) first, so the motor
  spins smoothly while you capture.

## 1. SVPWM signature (README)

Shows the min/max injection from `docs/control-math.md` on real hardware: each phase-to-ground
voltage has the flattened "saddle" shape, while the line-to-line difference is a clean sine.

- **Filter:** an RC low-pass on each of phases A and B, 10 kΩ in series and 100 nF to supply minus.
  The corner is 1/(2π · 10 kΩ · 100 nF) ≈ 160 Hz. That is far below the PWM frequency, so the
  switching is removed, and well above the 40 to 50 Hz electrical frequency, so the shape survives
  (about 16° of lag, the same on both channels).
- **Probes:** CH1 on the phase A capacitor, CH2 on the phase B capacitor.
- **Drive:** `python bench/scope_setup.py --port COM3 --signal off --speed 25`
  (25 rad/s → 44 Hz electrical; the back-EMF is about 3.8 V, so the modulation is deep enough
  for the saddle to show).
- **Scope:** 10 ms/div, both channels on the ±25 V range (or ±5 V with a 6 V offset), trigger
  CH1 rising at 6 V. Average 8 to 16 captures.
- **Plot:** `python bench/scope_plot.py svpwm.csv --title "SVPWM: phase voltage and line-to-line" --labels "phase A" "phase B" --diff "A − B" -o svpwm.png`

## 2. Phase current through the DAC (README)

The current the controller actually regulates, read out live without a current probe.

- **Probes:** CH1 on PA4 (Nucleo A2), CH2 on PA9 (TIMING_OUT) if you want the ISR marker.
- **Drive:** `python bench/scope_setup.py --port COM3 --signal ia --gain 2 --speed 10 --id 0.3`
  (0.3 A on the d-axis makes no torque but lifts the waveform well above the 4 mA ADC step;
  with 2 V/A the sine is ±0.6 V around 1.65 V).
- **Scope:** 20 ms/div, CH1 ±2.5 V range, trigger CH1 rising at 1.65 V.
- **Plot:** `python bench/scope_plot.py ia.csv --title "Phase current, closed-loop FOC" --labels "i_a" --offset 1.65 --scale 0.5 --unit A -o ia.png`

The bench `phase` test makes the three-phase version of this plot from the UART capture, so
you only need the scope shot if you want a real instrument trace in the README.

## 3. Switch-node edge (bring-up)

Dead time and ringing on one half-bridge. This also answers whether the ringing peak stays below
the AON7544's 30 V rating.

- **Probe:** CH1 directly on SHA with a ground spring to the nearest GND pad. Don't use the long
  ground lead; it adds tens of nanoseconds of fake ringing.
- **Drive:** `--signal off --speed 10`.
- **Scope:** 50 ns/div, ±25 V range, trigger on the rising edge at 6 V, maximum sample rate.
- **What to read off:** dead time (flat step before the edge), overshoot peak, ringing frequency.

## 4. ISR timing (bring-up)

- **Probes:** CH1 on PA9 (TIMING_OUT, high for the whole ISR), CH2 on PA8 (HRTIM CHA1).
- **Scope:** 20 µs/div, trigger CH1 rising.
- **What to read off:** the ISR starts at the PWM center (where the ADC samples) and its high
  time over the 96 µs period is the CPU load (the bench `isr` test reports the worst case).

## DAC signals

`SET dac <n>` over the bench link, or `foc.dac_sel` in Live Expressions:

| n | Signal | Scale |
|---|---|---|
| 0 | off (1.65 V) | |
| 1, 2, 3 | ia, ib, ic | 1.65 V + gain × A |
| 4, 5 | iq, id | 1.65 V + gain × A |
| 6 | electrical angle | 0 to 3.3 V sawtooth |
| 7 | cogging feedforward iq_ff | 1.65 V + gain × A |
| 8 | speed | 1.65 V + gain × rad/s |
