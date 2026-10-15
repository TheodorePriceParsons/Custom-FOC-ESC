/*
 * drv8305.c
 * Frame: [15] R/W (1 = read) | [14:11] addr | [10:0] data.
 * Same frame as your DRV_Read / DRV_Write. Bit positions in reg 0x9 (CLR_FLTS)
 * and 0xA (gain fields) from the datasheet register map; Nv7's 0x2A for 40 V/V
 * confirms the 0xA layout.
 */
#include "drv8305.h"
#include "spi_bus.h"
#include "board.h"
#include <math.h>
drv_status_t drv;

static uint16_t xfer(uint16_t w)
{
    uint16_t r = 0;
    HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_RESET);
    HAL_SPI_TransmitReceive(SPI_BUS, (uint8_t *)&w, (uint8_t *)&r, 1, 5);
    HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_SET);
    for (volatile int i = 0; i < 60; i++) { }    /* nSCS high time between frames */
    return r;
}

uint16_t drv8305_read(uint8_t addr)
{
    uint16_t cmd = (uint16_t)((1u << 15) | ((addr & 0xFu) << 11));
    spi_bus_lock_for_drv();
    uint16_t r = xfer(cmd);
    spi_bus_release();
    return r & 0x7FFu;
}

void drv8305_write(uint8_t addr, uint16_t data)
{
    uint16_t cmd = (uint16_t)(((addr & 0xFu) << 11) | (data & 0x7FFu));
    spi_bus_lock_for_drv();
    (void)xfer(cmd);
    spi_bus_release();
}

void drv8305_read_status(void)
{
    drv.warn   = drv8305_read(DRV_REG_WARN);
    drv.ov_vds = drv8305_read(DRV_REG_OV_VDS);
    drv.ic     = drv8305_read(DRV_REG_IC_FAULT);
    drv.vgs    = drv8305_read(DRV_REG_VGS_FAULT);
}

void drv8305_clear_faults(void)
{
    uint16_t v = drv8305_read(DRV_REG_IC_OP);
    drv8305_write(DRV_REG_IC_OP, v | (1u << 1));   /* CLR_FLTS, self-clearing */
}

bool drv8305_nfault_active(void)
{
#if HAS_NFAULT
    return HAL_GPIO_ReadPin(nFAULT_GPIO_Port, nFAULT_Pin) == GPIO_PIN_RESET;
#else
    return false;
#endif
}

bool drv8305_init(void)
{
#if HAS_EN_GATE
    HAL_GPIO_WritePin(EN_GATE_GPIO_Port, EN_GATE_Pin, GPIO_PIN_SET);
#endif
    HAL_Delay(10);                               /* charge pump / VREG settle */

    /* Bus sanity: dead bus reads all 0s or all 1s. Default is 0x344. */
    drv.hs_gate_default = drv8305_read(DRV_REG_HS_GATE);
    drv.spi_ok = (drv.hs_gate_default != 0x000u) && (drv.hs_gate_default != 0x7FFu);

    uint16_t g = DRV_CSA_GAIN_BITS & 0x3u;
    uint16_t shunt_val = (uint16_t)(g | (g << 2) | (g << 4));

    drv8305_write(DRV_REG_HS_GATE,   DRV_HS_GATE_VAL);
    drv8305_write(DRV_REG_LS_GATE,   DRV_LS_GATE_VAL);
    drv8305_write(DRV_REG_GATE_CTRL, DRV_GATE_CTRL_VAL);
    drv8305_write(DRV_REG_VDS_SENSE, DRV_VDS_SENSE_VAL);
    drv8305_write(DRV_REG_SHUNT,     shunt_val);

    drv.hs_gate   = drv8305_read(DRV_REG_HS_GATE);
    drv.gate_ctrl = drv8305_read(DRV_REG_GATE_CTRL);
    drv.shunt     = drv8305_read(DRV_REG_SHUNT);
    drv.config_ok = (drv.hs_gate == DRV_HS_GATE_VAL) &&
                    (drv.gate_ctrl == DRV_GATE_CTRL_VAL) &&
                    ((drv.shunt & 0x3Fu) == shunt_val);

    drv8305_clear_faults();
    HAL_Delay(1);
    drv8305_read_status();

    return drv.spi_ok && drv.config_ok;
}



// In radians
float MT_READ(SPI_HandleTypeDef *hspi) {
  uint8_t tx_buf[2] = {0x00, 0x00};
  uint8_t rx_buf[2];
  uint16_t angle_raw;
  float angle_degrees;

  HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(hspi, tx_buf, rx_buf, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(MT_CS_GPIO_Port, MT_CS_Pin, GPIO_PIN_SET);

  if (status != HAL_OK) {
    return -1.0f;
  }

  uint16_t received_16bit_word = ((uint16_t)rx_buf[1] << 8) | rx_buf[0];
  uint16_t data_shifted_for_dummy = received_16bit_word & 0x7FFF;
  angle_raw = (data_shifted_for_dummy >> 1) & 0x3FFF;
  angle_degrees = ((float)angle_raw) / 16384.0f * 2 * M_PI;

  return angle_degrees;
}

uint16_t DRV_Read(SPI_HandleTypeDef *hspi, uint8_t address) {
  uint16_t command_word;
  uint16_t received_word;
  uint16_t data_value;

  command_word = (1U << 15) | ((address & 0x0F) << 11);

  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_TransmitReceive(hspi, (uint8_t *)&command_word,
                              (uint8_t *)&received_word, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_SET);

  if (status != HAL_OK) {
    return 0xFFFF;
  }

  data_value = received_word & 0x07FF;

  return data_value;
}

HAL_StatusTypeDef DRV_Write(SPI_HandleTypeDef *hspi, uint8_t address,
                            uint16_t data) {
  uint16_t command_word;
  uint16_t tx_data;

  data &= 0x07FF;
  command_word = ((address & 0x0F) << 11) | data;
  tx_data = command_word;

  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_RESET);
  HAL_StatusTypeDef status =
      HAL_SPI_Transmit(hspi, (uint8_t *)&tx_data, 1, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(DRV_CS_GPIO_Port, DRV_CS_Pin, GPIO_PIN_SET);

  return status;
}
