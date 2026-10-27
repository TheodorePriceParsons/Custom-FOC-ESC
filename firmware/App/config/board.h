/*
 * board.h
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */

#ifndef CONFIG_BOARD_H_
#define CONFIG_BOARD_H_

//timing
#define PWM_PERIOD      65527.0f
#define PWM_DUTY_MIN    0.001f
#define PWM_DUTY_MAX    0.95f

#define F_LOOP          10377.0f
#define DT              (1.0f / F_LOOP)

//ADC
#define ADC_VREF        3.3f
#define ADC_MAX         4096.0f

//Current sense
#define R_SHUNT         0.005f
#define CSA_GAIN        40.0f
#define AMPS_PER_COUNT  (ADC_VREF / (ADC_MAX * CSA_GAIN * R_SHUNT))
#define I_SENSE_MAX     ((ADC_VREF / 2.0f) / (CSA_GAIN * R_SHUNT))

//Bus divider
#define VBUS_R_TOP      10000.0f
#define VBUS_R_BOT      3300.0f
#define VOLTS_PER_COUNT ((ADC_VREF / ADC_MAX) * (VBUS_R_TOP + VBUS_R_BOT) / VBUS_R_BOT)

//MT encoder
#define ENC_COUNTS      16384.0f
#define ENC_CPR         16384u          // integer version, power of 2

/* ===================== added for foc.c ===================== */

//ADC DMA buffer order = CubeMX rank order (IN1, IN2, IN5, IN6)
#define ADC_RANK_IA     0
#define ADC_RANK_IB     1
#define ADC_RANK_IC     2
#define ADC_RANK_VBUS   3               // rank 4, the 47.5-cycle one
#define CURRENT_SIGN    (1.0f)
#define I_TRIP          4.0f            // A, any phase -> FAULT
#define DRV_CSA_GAIN_BITS 0x2u          // 0=10 1=20 2=40 3=80 V/V, must match CSA_GAIN

//Bus
#define VBUS_NOMINAL    12.0f
#define VBUS_MIN        6.0f
#define USE_VBUS_SENSE  0               // 1 once the divider is on and reads right

//Motor
#define POLE_PAIRS      11u             // GM4108H 24N22P

//Modulation: |Vdq| limit as fraction of vbus/sqrt3, keeps duty <= PWM_DUTY_MAX
#define VMOD_FRAC       (2.0f * PWM_DUTY_MAX - 1.0f)

//Bring-up
#define OFFSET_SAMPLES  2048u
#define ALIGN_V         1.0f            // V on d-axis during alignment
#define ALIGN_HOLD_S    0.75f
#define VEL_LPF_ALPHA   0.02f

//Current PI starting point (Kp ~ L*wc, Ki ~ R*wc), tune live
#define KP_I            1.0f
#define KI_I            500.0f
//Speed PI (outer loop), runs every SPD_DIV ISR ticks (~1 kHz)
//Tune Kp first with KI_W = 0, then KI_W = 15.7 * KP_W
#define SPD_DIV         10u
#define DT_SPD          (DT * (float)SPD_DIV)
#define KP_W            0.01f           // A per (rad/s)
#define KI_W            0.0f            // A per rad
#define IQ_MAX          0.3f            // A, speed loop output clamp
#define W_SLEW          50.0f           // rad/s^2, setpoint ramp

//DRV8305 registers (Nv7 values, recheck for AON7544 later)
#define DRV_HS_GATE_VAL   0x378u        // IDRIVE 0.25 A, 1758 ns tdrive
#define DRV_LS_GATE_VAL   0x378u
#define DRV_GATE_CTRL_VAL 0x286u        // defaults + 3-PWM mode + 35 ns extra dead time
#define DRV_VDS_SENSE_VAL 0x050u        // VDS trip ~0.109 V


#define HAS_EN_GATE     1
#define HAS_NFAULT      1

#endif
