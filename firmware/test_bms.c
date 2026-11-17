/* Plain-assert unit tests for the C controller. Run with: make test */
#undef NDEBUG                 /* keep asserts on, even in optimised builds */
#include <assert.h>
#include <stdio.h>
#include "bms.h"

static int checks = 0;
#define CHECK(cond) do { assert(cond); checks++; } while (0)

static uint32_t now = 0;

/* Start fresh: clock at 0, controller at power-on state. */
static void start(void) { now = 0; bms_init(); }

/* Send the same reading n times, 10 ms apart. */
static void feed(int32_t mv, int32_t t, int n)
{
    for (int i = 0; i < n; i++) {
        now += 10;
        bms_on_reading(mv, t, now);
    }
}

static void test_normal_and_warning(void)          /* REQ-01, REQ-02 */
{
    start();
    CHECK(bms_get_state() == BMS_NORMAL && bms_get_contactor_closed());
    feed(3700, 49, 1); CHECK(bms_get_state() == BMS_NORMAL);
    feed(3700, 50, 1); CHECK(bms_get_state() == BMS_WARNING);
    feed(3700, 60, 1); CHECK(bms_get_state() == BMS_WARNING && bms_get_contactor_closed());
    feed(3000, 25, 1); CHECK(bms_get_state() == BMS_NORMAL);
    feed(4200, 25, 1); CHECK(bms_get_state() == BMS_NORMAL);
}

static void test_each_fault(void)                  /* REQ-03, 04, 05, 07 */
{
    struct { int32_t mv, t; uint8_t bit; } cases[] = {
        {3700, 61, BMS_FAULT_OVER_TEMP},
        {2999, 25, BMS_FAULT_UNDER_VOLT},
        {4201, 25, BMS_FAULT_OVER_VOLT},
    };
    for (int i = 0; i < 3; i++) {
        start();
        feed(cases[i].mv, cases[i].t, 3);
        CHECK(bms_get_state() == BMS_FAULT);
        CHECK(!bms_get_contactor_closed());        /* cut in the same step */
        CHECK(bms_get_faults() == cases[i].bit);
    }
}

static void test_debounce(void)                    /* REQ-06 */
{
    start();
    feed(2999, 25, 2);
    CHECK(bms_get_state() != BMS_FAULT && bms_get_debounce_count() == 2);
    feed(3700, 25, 1); CHECK(bms_get_debounce_count() == 0);  /* good resets */
    feed(2999, 25, 2); CHECK(bms_get_state() != BMS_FAULT);
    feed(2999, 25, 1); CHECK(bms_get_state() == BMS_FAULT);
}

static void test_latch_and_reset(void)             /* REQ-08, REQ-09 */
{
    start();
    feed(4201, 25, 3);
    CHECK(!bms_on_reset());                         /* latest reading is bad */
    feed(3700, 55, 1);
    CHECK(!bms_on_reset());                         /* warning is not normal */
    feed(3700, 25, 5);
    CHECK(bms_get_state() == BMS_FAULT);            /* still latched */
    CHECK(bms_on_reset());
    CHECK(bms_get_state() == BMS_NORMAL && bms_get_contactor_closed());
    CHECK(bms_get_faults() == 0);
}

static void test_timeout(void)                     /* REQ-10 */
{
    start();
    bms_on_reading(3700, 25, 1000);
    bms_tick(1499); CHECK(bms_get_state() == BMS_NORMAL);
    bms_tick(1500); CHECK(bms_get_state() == BMS_FAULT);
    CHECK(bms_get_faults() & BMS_FAULT_TIMEOUT && !bms_get_contactor_closed());
    CHECK(!bms_on_reset());                         /* needs a fresh reading */
    bms_on_reading(3700, 25, 1600);
    CHECK(bms_on_reset());
}

static void test_timer_wrap(void)                  /* REQ-10, counter wrap */
{
    start();
    bms_on_reading(3700, 25, UINT32_MAX - 100);     /* just before wrap */
    bms_tick(398); CHECK(bms_get_state() == BMS_NORMAL);  /* 499 ms */
    bms_tick(399); CHECK(bms_get_state() == BMS_FAULT);   /* 500 ms */
}

static void test_bad_frames(void)                  /* REQ-11 */
{
    start();
    feed(2999, 25, 2);
    bms_on_bad_frame();                             /* 3rd bad in a row */
    CHECK(bms_get_state() == BMS_FAULT);
    CHECK(bms_get_faults() == (BMS_FAULT_UNDER_VOLT | BMS_FAULT_BAD_FRAME));
}

int main(void)
{
    test_normal_and_warning();
    test_each_fault();
    test_debounce();
    test_latch_and_reset();
    test_timeout();
    test_timer_wrap();
    test_bad_frames();
    printf("All C tests passed (%d checks)\n", checks);
    return 0;
}
