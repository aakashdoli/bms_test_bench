# BMS Safety Requirements

| ID | Requirement |
|---|---|
| REQ-01 | State is NORMAL when cell voltage is 3000 to 4200 mV and temperature is below 50°C. Contactor is closed. |
| REQ-02 | State is WARNING when temperature is 50 to 60°C. Contactor stays closed. |
| REQ-03 | Over-temperature fault when temperature is above 60°C. |
| REQ-04 | Under-voltage fault when voltage is below 3000 mV. |
| REQ-05 | Over-voltage fault when voltage is above 4200 mV. |
| REQ-06 | A fault only triggers after 3 bad readings in a row (debounce). A good reading resets the count. |
| REQ-07 | On any fault, open the contactor (cut power) in the same step. |
| REQ-08 | A fault stays latched until a reset command is received. |
| REQ-09 | Reset only works when the latest reading is normal. Otherwise it is ignored. |
| REQ-10 | Signal timeout: if no valid sensor frame arrives for 500 ms, go to fault. |
| REQ-11 | Frames with a wrong checksum are dropped and counted as bad readings. |
| REQ-12 | Frames with a repeated alive counter (replay or stuck sender) are dropped. |

## Clarifications

Decisions made where the table leaves room for interpretation:

- Boundaries: 3000 and 4200 mV are normal. 50 and 60°C are WARNING. 61°C is bad.
- Before the 3rd bad reading, the state does not change (it keeps its last value).
- The fault bitmask holds every cause seen during the bad streak that caused the fault.
- A WARNING reading is not "normal" for REQ-09, so a reset is ignored at 50 to 60°C.
- Timeout (REQ-10) is not debounced: it faults as soon as 500 ms have passed.
- After a timeout, a fresh valid reading is needed before a reset is accepted.
- The 500 ms timer starts at power-on (time 0), so a missing first frame also times out.
- Dropped replay frames (REQ-12) do not count as bad readings and do not refresh the timer.
