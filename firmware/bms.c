/* BMS controller logic. Every rule is tagged with its requirement ID. */
#include "bms.h"

/* All controller state lives in this one struct. No malloc anywhere. */
typedef struct {
    bms_state_t state;
    bool     contactor_closed;
    uint8_t  faults;         /* latched fault bits (REQ-08) */
    uint8_t  pending;        /* causes seen in the current bad streak */
    uint8_t  bad_count;      /* bad readings in a row (REQ-06) */
    bool     latest_normal;  /* was the latest reading fully normal? (REQ-09) */
    uint32_t last_valid_ms;  /* time of the last valid sensor frame (REQ-10) */
} bms_t;

static bms_t bms;

/* Enter FAULT and cut power in the same step (REQ-07). */
static void latch(uint8_t bits)
{
    bms.faults |= bits;
    bms.state = BMS_FAULT;
    bms.contactor_closed = false;
}

/* Count one bad reading. Fault only on the 3rd in a row (REQ-06). */
static void count_bad(uint8_t bits)
{
    bms.latest_normal = false;
    if (bms.state == BMS_FAULT) {
        return;                       /* already latched */
    }
    bms.pending |= bits;
    bms.bad_count++;
    if (bms.bad_count >= BMS_DEBOUNCE_COUNT) {
        latch(bms.pending);
    }
}

void bms_init(void)
{
    bms = (bms_t){ .state = BMS_NORMAL, .contactor_closed = true };
}

void bms_on_reading(int32_t voltage_mv, int32_t temp_c, uint32_t now_ms)
{
    uint8_t bits = 0;
    if (temp_c > BMS_T_FAULT_C)      bits |= BMS_FAULT_OVER_TEMP;   /* REQ-03 */
    if (voltage_mv < BMS_V_MIN_MV)   bits |= BMS_FAULT_UNDER_VOLT;  /* REQ-04 */
    if (voltage_mv > BMS_V_MAX_MV)   bits |= BMS_FAULT_OVER_VOLT;   /* REQ-05 */

    bms.last_valid_ms = now_ms;       /* a valid frame arrived (REQ-10) */

    if (bits != 0) {
        count_bad(bits);
        return;
    }

    bms.latest_normal = (temp_c < BMS_T_WARN_C);
    if (bms.state == BMS_FAULT) {
        return;                       /* stays latched (REQ-08) */
    }
    bms.bad_count = 0;                /* good reading resets debounce (REQ-06) */
    bms.pending = 0;
    bms.state = bms.latest_normal ? BMS_NORMAL : BMS_WARNING;  /* REQ-01/02 */
}

void bms_on_bad_frame(void)
{
    count_bad(BMS_FAULT_BAD_FRAME);   /* REQ-11: counts as a bad reading */
}

bool bms_on_reset(void)
{
    if (bms.state != BMS_FAULT || !bms.latest_normal) {
        return false;                 /* REQ-09: ignored */
    }
    uint32_t keep = bms.last_valid_ms;
    bms_init();                       /* clear fault, close contactor */
    bms.last_valid_ms = keep;
    bms.latest_normal = true;
    return true;
}

void bms_tick(uint32_t now_ms)
{
    /* Unsigned subtraction stays correct when the ms counter wraps. */
    if ((uint32_t)(now_ms - bms.last_valid_ms) >= BMS_TIMEOUT_MS) {
        bms.latest_normal = false;    /* old reading is stale now */
        latch(BMS_FAULT_TIMEOUT);     /* REQ-10: no debounce */
    }
}

bms_state_t bms_get_state(void)          { return bms.state; }
bool        bms_get_contactor_closed(void) { return bms.contactor_closed; }
uint8_t     bms_get_faults(void)         { return bms.faults; }
uint8_t     bms_get_debounce_count(void) { return bms.bad_count; }
