/* BMS controller: public interface. No heap, one static state struct. */
#ifndef BMS_H
#define BMS_H

#include <stdbool.h>
#include <stdint.h>

/* Limits taken from requirements.md */
#define BMS_V_MIN_MV        3000  /* REQ-04 */
#define BMS_V_MAX_MV        4200  /* REQ-05 */
#define BMS_T_WARN_C        50    /* REQ-02 */
#define BMS_T_FAULT_C       60    /* REQ-03 */
#define BMS_DEBOUNCE_COUNT  3     /* REQ-06 */
#define BMS_TIMEOUT_MS      500u  /* REQ-10 */

typedef enum {
    BMS_NORMAL  = 0,
    BMS_WARNING = 1,
    BMS_FAULT   = 2
} bms_state_t;

/* Fault bitmask bits */
#define BMS_FAULT_OVER_TEMP   (1u << 0)
#define BMS_FAULT_UNDER_VOLT  (1u << 1)
#define BMS_FAULT_OVER_VOLT   (1u << 2)
#define BMS_FAULT_TIMEOUT     (1u << 3)
#define BMS_FAULT_BAD_FRAME   (1u << 4)

void bms_init(void);                       /* power-on: NORMAL, contactor closed */
void bms_on_reading(int32_t voltage_mv, int32_t temp_c, uint32_t now_ms);
void bms_on_bad_frame(void);               /* REQ-11: a frame with a bad checksum */
bool bms_on_reset(void);                   /* true if the reset was accepted */
void bms_tick(uint32_t now_ms);            /* call often: checks the timeout */

bms_state_t bms_get_state(void);
bool        bms_get_contactor_closed(void);
uint8_t     bms_get_faults(void);
uint8_t     bms_get_debounce_count(void);

#endif
