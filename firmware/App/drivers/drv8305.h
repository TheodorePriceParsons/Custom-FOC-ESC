#ifndef DRV8305_H
#define DRV8305_H

#include <stdint.h>
#include <stdbool.h>

/* Register addresses */
#define DRV_REG_WARN        0x1   /* warnings & watchdog */
#define DRV_REG_OV_VDS      0x2   /* OV / VDS faults */
#define DRV_REG_IC_FAULT    0x3   /* IC faults */
#define DRV_REG_VGS_FAULT   0x4   /* VGS faults */
#define DRV_REG_HS_GATE     0x5
#define DRV_REG_LS_GATE     0x6
#define DRV_REG_GATE_CTRL   0x7
#define DRV_REG_IC_OP       0x9
#define DRV_REG_SHUNT       0xA
#define DRV_REG_VREG        0xB
#define DRV_REG_VDS_SENSE   0xC

typedef struct {
    uint16_t warn, ov_vds, ic, vgs;   /* status regs 0x1..0x4, all 0 = healthy */
    uint16_t hs_gate_default;         /* read before config, expect 0x344 */
    uint16_t hs_gate, gate_ctrl, shunt;   /* readback after config */
    bool     spi_ok, config_ok;
} drv_status_t;

extern drv_status_t drv;              /* add to Live Expressions */

/* All main-loop only (they take the shared SPI bus). */
uint16_t drv8305_read(uint8_t addr);
void     drv8305_write(uint8_t addr, uint16_t data);
bool     drv8305_init(void);          /* gate drive, 3-PWM, VDS trip, CSA gain, clear faults */
void     drv8305_read_status(void);
void     drv8305_clear_faults(void);
bool     drv8305_nfault_active(void); /* false if HAS_NFAULT = 0 */

#endif
