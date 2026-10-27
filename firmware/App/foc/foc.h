/*
 * foc.h
 * Bring-up state machine. Drive it from CubeIDE Live Expressions:
 * write foc.mode and the *_cmd fields while running.
 */
#ifndef FOC_FOC_H_
#define FOC_FOC_H_

#include <stdint.h>
#include <stdbool.h>

typedef enum {
    FOC_IDLE = 0,     /* outputs off, sensing runs */
    FOC_CALIB,        /* outputs off, measure shunt offsets, returns to IDLE */
    FOC_TEST_PWM,     /* fixed duties test_da/db/dc, for scoping */
    FOC_OPENLOOP,     /* rotating voltage vector, no encoder */
    FOC_ALIGN,        /* find encoder offset + direction, returns to IDLE */
    FOC_VOLTAGE,      /* encoder-commutated, vd_cmd/vq_cmd in volts */
    FOC_CURRENT,      /* PI current loops, id_cmd/iq_cmd in amps */
    FOC_SPEED,        /* speed PI -> iq_cmd -> current loops, w_cmd in mech rad/s */
    FOC_FAULT         /* outputs off until you write FOC_IDLE */
} foc_mode_t;

typedef enum {
    FLT_NONE = 0,
    FLT_OVERCURRENT,
    FLT_DRV_NFAULT,
    FLT_NOT_CALIBRATED,
    FLT_NOT_ALIGNED,
    FLT_VBUS_LOW,
	FLT_ALIGN_NO_MOTION,
    FLT_WATCHDOG,         /* host link lost while running */
    FLT_ESTOP             /* user button B1 */
} foc_fault_t;

typedef struct {
    float kp, ki, integ;
} pi_t;

typedef struct {
    /* ---- commands (write these) ---- */
    volatile foc_mode_t mode;
    volatile float test_da, test_db, test_dc;
    volatile float ol_v, ol_speed;        /* V, electrical rad/s */
    volatile float vd_cmd, vq_cmd;        /* V */
    volatile float id_cmd, iq_cmd;        /* A */
    volatile float w_cmd;                 /* mech rad/s, FOC_SPEED setpoint */

    /* ---- state / measurements (watch these) ---- */
    foc_fault_t fault;
    bool     calibrated, aligned;
    uint16_t adc_raw[3];
    float    offs[3];
    float    ia, ib, ic, i_alpha, i_beta, id, iq;
    uint16_t enc_raw;
    float    theta_mech, theta_e, vel_mech;   /* rad, rad, rad/s */
    float    vbus;
    float    vd_out, vq_out, da, db, dc;
    bool     v_sat;             /* true if either axis saturated (telemetry) */
    bool     vd_sat, vq_sat;    /* per-axis, for PI anti-windup */

    /* alignment results */
    int8_t   dir;
    float    elec_offset;
    int32_t  align_delta;      /* expect ~ +-ENC_CPR/(4*POLE_PAIRS) = +-372 */
    volatile uint32_t wd_last, wd_timeout;   /* host watchdog, ISR ticks, 0 = off */
    /* timing */
    uint32_t isr_cycles, isr_max_cycles, isr_count;

    /* internal */
    foc_mode_t prev_mode;
    float    ol_theta, t_mode;
    uint32_t n_calib;
    uint32_t acc[3];
    uint16_t enc_prev, align_raw0;
    pi_t     pi_d, pi_q;
    pi_t     pi_w;              /* speed loop */
    float    w_ref;             /* slew-limited speed setpoint, mech rad/s */
    uint8_t  spd_div;
} foc_t;

extern foc_t foc;

bool foc_init(void);       /* after MX_*_Init. Returns drv8305_init result. */
void foc_start(void);      /* starts PWM timers + ISR, then auto-runs CALIB */
void foc_isr(void);        /* call from HRTIM1_Master_IRQHandler, every 2nd MCMP4 */
void foc_poll(void);       /* call in while(1): DRV status when safe */
void foc_estop(void);

#endif
