/*
 * plant.c
 * Averaged inverter + PMSM dq model, see plant.h.
 *
 *   v_x      = Vbus (d_x - (d_a + d_b + d_c) / 3)                 phase-to-neutral, averaged
 *   v_ab     = Clarke(v_a, v_b, v_c),  v_dq = Park(v_ab, theta_e)
 *   L did/dt = vd - R id + we L iq
 *   L diq/dt = vq - R iq - we L id - we lam
 *   J dw/dt  = (3/2) p lam iq - Tc sign(w) - B w                  (stiction at w = 0)
 */
#include "plant.h"
#include <math.h>

#define TWO_PI 6.283185307179586

static double urand(plant_t *p)                 /* xorshift64*, [0, 1) */
{
    uint64_t x = p->rng;
    x ^= x >> 12; x ^= x << 25; x ^= x >> 27;
    p->rng = x;
    return (double)((x * 0x2545F4914F6CDD1DULL) >> 11) * (1.0 / 9007199254740992.0);
}

static double nrand(plant_t *p)                 /* standard normal, Box-Muller */
{
    double u1 = urand(p), u2 = urand(p);
    if (u1 < 1e-300) u1 = 1e-300;
    return sqrt(-2.0 * log(u1)) * cos(TWO_PI * u2);
}

void plant_init(plant_t *p, uint64_t seed)
{
    p->R = 5.0;  p->L = 2.0e-3;  p->lam = 0.0125;
    p->J = 6.0e-5;  p->B = 2.0e-4;  p->Tc = 0.005;
    p->pole_pairs = 11;
    p->theta0 = 0.9;
    p->enc_dir = 1;
    p->ecc = 0.6 * TWO_PI / 360.0;
    p->glitch_p = 0.0;
    p->noise_a = 0.003;
    p->adc_off[0] = 3; p->adc_off[1] = -5; p->adc_off[2] = 1;
    p->vbus = 12.0;
    p->amps_per_count = 3.3 / (4096.0 * 40.0 * 0.005);
    p->enc_cpr = 16384;
    p->id = p->iq = p->w = 0.0;
    p->th = 0.3;
    p->rng = seed ? seed : 0x9E3779B97F4A7C15ULL;
}

double plant_theta_e(const plant_t *p)
{
    return fmod(p->pole_pairs * p->th + p->theta0, TWO_PI);
}

void plant_step(plant_t *p, const double d[3], int on, double dt)
{
    double va = 0.0, vb = 0.0, vc = 0.0;
    if (on) {
        double m = (d[0] + d[1] + d[2]) / 3.0;
        va = p->vbus * (d[0] - m);
        vb = p->vbus * (d[1] - m);
        vc = p->vbus * (d[2] - m);
    }
    double v_al = (2.0 / 3.0) * (va - 0.5 * vb - 0.5 * vc);
    double v_be = (vb - vc) / sqrt(3.0);

    const int sub = 8;
    double h = dt / sub;
    double kt = 1.5 * p->pole_pairs * p->lam;
    for (int k = 0; k < sub; k++) {
        double te_ang = plant_theta_e(p);
        double s = sin(te_ang), c = cos(te_ang);
        double vd =  c * v_al + s * v_be;
        double vq = -s * v_al + c * v_be;
        double we = p->pole_pairs * p->w;

        double did = (vd - p->R * p->id + we * p->L * p->iq) / p->L;
        double diq = (vq - p->R * p->iq - we * p->L * p->id - we * p->lam) / p->L;
        p->id += did * h;
        p->iq += diq * h;

        double te = kt * p->iq;
        if (fabs(p->w) < 1e-3 && fabs(te) <= p->Tc) {
            p->w = 0.0;                                         /* stiction */
        } else {
            double sgn = (p->w != 0.0) ? (p->w > 0 ? 1.0 : -1.0) : (te > 0 ? 1.0 : -1.0);
            p->w += (te - p->Tc * sgn - p->B * p->w) / p->J * h;
        }
        p->th += p->w * h;
    }
}

void plant_phase_currents(const plant_t *p, double i[3])
{
    double te = plant_theta_e(p);
    double s = sin(te), c = cos(te);
    double ial = c * p->id - s * p->iq;
    double ibe = s * p->id + c * p->iq;
    i[0] = ial;
    i[1] = -0.5 * ial + 0.8660254037844386 * ibe;
    i[2] = -0.5 * ial - 0.8660254037844386 * ibe;
}

void plant_adc(plant_t *p, uint16_t adc[3])
{
    double i[3];
    plant_phase_currents(p, i);
    for (int k = 0; k < 3; k++) {
        double n = 2048.0 + p->adc_off[k] + (i[k] + p->noise_a * nrand(p)) / p->amps_per_count;
        long r = lround(n);
        if (r < 0) r = 0;
        if (r > 4095) r = 4095;
        adc[k] = (uint16_t)r;
    }
}

uint16_t plant_encoder(plant_t *p)
{
    double th = p->th + p->ecc * sin(p->th + 0.7);
    double turns = th / TWO_PI;
    long raw = lround((turns - floor(turns)) * p->enc_cpr) % (long)p->enc_cpr;
    if (p->enc_dir < 0) raw = ((long)p->enc_cpr - raw) % (long)p->enc_cpr;
    if (p->w != 0.0 && urand(p) < p->glitch_p) {
        raw ^= 1L << (6 + (int)(urand(p) * 6.0));               /* marginal SSI timing */
    }
    return (uint16_t)raw;
}
