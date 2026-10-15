/*
 * foc_math.c
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */
#include "foc_math.h"
#include <math.h>
//note to self: don't optimize out phase c since having all three reduces noises in measurements
void clarke(float a, float b, float c, float *alpha, float *beta) {
	*alpha = (float)TWO_THIRDS*(a-b*0.5f-c*0.5f);
	*beta = (float)ONE_OVER_SQRT3*(b-c);
}

void park(float alpha, float beta, float s, float c, float *d, float *q) {
    *d =  c*alpha + s*beta;
    *q = -s*alpha + c*beta;
}
float wrap_2pi(float x) {
	float mod = fmodf(x, TWO_PI);
	if (mod<0) {
		return mod+TWO_PI;
	}
	return mod;
}
void invpark(float c, float s, float d, float q, float *alpha, float *beta){
	*alpha = c*d-s*q;
	*beta = s*d+c*q;
}

void svpwm(float v_alpha, float v_beta, float v_bus, float *da, float *db, float *dc) {
    float va = v_alpha;
    float vb = -0.5f * v_alpha + SQRT3_OVER_2 * v_beta;
    float vc = -0.5f * v_alpha - SQRT3_OVER_2 * v_beta;


    float vmax = fmaxf(va, fmaxf(vb, vc));
    float vmin = fminf(va, fminf(vb, vc));
    float voff = 0.5f * (vmax + vmin);

    //0.5 duty is the middle point
    float inv = 1.0f / v_bus;
    *da = 0.5f + (va - voff) * inv;
    *db = 0.5f + (vb - voff) * inv;
    *dc = 0.5f + (vc - voff) * inv;

    //clamping
    *da = fminf(fmaxf(*da, 0.0f), 1.0f);
    *db = fminf(fmaxf(*db, 0.0f), 1.0f);
    *dc = fminf(fmaxf(*dc, 0.0f), 1.0f);
}


