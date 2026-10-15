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

// ISR-safe (direct register write, no HAL lock)
void pwm_outputs_on(void);
void pwm_outputs_off(void);

#endif /* DRIVERS_PWM_H_ */

