/*
 * sil.c
 * Software-in-the-loop harness: the real foc.c / foc_math.c / bench.c, compiled for the PC,
 * closed around the plant model in plant/plant.c. Python drives it through ctypes
 * (sil_transport.py) with the same byte stream it sends to the Nucleo.
 *
 * One control period, in hardware order:
 *   1. ADC + encoder sampled at the PWM center      -> sense_dma[], encoder
 *   2. foc_isr() runs (and bench_isr() inside it)   -> new duties d[k]
 *   3. the bridge applies d[k-1] for this period    (compare registers are preloaded,
 *      d[k] takes effect at the next update event: one-sample delay)
 *   4. d[k] becomes the applied duty for the next period
 * Output disable (pwm_outputs_off) acts immediately, as the HRTIM ODISR write does.
 */
#include <stdlib.h>
#include <string.h>
#include "plant.h"
#include "foc.h"
#include "bench.h"
#include "board.h"
#include "sense.h"
#include "main.h"

#if defined(_WIN32)
#define SIL_API __declspec(dllexport)
#else
#define SIL_API __attribute__((visibility("default")))
#endif

/* drivers_sil.c */
extern float    sil_duty[3];
extern int      sil_outputs_on;
extern uint16_t sil_enc_raw;
extern uint32_t sil_tick_ms;
extern int      sil_nfault;

/* bench.c (C linkage, compiled in bench_sil.cpp) */
void LPUART1_IRQHandler(void);
void BSP_PB_Callback(Button_TypeDef Button);

static plant_t  P;
static double   applied[3] = { 0.5, 0.5, 0.5 };
static uint64_t ticks;
static int      started, plant_ready;

static void ensure_plant(void)
{
    if (!plant_ready) { plant_init(&P, 1); plant_ready = 1; }
}

/* ---------------- UART byte queues ---------------- */
#define RXQ 4096u
static uint8_t  rxq[RXQ];
static uint32_t rx_h, rx_t;
static uint8_t *txb;
static size_t   tx_len, tx_cap, tx_pos;

int sil_rx_pending(void) { return rx_h != rx_t; }

uint8_t sil_rx_pop(void)
{
    if (rx_h == rx_t) return 0;
    uint8_t b = rxq[rx_t];
    rx_t = (rx_t + 1u) % RXQ;
    return b;
}

void sil_tx_push(uint8_t b)
{
    if (tx_len == tx_cap) {
        size_t n = tx_cap ? 2 * tx_cap : 65536;
        uint8_t *p = (uint8_t *)realloc(txb, n);
        if (!p) return;
        txb = p;
        tx_cap = n;
    }
    txb[tx_len++] = b;
}

/* ---------------- one control period ---------------- */
static void sample(void)
{
    uint16_t adc[3];
    plant_adc(&P, adc);
    sense_dma[ADC_RANK_IA] = adc[0];
    sense_dma[ADC_RANK_IB] = adc[1];
    sense_dma[ADC_RANK_IC] = adc[2];
    sense_dma[ADC_RANK_VBUS] = (uint16_t)(P.vbus / VOLTS_PER_COUNT);
    sil_enc_raw = plant_encoder(&P);
}

static void tick(void)
{
    sample();
    foc_isr();
    plant_step(&P, applied, sil_outputs_on, (double)DT);
    for (int k = 0; k < 3; k++) applied[k] = sil_duty[k];
    ticks++;
    sil_tick_ms = (uint32_t)(ticks * 1000u / (uint64_t)F_LOOP);
}

/* ---------------- API (ctypes) ---------------- */

/* Boot like main(): foc_init, bench_init, foc_start (which runs CALIB). Once per process. */
SIL_API int sil_init(uint64_t seed)
{
    if (started) return -1;
    ensure_plant();                         /* keeps parameters set with sil_param() */
    if (seed) P.rng = seed;
    sample();
    if (!foc_init()) return -2;
    bench_init();
    foc_start();
    started = 1;
    return 0;
}

/* Plant parameters, set before or between runs. Returns 0 if the name is unknown. */
SIL_API int sil_param(const char *name, double v)
{
    ensure_plant();
    if      (!strcmp(name, "R"))        P.R = v;
    else if (!strcmp(name, "L"))        P.L = v;
    else if (!strcmp(name, "lam"))      P.lam = v;
    else if (!strcmp(name, "J"))        P.J = v;
    else if (!strcmp(name, "B"))        P.B = v;
    else if (!strcmp(name, "Tc"))       P.Tc = v;
    else if (!strcmp(name, "theta0"))   P.theta0 = v;
    else if (!strcmp(name, "enc_dir"))  P.enc_dir = v < 0 ? -1 : 1;
    else if (!strcmp(name, "ecc"))      P.ecc = v;
    else if (!strcmp(name, "glitch_p")) P.glitch_p = v;
    else if (!strcmp(name, "noise_a"))  P.noise_a = v;
    else if (!strcmp(name, "vbus"))     P.vbus = v;
    else if (!strcmp(name, "nfault"))   sil_nfault = v != 0.0;
    else return 0;
    return 1;
}

/* Ground truth for tests: what the plant really did, not what the firmware measured. */
SIL_API double sil_truth(const char *name)
{
    ensure_plant();
    if (!strcmp(name, "w"))       return P.w;
    if (!strcmp(name, "th"))      return P.th;
    if (!strcmp(name, "id"))      return P.id;
    if (!strcmp(name, "iq"))      return P.iq;
    if (!strcmp(name, "theta_e")) return plant_theta_e(&P);
    if (!strcmp(name, "t"))       return (double)ticks * (double)DT;
    if (!strcmp(name, "on"))      return sil_outputs_on;
    return 0.0;
}

SIL_API void sil_run(uint32_t n)
{
    while (n--) tick();
}

/* Host -> board bytes. The UART IRQ moves them into bench.c's ring buffer and the main loop
 * (bench_poll) parses complete lines, between control periods as on the target. */
SIL_API void sil_write(const uint8_t *data, uint32_t n)
{
    for (uint32_t i = 0; i < n; i++) {
        uint32_t nh = (rx_h + 1u) % RXQ;
        if (nh != rx_t) { rxq[rx_h] = data[i]; rx_h = nh; }
        LPUART1_IRQHandler();
        if (data[i] == '\n') bench_poll();
    }
    bench_poll();
}

/* Board -> host bytes. Returns how many were copied. */
SIL_API uint32_t sil_read(uint8_t *out, uint32_t max)
{
    size_t n = tx_len - tx_pos;
    if (n > max) n = max;
    memcpy(out, txb + tx_pos, n);
    tx_pos += n;
    if (tx_pos == tx_len) tx_pos = tx_len = 0;
    return (uint32_t)n;
}

/* Nucleo B1 */
SIL_API void sil_press_estop(void) { BSP_PB_Callback(BUTTON_USER); }
