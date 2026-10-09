/*
 * pwm.h
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */

#ifndef DRIVERS_PWM_H_
#define DRIVERS_PWM_H_
#include "main.h"
void pwm_set_duty(float a, float b, float c);
void pwm_start(void);
void pwm_stop(void);

#endif /* DRIVERS_PWM_H_ */
