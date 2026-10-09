/*
 * board.h
 *
 *  Created on: Oct 8, 2026
 *      Author: theop
 */

#ifndef CONFIG_BOARD_H_
#define CONFIG_BOARD_H_

//timing
#define PWM_PERIOD      65527.0f
#define PWM_DUTY_MIN    0.001f
#define PWM_DUTY_MAX    0.95f

#define F_LOOP          10377.0f
#define DT              (1.0f / F_LOOP)

//ADC
#define ADC_VREF        3.3f
#define ADC_MAX         4096.0f

//Current sense
#define R_SHUNT         0.005f
#define CSA_GAIN        40.0f
#define AMPS_PER_COUNT  (ADC_VREF / (ADC_MAX * CSA_GAIN * R_SHUNT))
#define I_SENSE_MAX     ((ADC_VREF / 2.0f) / (CSA_GAIN * R_SHUNT))

//Bus divider
#define VBUS_R_TOP      10000.0f
#define VBUS_R_BOT      3300.0f
#define VOLTS_PER_COUNT ((ADC_VREF / ADC_MAX) * (VBUS_R_TOP + VBUS_R_BOT) / VBUS_R_BOT)

//MT encoder
#define ENC_COUNTS      16384.0f



#endif
