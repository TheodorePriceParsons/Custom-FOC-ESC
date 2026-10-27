# Bench protocol (v1)

ASCII lines over LPUART1 (the ST-LINK virtual COM port), 115200 8N1, `\n` terminated.
Every command gets exactly one reply line: `OK ...` or `ERR <reason>`.
Lines starting with `#` are comments from the board (e.g. `# bench ready` at boot).

Every received command kicks the host watchdog.

| Command | Reply | Notes |
|---|---|---|
| `PING` | `OK` | heartbeat |
| `INFO` | `OK proto= f_loop= cap_n= cap_ch= cap_pre= pole_pairs= build=<date time>` | |
| `WD <ms>` | `OK` | arm the host watchdog (0 = off, max 10000). While armed, if no command arrives for `<ms>` while the drive is running, the ISR trips `FLT_WATCHDOG` |
| `MODE <name>` | `OK` | `IDLE CALIB OPENLOOP ALIGN VOLTAGE CURRENT SPEED`. From `FAULT` only `IDLE` is accepted (clears the fault) |
| `SET <name> <value>` | `OK` | `vd vq` (±3 V), `id iq` (±1 A), `w` (±30 rad/s), `ol_v`, `ol_speed`, gains `kp_i ki_i kp_w ki_w` (≥ 0) |
| `GET` | `OK mode= fault= aligned= vel= w_ref= iq= id= vd= vq= vbus= isr_max= kp_i= ki_i= kp_w= ki_w=` | |
| `CLRMAX` | `OK` | reset the worst-case ISR cycle count |
| `CAP <kind> <decim> [step]` | `OK` | arm a 2048-sample capture, one sample every `<decim>` ISR ticks (1-64). If `step` is given it is written at sample 200 |
| `STAT` | `OK state= n=` | state 0 off, 1 capturing, 2 done |
| `DUMP` | `OK n= ch=` then `n*ch` little-endian float32, then `END` | row-major, sample by sample |
| `ABORT` | `OK` | cancel a capture |

Errors: `CMD` unknown command, `ARG` bad argument, `RANGE` outside the limits above,
`MODE` capture kind needs a different drive mode, `BUSY` capture running, `NODATA` nothing to dump,
`FAULT` clear the fault with `MODE IDLE` first, `LONG` line over 63 characters.

## Capture kinds

| Kind | Required mode | Step writes | Channels |
|---|---|---|---|
| `VD` | VOLTAGE | `vd_cmd` | vd_cmd, id, iq, vel_mech |
| `ID` | CURRENT | `id_cmd` | id_cmd, id, iq, vd_out |
| `IQ` | CURRENT | `iq_cmd` | iq_cmd, iq, id, vq_out |
| `W` | SPEED | `w_cmd` and `w_ref` (bypasses the slew limit) | w_ref, vel_mech, iq_cmd, iq |
| `NONE` | any | nothing | w_ref, vel_mech, iq, theta_mech |

## Fault codes (`fault=` in GET)

0 NONE, 1 OVERCURRENT, 2 DRV_NFAULT, 3 NOT_CALIBRATED, 4 NOT_ALIGNED, 5 VBUS_LOW,
6 ALIGN_NO_MOTION, 7 WATCHDOG, 8 ESTOP
