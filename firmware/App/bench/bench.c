/*
 * bench.c
 * Host interface for the automated test bench. Protocol: bench/PROTOCOL.md
 *
 * Context rules:
 *   bench_isr()          control ISR (HRTIM, prio 0)  -> capture only, a few loads/stores
 *   LPUART1_IRQHandler   prio BENCH_UART_IRQ_PRIO     -> bytes into a ring buffer
 *   bench_poll()         main loop                    -> parsing, replies, dumps
 */
#include "bench.h"
#include "foc.h"
#include "board.h"
#include "main.h"
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>

#define BENCH_UART   LPUART1
#define RX_SIZE      128u                 /* power of 2 */
#define LINE_MAX     64u
#define MAX_ARGS     4

/* hard limits on anything the host can command */
#define LIM_V        3.0f                 /* V   */
#define LIM_I        1.0f                 /* A   */
#define LIM_W        30.0f                /* rad/s mech, below the ~34 rad/s voltage limit at 12 V */

/* ======================= capture ======================= */

typedef enum { CAP_OFF = 0, CAP_ARMED = 1, CAP_DONE = 2 } cap_state_t;

static float cap[BENCH_CAP_N][BENCH_CAP_CH];
static volatile cap_state_t cap_state;
static volatile uint32_t    cap_n;
static uint32_t             cap_decim, cap_div;
static const volatile float *cap_src[BENCH_CAP_CH];
static volatile float       *step_dst[2];
static float                 step_val;
static bool                  step_en;

/* what each capture kind records, which mode it needs, and what the step writes */
typedef struct {
    const char           *name;
    bool                  any_mode;
    foc_mode_t            mode;
    float                 lim;
    const volatile float *ch[BENCH_CAP_CH];
    volatile float       *dst[2];
} cap_kind_t;

static const cap_kind_t kinds[] = {
    /* d-axis voltage step: identifies R and L, no torque */
    { "VD",   false, FOC_VOLTAGE, LIM_V, { &foc.vd_cmd, &foc.id, &foc.iq, &foc.vel_mech },     { &foc.vd_cmd, 0 } },
    /* d-axis current step: current loop response, no torque, rotor need not be locked */
    { "ID",   false, FOC_CURRENT, LIM_I, { &foc.id_cmd, &foc.id, &foc.iq, &foc.vd_out },       { &foc.id_cmd, 0 } },
    /* q-axis current step: needs a locked rotor */
    { "IQ",   false, FOC_CURRENT, LIM_I, { &foc.iq_cmd, &foc.iq, &foc.id, &foc.vq_out },       { &foc.iq_cmd, 0 } },
    /* speed step: writes w_cmd AND w_ref so the slew limit is bypassed */
    { "W",    false, FOC_SPEED,   LIM_W, { &foc.w_ref, &foc.vel_mech, &foc.iq_cmd, &foc.iq },  { &foc.w_cmd, &foc.w_ref } },
    /* no step: steady-state recording (speed ripple vs rotor angle) */
    { "NONE", true,  FOC_IDLE,    0.0f,  { &foc.w_ref, &foc.vel_mech, &foc.iq, &foc.theta_mech }, { 0, 0 } },
};

void bench_isr(void)
{
    if (cap_state != CAP_ARMED) return;
    if (++cap_div < cap_decim) return;
    cap_div = 0;

    uint32_t n = cap_n;
    if (n == BENCH_CAP_PRE && step_en) {
        if (step_dst[0]) *step_dst[0] = step_val;
        if (step_dst[1]) *step_dst[1] = step_val;
    }
    for (uint32_t k = 0; k < BENCH_CAP_CH; k++) cap[n][k] = *cap_src[k];
    n++;
    cap_n = n;
    if (n >= BENCH_CAP_N) cap_state = CAP_DONE;
}

/* ======================= UART ======================= */

static volatile uint8_t  rx_buf[RX_SIZE];
static volatile uint32_t rx_head, rx_tail;

void LPUART1_IRQHandler(void)
{
    if (BENCH_UART->ISR & (USART_ISR_ORE | USART_ISR_FE | USART_ISR_NE)) {
        BENCH_UART->ICR = USART_ICR_ORECF | USART_ICR_FECF | USART_ICR_NECF;
    }
    while (BENCH_UART->ISR & USART_ISR_RXNE_RXFNE) {
        uint8_t  c = (uint8_t)BENCH_UART->RDR;
        uint32_t h = rx_head, nh = (h + 1u) & (RX_SIZE - 1u);
        if (nh != rx_tail) { rx_buf[h] = c; rx_head = nh; }   /* drop on overflow */
    }
}

static void kick(void) { foc.wd_last = foc.isr_count; }

static void put_c(char c)
{
    while (!(BENCH_UART->ISR & USART_ISR_TXE_TXFNF)) { }
    BENCH_UART->TDR = (uint8_t)c;
}

static void put_s(const char *s) { while (*s) put_c(*s++); }

static void put_u(uint32_t v)
{
    char b[11]; int i = 0;
    do { b[i++] = (char)('0' + v % 10u); v /= 10u; } while (v);
    while (i) put_c(b[--i]);
}

static void put_i(int32_t v)
{
    if (v < 0) { put_c('-'); put_u((uint32_t)(-v)); } else put_u((uint32_t)v);
}

/* fixed-point print, 6 decimals; avoids pulling printf float support */
static void put_f(float x)
{
    if (x != x) { put_s("nan"); return; }
    if (x < 0.0f) { put_c('-'); x = -x; }
    if (x > 4.0e9f) { put_s("inf"); return; }
    uint32_t ip = (uint32_t)x;
    uint32_t fp = (uint32_t)((x - (float)ip) * 1000000.0f + 0.5f);
    if (fp >= 1000000u) { ip++; fp -= 1000000u; }
    put_u(ip);
    put_c('.');
    char b[6];
    for (int i = 5; i >= 0; i--) { b[i] = (char)('0' + fp % 10u); fp /= 10u; }
    for (int i = 0; i < 6; i++) put_c(b[i]);
}

static void kv_u(const char *k, uint32_t v) { put_c(' '); put_s(k); put_c('='); put_u(v); }
static void kv_i(const char *k, int32_t v)  { put_c(' '); put_s(k); put_c('='); put_i(v); }
static void kv_f(const char *k, float v)    { put_c(' '); put_s(k); put_c('='); put_f(v); }

static void ok(void)              { put_s("OK\n"); }
static void err(const char *why)  { put_s("ERR "); put_s(why); put_c('\n'); }

/* ======================= commands ======================= */

static bool parse_f(const char *s, float *out)
{
    char *end;
    float v = strtof(s, &end);
    if (end == s || *end != '\0' || v != v) return false;
    *out = v;
    return true;
}

static float absf(float x) { return x < 0.0f ? -x : x; }

static const struct { const char *name; foc_mode_t m; } modes[] = {
    { "IDLE", FOC_IDLE }, { "CALIB", FOC_CALIB }, { "OPENLOOP", FOC_OPENLOOP },
    { "ALIGN", FOC_ALIGN }, { "VOLTAGE", FOC_VOLTAGE }, { "CURRENT", FOC_CURRENT },
    { "SPEED", FOC_SPEED },
};

static const struct { const char *name; volatile float *p; float lim; } vars[] = {
    { "vd", &foc.vd_cmd, LIM_V }, { "vq", &foc.vq_cmd, LIM_V },
    { "id", &foc.id_cmd, LIM_I }, { "iq", &foc.iq_cmd, LIM_I },
    { "w",  &foc.w_cmd,  LIM_W },
    { "ol_v", &foc.ol_v, LIM_V }, { "ol_speed", &foc.ol_speed, 200.0f },
};

static void cmd_mode(const char *name)
{
    for (unsigned i = 0; i < sizeof modes / sizeof modes[0]; i++) {
        if (strcmp(name, modes[i].name) == 0) {
            if (foc.mode == FOC_FAULT && modes[i].m != FOC_IDLE) { err("FAULT"); return; }
            foc.mode = modes[i].m;
            ok();
            return;
        }
    }
    err("ARG");
}

static void cmd_set(const char *name, const char *val)
{
    float v;
    if (!parse_f(val, &v)) { err("ARG"); return; }

    for (unsigned i = 0; i < sizeof vars / sizeof vars[0]; i++) {
        if (strcmp(name, vars[i].name) == 0) {
            if (absf(v) > vars[i].lim) { err("RANGE"); return; }
            *vars[i].p = v;
            ok();
            return;
        }
    }
    /* gains: non-negative, generous upper bounds */
    if (v < 0.0f) { err("RANGE"); return; }
    if      (strcmp(name, "kp_i") == 0 && v <= 50.0f)    { foc.pi_d.kp = foc.pi_q.kp = v; }
    else if (strcmp(name, "ki_i") == 0 && v <= 100000.0f){ foc.pi_d.ki = foc.pi_q.ki = v; }
    else if (strcmp(name, "kp_w") == 0 && v <= 1.0f)     { foc.pi_w.kp = v; }
    else if (strcmp(name, "ki_w") == 0 && v <= 50.0f)    { foc.pi_w.ki = v; }
    else { err("ARG"); return; }
    ok();
}

static void cmd_get(void)
{
    put_s("OK");
    kv_i("mode", (int32_t)foc.mode);
    kv_i("fault", (int32_t)foc.fault);
    kv_u("aligned", foc.aligned ? 1u : 0u);
    kv_f("vel", foc.vel_mech);
    kv_f("w_ref", foc.w_ref);
    kv_f("iq", foc.iq);
    kv_f("id", foc.id);
    kv_f("vd", foc.vd_out);
    kv_f("vq", foc.vq_out);
    kv_f("vbus", foc.vbus);
    kv_u("isr_max", foc.isr_max_cycles);
    kv_f("kp_i", foc.pi_q.kp);
    kv_f("ki_i", foc.pi_q.ki);
    kv_f("kp_w", foc.pi_w.kp);
    kv_f("ki_w", foc.pi_w.ki);
    put_c('\n');
}

static void cmd_cap(int argc, char **argv)
{
    if (argc < 3) { err("ARG"); return; }
    if (cap_state == CAP_ARMED) { err("BUSY"); return; }

    const cap_kind_t *k = 0;
    for (unsigned i = 0; i < sizeof kinds / sizeof kinds[0]; i++) {
        if (strcmp(argv[1], kinds[i].name) == 0) k = &kinds[i];
    }
    if (!k) { err("ARG"); return; }

    float d;
    if (!parse_f(argv[2], &d) || d < 1.0f || d > 64.0f) { err("ARG"); return; }

    float sv = 0.0f;
    bool  se = (argc >= 4);
    if (se) {
        if (k->dst[0] == 0 || !parse_f(argv[3], &sv)) { err("ARG"); return; }
        if (absf(sv) > k->lim) { err("RANGE"); return; }
    }
    if (!k->any_mode && foc.mode != k->mode) { err("MODE"); return; }

    for (uint32_t c = 0; c < BENCH_CAP_CH; c++) cap_src[c] = k->ch[c];
    step_dst[0] = k->dst[0];
    step_dst[1] = k->dst[1];
    step_val  = sv;
    step_en   = se;
    cap_decim = (uint32_t)d;
    cap_div   = 0;
    cap_n     = 0;
    cap_state = CAP_ARMED;            /* last: ISR starts sampling now */
    ok();
}

static void cmd_dump(void)
{
    if (cap_state != CAP_DONE) { err("NODATA"); return; }
    put_s("OK");
    kv_u("n", BENCH_CAP_N);
    kv_u("ch", BENCH_CAP_CH);
    put_c('\n');
    const uint8_t *p = (const uint8_t *)cap;
    for (uint32_t i = 0; i < sizeof cap; i++) {
        put_c((char)p[i]);
        if ((i & 1023u) == 0u) kick();   /* link is alive while we stream */
    }
    put_s("END\n");
}

static void handle(char *line)
{
    char *argv[MAX_ARGS];
    int argc = 0;
    for (char *t = line; *t && argc < MAX_ARGS; ) {
        while (*t == ' ') *t++ = '\0';
        if (!*t) break;
        argv[argc++] = t;
        while (*t && *t != ' ') t++;
    }
    if (argc == 0) return;

    kick();

    const char *c = argv[0];
    if      (strcmp(c, "PING") == 0) ok();
    else if (strcmp(c, "INFO") == 0) {
        put_s("OK");
        kv_u("proto", BENCH_PROTO_VERSION);
        kv_u("f_loop", (uint32_t)F_LOOP);
        kv_u("cap_n", BENCH_CAP_N);
        kv_u("cap_ch", BENCH_CAP_CH);
        kv_u("cap_pre", BENCH_CAP_PRE);
        kv_u("pole_pairs", POLE_PAIRS);
        put_s(" build=" __DATE__ " " __TIME__ "\n");
    }
    else if (strcmp(c, "WD") == 0) {
        float ms;
        if (argc < 2 || !parse_f(argv[1], &ms) || ms < 0.0f || ms > 10000.0f) { err("ARG"); return; }
        kick();
        foc.wd_timeout = (uint32_t)(ms * F_LOOP / 1000.0f);
        ok();
    }
    else if (strcmp(c, "MODE") == 0)  { if (argc < 2) err("ARG"); else cmd_mode(argv[1]); }
    else if (strcmp(c, "SET") == 0)   { if (argc < 3) err("ARG"); else cmd_set(argv[1], argv[2]); }
    else if (strcmp(c, "GET") == 0)   cmd_get();
    else if (strcmp(c, "CLRMAX") == 0){ foc.isr_max_cycles = 0; ok(); }
    else if (strcmp(c, "CAP") == 0)   cmd_cap(argc, argv);
    else if (strcmp(c, "STAT") == 0)  { put_s("OK"); kv_u("state", (uint32_t)cap_state); kv_u("n", cap_n); put_c('\n'); }
    else if (strcmp(c, "DUMP") == 0)  cmd_dump();
    else if (strcmp(c, "ABORT") == 0) { cap_state = CAP_OFF; ok(); }
    else err("CMD");
}

/* ======================= public ======================= */

void bench_init(void)
{
    rx_head = rx_tail = 0;
    cap_state = CAP_OFF;
    BENCH_UART->CR1 |= USART_CR1_RXNEIE_RXFNEIE;
    HAL_NVIC_SetPriority(LPUART1_IRQn, BENCH_UART_IRQ_PRIO, 0);
    HAL_NVIC_EnableIRQ(LPUART1_IRQn);
    put_s("# bench ready\n");
}

void bench_poll(void)
{
    static char     line[LINE_MAX];
    static uint32_t len;
    static bool     overflow;

    while (rx_tail != rx_head) {
        char c = (char)rx_buf[rx_tail];
        rx_tail = (rx_tail + 1u) & (RX_SIZE - 1u);

        if (c == '\r') continue;
        if (c == '\n') {
            line[len] = '\0';
            if (overflow) err("LONG");
            else handle(line);
            len = 0;
            overflow = false;
        } else if (len < LINE_MAX - 1u) {
            line[len++] = c;
        } else {
            overflow = true;
        }
    }
}

/* Nucleo user button B1 -> latched E-stop (write MODE IDLE to clear) */
void BSP_PB_Callback(Button_TypeDef Button)
{
    if (Button == BUTTON_USER) foc_estop();
}

