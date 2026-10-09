/*
 * foc_math.c
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */
#include "foc_math.h"


void clarke(float a, float b, float c, float *alpha, float *beta) {
	*alpha = (float)TWO_THIRDS*(a-b*0.5f-c*0.5f);
	*beta = (float)ONE_OVER_SQRT3*(b-c);
}
