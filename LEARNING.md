# What I learned

## Phase 1: the C controller
- Embedded code avoids `malloc`, so it can never run out of memory at a bad moment. All state lives in one fixed struct.
- Writing the requirements first, with clear boundaries, made the code and the tests easier.
- `-Wall -Wextra -Werror` turns every warning into an error, so small mistakes cannot slip through.
- Unsigned subtraction (`now - last`) keeps the timeout correct even when the millisecond timer wraps around.

## Phase 2: Python bridge and CAN protocol
- A CAN frame is just a few bytes. Both sides must agree on the layout, such as big-endian voltage in bytes 0-1.
- `ctypes` lets Python call C functions directly, but the argument types must be declared exactly.
- A checksum catches corrupted frames. An alive counter catches replayed or stuck frames.
- A fake clock makes time a test input, so tests never need to sleep.

## Phase 3: automated tests
- Tests should talk to the controller only through CAN, the same way a real rig talks to a real ECU.
- Boundary tests (499 vs 500 ms, 60 vs 61°C) catch `>` vs `>=` bugs that a "clearly bad" value would miss.
- `parametrize` turns one test function into many cases from a table.
- Breaking the code on purpose (a mutation check) shows whether the tests really catch bugs.

## Phase 4: traceability
- Traceability answers the question "which tests prove this requirement, and did they pass?"
- A pytest marker plus a hook can record that link automatically for every test.
- The report must fail when a requirement has no test. A warning nobody reads is not enough.

## Phase 5: AI test suggestions
- AI can suggest useful edge cases, but it can also invent requirements or repeat existing tests.
- AI output is labelled NOT REVIEWED, and a human decides what becomes a real test.
- A code guard, not just a promise, stops the script from writing into `tests/`.

## Phase 6: dashboard
- Streamlit re-runs the whole script on every click, so long-lived objects like the bus must be cached.
- Seeing the charts and the CAN log makes debounce, latch and timeout easy to explain to others.
- Running pytest in a separate process keeps the test run apart from the live bench.

## Phase 7: CI and documentation
- CI builds and tests the project on a clean Linux machine on every push, so "works on my laptop" is not enough.
- Uploading the reports as an artifact keeps the evidence for every run.
- An honest "Limits" section shows what the bench does not prove: software-in-the-loop is not hardware-in-the-loop.
