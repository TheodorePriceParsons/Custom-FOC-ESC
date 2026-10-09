/*
 * pwm.c
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */
#include "pwm.h"
#include "board.h"



extern HRTIM_HandleTypeDef hhrtim1;


static void DUTY_CYCLE(uint32_t timind, float duty) {
  if (duty < 0.001f) {
    duty = 0.001f;
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
	pwm_set_duty(0.0f, 0.0f, 0.0f);
	HAL_HRTIM_WaveformCounterStart(&hhrtim1, HRTIM_TIMERID_TIMER_A | HRTIM_TIMERID_TIMER_B | HRTIM_TIMERID_TIMER_C);
	HAL_HRTIM_WaveformCounterStart_IT(&hhrtim1, HRTIM_TIMERID_MASTER);
	HAL_HRTIM_WaveformOutputStart(&hhrtim1, HRTIM_OUTPUT_TA1);
	HAL_HRTIM_WaveformOutputStart(&hhrtim1, HRTIM_OUTPUT_TB1);
	HAL_HRTIM_WaveformOutputStart(&hhrtim1, HRTIM_OUTPUT_TC1);
}
void pwm_stop(void) {
	HAL_HRTIM_WaveformOutputStop(&hhrtim1, HRTIM_OUTPUT_TA1);
	HAL_HRTIM_WaveformOutputStop(&hhrtim1, HRTIM_OUTPUT_TB1);
	HAL_HRTIM_WaveformOutputStop(&hhrtim1, HRTIM_OUTPUT_TC1);
}
