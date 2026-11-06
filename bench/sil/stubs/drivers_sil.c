/*
 * drivers_sil.c
 * PC versions of App/drivers (pwm, sense, mt6701, spi_bus, drv8305). Same headers, same
 * behaviour at the interface, no registers: duties and outputs go to sil.c, which feeds
 * them to the plant; ADC and encoder values come from the plant.
 */
#include "main.h"
#include "board.h"
#include "pwm.h"
#include "sense.h"
#include "mt6701.h"
#include "spi_bus.h"
#include "drv8305.h"

SilCoreDebug_t sil_coredebug;
SilDWT_t       sil_dwt;
SilGPIO_t      sil_gpioa;
SPI_HandleTypeDef hspi3;

/* ---- read/written by sil.c ---- */
float    sil_duty[3] = { 0.5f, 0.5f, 0.5f };   /* effective duty after HRTIM quantization */
int      sil_outputs_on;
uint16_t sil_enc_raw;
uint32_t sil_tick_ms;
int      sil_nfault;

uint32_t HAL_GetTick(void) { return sil_tick_ms; }

/* ---------------- pwm ---------------- */
static float duty_eff(float duty)
{
    /* same clamp and compare computation as pwm.c, then back to the duty the timer produces */
    if (duty < PWM_DUTY_MIN) duty = PWM_DUTY_MIN;
    else if (duty > PWM_DUTY_MAX) duty = PWM_DUTY_MAX;
    uint32_t cmp1 = (uint32_t)(PWM_PERIOD * (1.0f - duty)) / 2;
    uint32_t cmp2 = (uint32_t)(PWM_PERIOD * (1.0f + duty)) / 2;
    return (float)(cmp2 - cmp1) / PWM_PERIOD;
}

void pwm_set_duty(float a, float b, float c)
{
    sil_duty[0] = duty_eff(a);
    sil_duty[1] = duty_eff(b);
    sil_duty[2] = duty_eff(c);
}
void pwm_start(void)       { pwm_outputs_off(); pwm_set_duty(0.5f, 0.5f, 0.5f); }
void pwm_stop(void)        { pwm_outputs_off(); }
void pwm_outputs_on(void)  { sil_outputs_on = 1; }
void pwm_outputs_off(void) { sil_outputs_on = 0; }

/* ---------------- sense ---------------- */
volatile uint16_t sense_dma[4];
void sense_init(void)  { }
void sense_start(void) { }
float sense_vbus(void)
{
#if USE_VBUS_SENSE
    return (float)sense_dma[ADC_RANK_VBUS] * VOLTS_PER_COUNT;
#else
    return VBUS_NOMINAL;
#endif
}

/* ---------------- encoder ---------------- */
uint16_t mt6701_read_raw(void) { return sil_enc_raw; }
float mt6701_read_rad(void)    { return (float)sil_enc_raw * (6.28318531f / ENC_COUNTS); }

/* ---------------- shared SPI bus ---------------- */
void spi_bus_init(void)         { }
void spi_bus_lock_for_drv(void) { }
void spi_bus_release(void)      { }
bool spi_bus_locked(void)       { return false; }

/* ---------------- gate driver ---------------- */
drv_status_t drv;
uint16_t drv8305_read(uint8_t addr) { (void)addr; return 0; }
void drv8305_write(uint8_t addr, uint16_t data) { (void)addr; (void)data; }
bool drv8305_init(void)
{
    drv.spi_ok = drv.config_ok = true;
    drv.hs_gate_default = 0x344;
    drv.hs_gate = DRV_HS_GATE_VAL;
    drv.gate_ctrl = DRV_GATE_CTRL_VAL;
    return true;
}
void drv8305_read_status(void)  { }
void drv8305_clear_faults(void) { sil_nfault = 0; }
bool drv8305_nfault_active(void) { return sil_nfault != 0; }
