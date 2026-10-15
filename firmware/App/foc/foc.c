/*
 * foc.c
 *
 *  Created on: Oct 14, 2026
 *      Author: theop
 */

/*
 * foc.c
 * Control layer: never touches registers directly, only App/drivers.
 * Uses your foc_math.c: clarke(), park(alpha,beta,s,c,..), invpark(c,s,d,q,..), svpwm().
 * If you unify the sin/cos argument order, update the two calls marked [ORDER].
 */
#include "foc.h"
#include "board.h"
#include "foc_math.h"
#include "pwm.h"
#include "sense.h"
#include "mt6701.h"
#include "spi_bus.h"
#include "drv8305.h"
#include "main.h"
#include <math.h>

#define TWO_PI_F    6.28318530718f
#define HALF_PI_F   1.57079632679f
#define INV_SQRT3_F 0.57735026919f

/* timing pin for the scope (PA9, TIMING_OUT in your .ioc) */
#define TIMING_HI() (TIMING_OUT_GPIO_Port->BSRR = TIMING_OUT_Pin)
#define TIMING_LO() (TIMING_OUT_GPIO_Port->BRR  = TIMING_OUT_Pin)

static uint16_t enc_last;

foc_t foc;

/* ---------------- helpers ---------------- */

static inline float wrapf(float x)
{
    while (x >= TWO_PI_F) x -= TWO_PI_F;
    while (x <  0.0f)     x += TWO_PI_F;
    return x;
}

static inline int32_t enc_diff(uint16_t a, uint16_t b)   /* a - b, wrapped to +-CPR/2 */
{
    int32_t d = (int32_t)a - (int32_t)b;
    if (d >  (int32_t)(ENC_CPR / 2u)) d -= (int32_t)ENC_CPR;
    if (d < -(int32_t)(ENC_CPR / 2u)) d += (int32_t)ENC_CPR;
    return d;
}

static inline uint32_t enc_dir(uint16_t raw)
{
    uint32_t r = raw & (ENC_CPR - 1u);
    return (foc.dir < 0) ? ((ENC_CPR - r) & (ENC_CPR - 1u)) : r;
}

/* electrical angle in integer math, then one float scale */
static inline float elec_angle_raw(uint16_t raw)
{
    uint32_t e = (enc_dir(raw) * POLE_PAIRS) & (ENC_CPR - 1u);
    return (float)e * (TWO_PI_F / (float)ENC_CPR);
}

/* circle limit, d-axis priority. sets per-axis saturation flags */
static void limit_dq(float *vd, float *vq, float vmax, bool *sat_d, bool *sat_q)
{
    *sat_d = false;
    *sat_q = false;
    if (*vd >  vmax) { *vd =  vmax; *sat_d = true; }
    if (*vd < -vmax) { *vd = -vmax; *sat_d = true; }
    float vq_max = sqrtf(vmax * vmax - (*vd) * (*vd));
    if (*vq >  vq_max) { *vq =  vq_max; *sat_q = true; }
    if (*vq < -vq_max) { *vq = -vq_max; *sat_q = true; }
}

/* apply a dq voltage at electrical angle theta */
static void apply_vdq(float vd, float vq, float theta)
{
    float vmax = VMOD_FRAC * foc.vbus * INV_SQRT3_F;
    bool sat_d, sat_q;
    limit_dq(&vd, &vq, vmax, &sat_d, &sat_q);
    foc.vd_sat = sat_d;
    foc.vq_sat = sat_q;
    foc.v_sat  = sat_d || sat_q;
    foc.vd_out = vd;
    foc.vq_out = vq;

    float s = sinf(theta), c = cosf(theta);
    float va, vb;
    invpark(c, s, vd, vq, &va, &vb);                        /* [ORDER] */
    svpwm(va, vb, foc.vbus, &foc.da, &foc.db, &foc.dc);

    pwm_set_duty(foc.da, foc.db, foc.dc);              /* pwm.c clamps to PWM_DUTY_MIN/MAX */
}

/* PI with conditional integration: freeze integrator when saturated
 * and the error would push further into saturation */
static float pi_out(const pi_t *p, float err) { return p->kp * err + p->integ; }

static void pi_integrate(pi_t *p, float err, bool sat, float out)
{
    if (!sat || (err * out) < 0.0f) p->integ += p->ki * err * DT;
}

static void trip(foc_fault_t f)
{
    pwm_outputs_off();
    foc.fault = f;
    foc.mode  = FOC_FAULT;
}

static bool is_run_mode(foc_mode_t m)
{
    return m == FOC_TEST_PWM || m == FOC_OPENLOOP || m == FOC_ALIGN ||
           m == FOC_VOLTAGE  || m == FOC_CURRENT;
}

/* ---------------- mode entry ---------------- */

static void on_enter(foc_mode_t m)
{
    foc.t_mode = 0.0f;
    pwm_outputs_off();
    pwm_set_duty(0.5f, 0.5f, 0.5f);

    switch (m) {
    case FOC_CALIB:
        foc.n_calib = 0;
        foc.acc[0] = foc.acc[1] = foc.acc[2] = 0;
        foc.calibrated = false;
        break;
    case FOC_ALIGN:
        foc.aligned = false;
        foc.dir = 1;
        foc.elec_offset = 0.0f;
        break;
    case FOC_VOLTAGE:
        if (!foc.calibrated) { trip(FLT_NOT_CALIBRATED); return; }
        if (!foc.aligned)    { trip(FLT_NOT_ALIGNED); return; }
        break;
    case FOC_CURRENT:
        if (!foc.calibrated) { trip(FLT_NOT_CALIBRATED); return; }
        if (!foc.aligned)    { trip(FLT_NOT_ALIGNED); return; }
        foc.pi_d.integ = foc.pi_q.integ = 0.0f;
        break;
    case FOC_OPENLOOP:
        foc.ol_theta = 0.0f;
        break;
    case FOC_IDLE:
        foc.fault = FLT_NONE;
        break;
    default:
        break;
    }

    if (is_run_mode(m)) {
        if (foc.vbus < VBUS_MIN) { trip(FLT_VBUS_LOW); return; }
        pwm_outputs_on();
    }
}

/* ---------------- public ---------------- */

bool foc_init(void)
{
    foc.mode = FOC_IDLE;
    foc.prev_mode = FOC_IDLE;
    foc.dir = 1;
    foc.ol_v = 1.0f;
    foc.ol_speed = 6.28f;            /* 1 electrical rev/s */
    foc.test_da = foc.test_db = foc.test_dc = 0.5f;
    foc.pi_d.kp = foc.pi_q.kp = KP_I;
    foc.pi_d.ki = foc.pi_q.ki = KI_I;
    foc.vbus = VBUS_NOMINAL;

    /* cycle counter for ISR timing */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL  |= DWT_CTRL_CYCCNTENA_Msk;

    pwm_outputs_off();
    spi_bus_init();
    sense_init();
    bool ok = drv8305_init();
    enc_last = mt6701_read_raw();
    if (enc_last == MT6701_ERR) enc_last = 0;
    foc.enc_prev = enc_last;
    return ok;
}

void foc_start(void)
{
    sense_start();
    pwm_start();                     /* counters + master IRQ, outputs stay off */
    foc.mode = FOC_CALIB;            /* ISR picks this up and measures offsets */
}

void foc_poll(void)
{
    static uint32_t last = 0;
    uint32_t now = HAL_GetTick();
    if (now - last < 200u) return;
    last = now;
    /* only touch the shared bus when the encoder isn't needed */
    if (foc.mode == FOC_IDLE || foc.mode == FOC_FAULT) {
        drv8305_read_status();
    }
}

void foc_isr(void)
{
    uint32_t t0 = DWT->CYCCNT;
    TIMING_HI();
    foc.isr_count++;

    /* ---- sense ---- */
    foc.adc_raw[0] = sense_dma[ADC_RANK_IA];
    foc.adc_raw[1] = sense_dma[ADC_RANK_IB];
    foc.adc_raw[2] = sense_dma[ADC_RANK_IC];
    foc.vbus = sense_vbus();

    if (!spi_bus_locked()) {             /* main loop owns the bus -> reuse last angle */
        uint16_t r = mt6701_read_raw();
        if (r != MT6701_ERR) enc_last = r;
    }
    uint16_t raw = enc_last;
    int32_t  d   = enc_diff(raw, foc.enc_prev);
    foc.enc_prev = raw;
    foc.enc_raw  = raw;
    float vel_inst = (float)(foc.dir * d) * (TWO_PI_F / (float)ENC_CPR) / DT;
    foc.vel_mech  += VEL_LPF_ALPHA * (vel_inst - foc.vel_mech);
    foc.theta_mech = (float)enc_dir(raw) * (TWO_PI_F / (float)ENC_CPR);
    foc.theta_e    = wrapf(elec_angle_raw(raw) - foc.elec_offset);

    float s = sinf(foc.theta_e), c = cosf(foc.theta_e);

    if (foc.calibrated) {
        foc.ia = CURRENT_SIGN * ((float)foc.adc_raw[0] - foc.offs[0]) * AMPS_PER_COUNT;
        foc.ib = CURRENT_SIGN * ((float)foc.adc_raw[1] - foc.offs[1]) * AMPS_PER_COUNT;
        foc.ic = CURRENT_SIGN * ((float)foc.adc_raw[2] - foc.offs[2]) * AMPS_PER_COUNT;
        clarke(foc.ia, foc.ib, foc.ic, &foc.i_alpha, &foc.i_beta);
        park(foc.i_alpha, foc.i_beta, s, c, &foc.id, &foc.iq);   /* [ORDER] */

        if (fabsf(foc.ia) > I_TRIP || fabsf(foc.ib) > I_TRIP || fabsf(foc.ic) > I_TRIP) {
            trip(FLT_OVERCURRENT);
        }
    }

    if (is_run_mode(foc.mode) && drv8305_nfault_active()) {
        trip(FLT_DRV_NFAULT);
    }

    /* ---- mode change (from debugger or internal) ---- */
    if (foc.mode != foc.prev_mode) {
        foc.prev_mode = foc.mode;
        on_enter(foc.mode);
        foc.prev_mode = foc.mode;    /* on_enter may have tripped */
    }
    foc.t_mode += DT;

    /* ---- control ---- */
    switch (foc.mode) {

    case FOC_CALIB:
        foc.acc[0] += foc.adc_raw[0];
        foc.acc[1] += foc.adc_raw[1];
        foc.acc[2] += foc.adc_raw[2];
        if (++foc.n_calib >= OFFSET_SAMPLES) {
            for (int k = 0; k < 3; k++) foc.offs[k] = (float)foc.acc[k] / (float)OFFSET_SAMPLES;
            foc.calibrated = true;
            foc.mode = FOC_IDLE;
        }
        break;

    case FOC_TEST_PWM:
        pwm_set_duty(foc.test_da, foc.test_db, foc.test_dc);
        break;

    case FOC_OPENLOOP:
        foc.ol_theta = wrapf(foc.ol_theta + foc.ol_speed * DT);
        apply_vdq(foc.ol_v, 0.0f, foc.ol_theta);
        break;

    case FOC_ALIGN:
        /* step 1: hold theta=0. step 2: hold theta=pi/2. compare encoder. */
        if (foc.t_mode < ALIGN_HOLD_S) {
            apply_vdq(ALIGN_V, 0.0f, 0.0f);
        } else if (foc.t_mode < 2.0f * ALIGN_HOLD_S) {
            if (foc.t_mode - DT < ALIGN_HOLD_S) foc.align_raw0 = raw;   /* first tick of step 2 */
            apply_vdq(ALIGN_V, 0.0f, HALF_PI_F);
        } else {
            foc.align_delta = enc_diff(raw, foc.align_raw0);
            if (foc.align_delta > -40 && foc.align_delta < 40) {   /* < ~1/10 of expected */
                trip(FLT_ALIGN_NO_MOTION);
                break;
            }
            foc.dir = (foc.align_delta > 0) ? 1 : -1;
            /* at align_raw0 the rotor sat at theta_e = 0 */
            foc.elec_offset = elec_angle_raw(foc.align_raw0);
            foc.aligned = true;
            foc.mode = FOC_IDLE;
        }
        break;

    case FOC_VOLTAGE:
        apply_vdq(foc.vd_cmd, foc.vq_cmd, foc.theta_e);
        break;

    case FOC_CURRENT: {
        float ed = foc.id_cmd - foc.id;
        float eq = foc.iq_cmd - foc.iq;
        float vd = pi_out(&foc.pi_d, ed);
        float vq = pi_out(&foc.pi_q, eq);
        apply_vdq(vd, vq, foc.theta_e);
        pi_integrate(&foc.pi_d, ed, foc.vd_sat, vd);
        pi_integrate(&foc.pi_q, eq, foc.vq_sat, vq);
        break;
    }

    case FOC_IDLE:
    case FOC_FAULT:
    default:
        break;
    }

    /* ---- timing ---- */
    foc.isr_cycles = DWT->CYCCNT - t0;
    if (foc.isr_cycles > foc.isr_max_cycles) foc.isr_max_cycles = foc.isr_cycles;
    TIMING_LO();
}

