/*
 * pwm.c
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */
#include "pwm.h"
#include "board.h"

#define PWM_OUT_MASK (HRTIM_OUTPUT_TA1 | HRTIM_OUTPUT_TB1 | HRTIM_OUTPUT_TC1)

extern HRTIM_HandleTypeDef hhrtim1;


static void DUTY_CYCLE(uint32_t timind, float duty) {
  if (duty < PWM_DUTY_MIN) {
    duty = PWM_DUTY_MIN;
  } else if (duty > PWM_DUTY_MAX) {
    duty = PWM_DUTY_MAX;
  }
  __HAL_HRTIM_SetCompare(&hhrtim1, timind, HRTIM_COMPAREUNIT_1,
                         (uint32_t)(PWM_PERIOD * (1.0f - duty)) / 2);
  __HAL_HRTIM_SetCompare(&hhrtim1, timind, HRTIM_COMPAREUNIT_2,
                         (uint32_t)(PWM_PERIOD * (1.0f + duty)) / 2);
}
void pwm_set_duty(float a, float b, float c) {
	DUTY_CYCLE(HRTIM_TIMERINDEX_TIMER_A, a);
	DUTY_CYCLE(HRTIM_TIMERINDEX_TIMER_B, b);
	DUTY_CYCLE(HRTIM_TIMERINDEX_TIMER_C, c);
}
void pwm_start(void) {
	pwm_outputs_off();
	pwm_set_duty(0.5f, 0.5f, 0.5f);
	HAL_HRTIM_WaveformCounterStart(&hhrtim1, HRTIM_TIMERID_TIMER_A | HRTIM_TIMERID_TIMER_B | HRTIM_TIMERID_TIMER_C);
	HAL_HRTIM_WaveformCounterStart_IT(&hhrtim1, HRTIM_TIMERID_MASTER);
	// outputs are enabled by foc.c when a run mode starts
}
void pwm_stop(void) {
	pwm_outputs_off();
}
void pwm_outputs_on(void)  { HRTIM1->sCommonRegs.OENR  = PWM_OUT_MASK; }
void pwm_outputs_off(void) { HRTIM1->sCommonRegs.ODISR = PWM_OUT_MASK; }
