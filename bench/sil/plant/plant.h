/*
 * plant.h
 * Averaged model of the power stage + GM4108H motor + MT6701 encoder + shunt ADC chain.
 *
 * "Averaged" = the inverter is modelled by its duty cycles over one PWM period
 * (switching ripple ignored), which is what the control loop sees at 10.4 kHz.
 *
 * Plain C99, no allocation, no OS calls: the same file can later be compiled for the
 * STM32 (PIL) or a second MCU (HIL).
 */
#ifndef SIL_PLANT_H_
#define SIL_PLANT_H_

#include <stdint.h>

typedef struct {
    /* ---- parameters (plausible GM4108H guesses, not measurements) ---- */
    double R, L, lam;          /* ohm, H, V s (per phase, peak flux linkage) */
    double J, B, Tc;           /* kg m^2, N m s, N m (Coulomb friction / stiction) */
    unsigned pole_pairs;
    double theta0;             /* rad elec: rotor d-axis at encoder zero (what ALIGN must find) */
    int    enc_dir;            /* +1 / -1: encoder mounted the other way round */
    double ecc;                /* rad mech: magnet eccentricity error amplitude */
    double glitch_p;           /* probability per read of a flipped bit while moving */
    double noise_a;            /* A rms per phase on the current sense */
    int    adc_off[3];         /* counts: CSA offset error around mid-scale */
    double vbus;               /* V */
    double amps_per_count;     /* from board.h */
    unsigned enc_cpr;

    /* ---- state ---- */
    double id, iq;             /* A, true rotor frame */
    double w, th;              /* rad/s, rad (mechanical) */
    uint64_t rng;
} plant_t;

void     plant_init(plant_t *p, uint64_t seed);

/* Integrate one control period dt with phase duties d[3] (0..1). on = 0: bridge off,
 * low sides conduct, phase voltages 0 (braking). */
void     plant_step(plant_t *p, const double d[3], int on, double dt);

/* Sensors as the firmware reads them at the PWM center. */
void     plant_adc(plant_t *p, uint16_t adc[3]);
uint16_t plant_encoder(plant_t *p);

/* true phase currents (for logging) */
void     plant_phase_currents(const plant_t *p, double i[3]);
double   plant_theta_e(const plant_t *p);

#endif
