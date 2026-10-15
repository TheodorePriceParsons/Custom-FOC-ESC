/*
 * foc_math.h
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */

#ifndef FOC_FOC_MATH_H_
#define FOC_FOC_MATH_H_

#define SQRT3_2 0.86602540f
#define TWO_THIRDS 0.66666667f
#define ONE_OVER_SQRT3 0.57735027f
#define TWO_PI 6.28318531f
#define SQRT3_OVER_2 0.86602540f
//function prototypes
void clarke(float a, float b, float c, float *alpha, float *beta);
void park(float alpha, float beta, float s, float c, float *d, float *q);
float wrap_2pi(float x);
void invpark(float c, float s, float d, float q, float *alpha, float *beta);
void svpwm(float v_alpha, float v_beta, float v_bus, float *da, float *db, float *dc);
#endif /* FOC_FOC_MATH_H_ */
