

#ifndef DRIVERS_MT6701_H_
#define DRIVERS_MT6701_H_

#include <stdint.h>

#define MT6701_ERR 0xFFFFu

uint16_t mt6701_read_raw(void);
float    mt6701_read_rad(void); // convenience for tests, -1.0f on error

#endif
