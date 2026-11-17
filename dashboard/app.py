"""BMS test bench dashboard.  Run:  streamlit run dashboard/app.py

Tab 1 drives the controller live over virtual CAN. Tabs 2-4 run the pytest
suite, show traceability, and let a human review AI test suggestions.
"""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import can
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from bench import can_protocol as cp                       # noqa: E402
from bench.bms_lib import LIB_PATH, STATE_NAMES, Bms, decode_faults  # noqa: E402
from bench.clock import FakeClock                          # noqa: E402
from bench.ecu_node import EcuNode                         # noqa: E402
from ai_suggest import HEADING, safe_path                  # noqa: E402
from trace_report import build_rows, read_requirements     # noqa: E402

REPORTS = ROOT / "reports"
COLORS = {"NORMAL": "#1a7f37", "WARNING": "#bf8700", "FAULT": "#cf222e"}


# =============================================================================
# The bench: bus + ECU + fake clock, kept alive across Streamlit reruns
# =============================================================================
class Bench:
    def __init__(self):
        self.lock = threading.Lock()       # one click at a time
        self.bms = Bms()
        self.session = 0
        self.ecu_bus = self.tester = None
        self.restart()

    def restart(self):
        """Fresh bus, clock and controller (power-on state)."""
        if self.ecu_bus:
            self.ecu_bus.shutdown()
            self.tester.shutdown()
        self.session += 1
        channel = f"dashboard-{self.session}"
        self.ecu_bus = can.Bus(interface="virtual", channel=channel)
        self.tester = can.Bus(interface="virtual", channel=channel)
        self.clock = FakeClock()
        self.ecu = EcuNode(self.ecu_bus, self.clock, self.bms)
        self.counter = 0
        self.status = None
        self.readings: list[dict] = []    # what the tester sent, for the charts
        self.timeline: list[dict] = []    # state after every ECU cycle
        self._cycle()

    # ---- primitive actions ----------------------------------------------
    def _send(self, frame_id, data):
        self.tester.send(can.Message(arbitration_id=frame_id, data=data, is_extended_id=False))

    def _cycle(self):
        """One ECU cycle, then read the newest status frame (like a real rig)."""
        self.ecu.poll()
        while (msg := self.tester.recv(timeout=0)) is not None:
            if msg.arbitration_id == cp.STATUS_ID:
                self.status = cp.unpack_status(bytes(msg.data))
        self.timeline.append({"time_ms": self.clock.now(), "state": STATE_NAMES[self.status.state]})

    def send_reading(self, mv, temp, corrupt=False, replay=False, wait=100):
        self.clock.advance(wait)
        if not replay:
            self.counter = (self.counter + 1) & 0xFF
        self._send(cp.SENSOR_ID, cp.pack_sensor(mv, temp, self.counter, corrupt))
        self._cycle()
        rx = [e for e in self.ecu.log if e["dir"] == "RX" and e["time_ms"] == self.clock.now()]
        self.readings.append({"time_ms": self.clock.now(), "voltage_mv": mv, "temp_c": temp,
                              "dropped": bool(rx and rx[-1]["dropped"])})

    def send_reset(self):
        self.clock.advance(10)
        self._send(cp.RESET_ID, cp.pack_reset())
        self._cycle()

    def advance(self, ms, auto_send, mv, temp):
        if auto_send:
            self.send_reading(mv, temp, wait=ms)
        else:
            self.clock.advance(ms)
            self._cycle()

    # ---- fault injection --------------------------------------------------
    def inject(self, kind, mv, temp):
        if kind == "over_temp":
            for _ in range(3):
                self.send_reading(3700, 75)
        elif kind == "under_volt":
            for _ in range(3):
                self.send_reading(2800, 25)
        elif kind == "over_volt":
            for _ in range(3):
                self.send_reading(4350, 25)
        elif kind == "checksum":
            for _ in range(3):
                self.send_reading(mv, temp, corrupt=True)
        elif kind == "replay":
            if self.counter == 0:
                self.send_reading(mv, temp)          # need one real frame to replay
            self.send_reading(mv, temp, replay=True)
        elif kind == "signal_loss":
            for _ in range(10):                      # silence until timeout
                self.clock.advance(100)
                self._cycle()
                if self.status.state == 2:
                    break

    def scenario(self):
        """normal -> heating -> warning -> fault -> cool down -> reset -> normal"""
        self.restart()
        plan = ([25] * 3 + [30, 38, 45, 52, 57] + [65] * 3 + [55, "reset", 45, 35]
                + [25] * 2 + ["reset"] + [25] * 3)
        for step in plan:
            self.send_reset() if step == "reset" else self.send_reading(3700, step)


@st.cache_resource
def get_bench() -> Bench:
    return Bench()


# =============================================================================
# Small helpers
# =============================================================================
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def badge(text, color, size="2rem"):
    return (f'<div style="background:{color};color:#fff;border-radius:12px;padding:14px;'
            f'text-align:center;font-size:{size};font-weight:700;letter-spacing:1px">{text}</div>')


def color_result(v):
    return {"PASS": "color:#1a7f37;font-weight:600", "PASSED": "color:#1a7f37;font-weight:600",
            "FAIL": "color:#cf222e;font-weight:600", "FAILED": "color:#cf222e;font-weight:600",
            "ERROR": "color:#cf222e;font-weight:600", "NO TESTS": "color:#bc4c00;font-weight:600"
            }.get(v, "")


# =============================================================================
# Tab 1: live control
# =============================================================================
def tab_live(b: Bench):
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.subheader("Sensor input")
        mv = st.slider("Cell voltage (mV)", 2500, 4500, 3700, 10)
        temp = st.slider("Temperature (°C)", -20, 90, 25, 1)
        auto = st.toggle("Auto send every step", value=True,
                         help="When on, 'Advance time' also sends the slider values.")

        c1, c2, c3, c4 = st.columns(4)
        with b.lock:
            if c1.button("Send reading", type="primary", width="stretch"):
                b.send_reading(mv, temp)
            if c2.button("Reset fault", width="stretch"):
                b.send_reset()
            if c3.button("Advance 100 ms", width="stretch"):
                b.advance(100, auto, mv, temp)
            if c4.button("Run full scenario", width="stretch"):
                b.scenario()

            st.markdown("**Fault injection**")
            f = st.columns(3)
            faults = [("Over-temperature", "over_temp"), ("Under-voltage", "under_volt"),
                      ("Over-voltage", "over_volt"), ("Bad checksum", "checksum"),
                      ("Replayed counter", "replay"), ("Signal loss", "signal_loss")]
            for i, (label, kind) in enumerate(faults):
                if f[i % 3].button(label, key=f"inj_{kind}", width="stretch"):
                    b.inject(kind, mv, temp)

    with right:
        s = b.status
        state = STATE_NAMES[s.state]
        st.subheader("Controller status")
        st.markdown(badge(state, COLORS[state], "2.6rem"), unsafe_allow_html=True)
        st.write("")
        m1, m2, m3 = st.columns(3)
        m1.metric("Contactor", "CLOSED" if s.contactor_closed else "OPEN")
        m2.metric("Debounce count", f"{b.bms.debounce_count()} / 3")
        m3.metric("Bench time", f"{b.clock.now()} ms")
        words = decode_faults(s.faults)
        st.markdown(f"**Faults (0x{s.faults:02X}):** " + (", ".join(words) if words else "none"))
        st.caption("Status is read from CAN frame 0x200. Debounce count is read from the "
                   "controller directly (it is not on the bus).")

    st.divider()
    st.plotly_chart(make_charts(b), width="stretch")

    st.subheader("CAN log")
    st.caption("Newest first. Direction is seen from the controller: RX = received, TX = sent.")
    log = pd.DataFrame(list(b.ecu.log)[::-1])
    if not log.empty:
        log["dropped"] = log["dropped"].map(lambda r: f"DROPPED: {r}" if r else "")
        log.columns = ["time (ms)", "dir", "frame ID", "raw bytes", "decoded", "dropped"]
        styled = log.style.apply(
            lambda row: ["background-color:#ffebe9" if row["dropped"] else ""] * len(row), axis=1)
        st.dataframe(styled, hide_index=True, width="stretch", height=320)


def make_charts(b: Bench) -> go.Figure:
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
                        row_heights=[0.4, 0.4, 0.2],
                        subplot_titles=("Temperature (°C)", "Cell voltage (mV)", "State"))
    df = pd.DataFrame(b.readings, columns=["time_ms", "voltage_mv", "temp_c", "dropped"])
    ok, bad = df[~df["dropped"].astype(bool)], df[df["dropped"].astype(bool)]
    fig.add_trace(go.Scatter(x=ok.time_ms, y=ok.temp_c, mode="lines+markers", name="temperature",
                             line=dict(color="#d1242f")), 1, 1)
    fig.add_trace(go.Scatter(x=ok.time_ms, y=ok.voltage_mv, mode="lines+markers", name="voltage",
                             line=dict(color="#0969da")), 2, 1)
    for row, col in ((1, "temp_c"), (2, "voltage_mv")):
        fig.add_trace(go.Scatter(x=bad.time_ms, y=bad[col], mode="markers", name="dropped frame",
                                 marker=dict(symbol="x", size=11, color="#6e7781"),
                                 showlegend=row == 1), row, 1)
    for y, c, t in [(50, "#bf8700", "warning 50"), (60, "#cf222e", "fault > 60")]:
        fig.add_hline(y=y, line_dash="dash", line_color=c, annotation_text=t, row=1, col=1)
    for y, t in [(3000, "min 3000"), (4200, "max 4200")]:
        fig.add_hline(y=y, line_dash="dash", line_color="#cf222e", annotation_text=t, row=2, col=1)
    tl = pd.DataFrame(b.timeline)
    fig.add_trace(go.Scatter(x=tl.time_ms, y=tl.state, mode="markers", showlegend=False,
                             marker=dict(symbol="square", size=10,
                                         color=[COLORS[s] for s in tl.state])), 3, 1)
    fig.update_yaxes(categoryorder="array", categoryarray=["NORMAL", "WARNING", "FAULT"], row=3, col=1)
    fig.update_xaxes(title_text="bench time (ms)", row=3, col=1)
    fig.update_layout(height=640, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.08, x=0))
    return fig


# =============================================================================
# Tab 2: test runner
# =============================================================================
def run_pytest():
    start = time.time()
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                          cwd=ROOT, capture_output=True, text=True)
    subprocess.run([sys.executable, "tools/trace_report.py"], cwd=ROOT, capture_output=True)
    results = load_json(REPORTS / "results.json", None)
    if results:
        s = results["summary"]
        history = load_json(REPORTS / "run_history.json", [])
        history.insert(0, {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                           "total": s["total"], "passed": s.get("passed", 0),
                           "failed": s.get("failed", 0) + s.get("error", 0),
                           "seconds": round(time.time() - start, 2)})
        (REPORTS / "run_history.json").write_text(json.dumps(history[:5], indent=2))
    st.session_state["pytest_output"] = proc.stdout[-4000:]


def tab_tests():
    if st.button("Run all tests", type="primary"):
        with st.spinner("Running pytest..."):
            run_pytest()

    results = load_json(REPORTS / "results.json", None)
    if not results:
        st.info("No test results yet. Click **Run all tests**.")
        return

    s = results["summary"]
    failed = s.get("failed", 0) + s.get("error", 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Total", s["total"])
    c2.metric("Passed", s.get("passed", 0))
    c3.metric("Failed", failed)
    st.caption(f"Last run: {results['generated']}")
    if failed == 0:
        st.success(f"All {s['total']} tests passed.")

    df = pd.DataFrame(results["tests"])
    table = pd.DataFrame({
        "test": df["name"], "file": df["file"],
        "requirements": df["reqs"].apply(", ".join),
        "result": df["outcome"].str.upper(),
        "time (ms)": (df["duration_s"] * 1000).round(1),
    })
    st.dataframe(table.style.map(color_result, subset=["result"]),
                 hide_index=True, width="stretch", height=420)

    for t in results["tests"]:
        if t["outcome"] in ("failed", "error"):
            with st.expander(f"❌ {t['name']}  ({', '.join(t['reqs'])})", expanded=True):
                st.code(t["message"], language="text")

    st.subheader("Run history (last 5)")
    history = load_json(REPORTS / "run_history.json", [])
    if history:
        st.dataframe(pd.DataFrame(history), hide_index=True, width="stretch")
    if "pytest_output" in st.session_state:
        with st.expander("Raw pytest output"):
            st.code(st.session_state["pytest_output"], language="text")


# =============================================================================
# Tab 3: traceability
# =============================================================================
def tab_trace():
    results = load_json(REPORTS / "results.json", None)
    if not results:
        st.info("Run the tests first (Test runner tab).")
        return
    rows, unknown = build_rows(read_requirements(ROOT / "requirements.md"), results)
    covered = sum(r["status"] != "NO TESTS" for r in rows)
    passing = sum(r["status"] == "PASS" for r in rows)

    c1, c2 = st.columns(2)
    c1.metric("Coverage", f"{covered} of {len(rows)} requirements covered")
    c2.metric("Passing", f"{passing} of {len(rows)} requirements passing")
    for r in rows:
        if r["status"] == "NO TESTS":
            st.error(f"⚠️ {r['id']} has no tests: {r['text']}")
    for u in unknown:
        st.warning(f"Tests reference {u}, which is not in requirements.md.")

    table = pd.DataFrame([{
        "requirement": r["id"], "description": r["text"],
        "tests": f"{r['passed']}/{len(r['tests'])} passed",
        "test names": ", ".join(sorted({t["name"].split("[")[0] for t in r["tests"]})) or "-",
        "result": r["status"],
    } for r in rows])
    st.dataframe(table.style.map(color_result, subset=["result"]), hide_index=True,
                 width="stretch", height=470,
                 column_config={"description": st.column_config.TextColumn(width="large"),
                                "test names": st.column_config.TextColumn(width="large")})
    html_report = REPORTS / "traceability.html"
    if html_report.exists():
        st.download_button("Download HTML report", html_report.read_bytes(),
                           file_name="traceability.html", mime="text/html")


# =============================================================================
# Tab 4: AI suggestions (human review)
# =============================================================================
def record_decision(s, generated, model, decision):
    decisions_path = safe_path(REPORTS / "ai_decisions.json")
    decisions = load_json(decisions_path, {})
    today = datetime.now().strftime("%Y-%m-%d")
    decisions[f"{generated}:{s['id']}"] = {"decision": decision, "date": today}
    decisions_path.write_text(json.dumps(decisions, indent=2))
    if decision == "accepted":
        path = safe_path(REPORTS / "reviewed_suggestions.md")
        if not path.exists():
            path.write_text("# Reviewed AI suggestions\n\nAccepted by a human reviewer. These are "
                            "test ideas, not tests: write each test by hand in tests/ and link "
                            "it to its requirement.\n")
        with path.open("a") as fh:
            fh.write(f"\n## {s['title']}\n\n- Accepted: {today}\n- Requirements: "
                     f"{', '.join(s['req_ids'])}\n- Source: AI model `{model}`, generated {generated}\n"
                     f"- Steps: {s['steps']}\n- Expected: {s['expected']}\n- Why: {s['rationale']}\n")


def tab_ai():
    has_key = bool(os.environ.get("GEMINI_API_KEY")) and bool(os.environ.get("GEMINI_MODEL"))
    st.markdown("An AI model proposes missing edge cases. **A human decides.** "
                "Accepted ideas go to `reports/reviewed_suggestions.md`; nothing is written into `tests/`.")
    if not has_key:
        st.info("AI suggestions are off: set `GEMINI_API_KEY` and `GEMINI_MODEL` in your terminal, "
                "then restart `streamlit run dashboard/app.py`. The rest of the bench works without them.")
    if st.button("Generate suggestions", type="primary", disabled=not has_key):
        with st.spinner("Asking the AI model..."):
            proc = subprocess.run([sys.executable, "tools/ai_suggest.py"], cwd=ROOT,
                                  capture_output=True, text=True, env=os.environ.copy())
        (st.success if proc.returncode == 0 else st.error)(proc.stdout.strip() or proc.stderr[-800:])

    data = load_json(REPORTS / "ai_suggestions.json", None)
    if not data:
        return
    st.warning(HEADING)
    st.caption(f"Model: {data['model']} · generated {data['generated']}")
    decisions = load_json(REPORTS / "ai_decisions.json", {})
    for s in data["suggestions"]:
        key = f"{data['generated']}:{s['id']}"
        with st.container(border=True):
            st.markdown(f"**{s['id']}. {s['title']}** · `{', '.join(s['req_ids'])}`")
            if s.get("unknown_reqs"):
                st.error(f"Unknown requirement ID(s): {', '.join(s['unknown_reqs'])}")
            st.markdown(f"**Steps:** {s['steps']}  \n**Expected:** {s['expected']}  \n"
                        f"**Why:** {s['rationale']}")
            if key in decisions:
                d = decisions[key]
                st.caption(f"{'✅ Accepted' if d['decision'] == 'accepted' else '❌ Rejected'} "
                           f"on {d['date']}")
            else:
                a, r, _ = st.columns([1, 1, 4])
                if a.button("Accept", key=f"acc_{key}", width="stretch"):
                    record_decision(s, data["generated"], data["model"], "accepted")
                    st.rerun()
                if r.button("Reject", key=f"rej_{key}", width="stretch"):
                    record_decision(s, data["generated"], data["model"], "rejected")
                    st.rerun()


# =============================================================================
# Page
# =============================================================================
def main():
    st.set_page_config(page_title="BMS Test Bench", page_icon="🔋", layout="wide")
    if not LIB_PATH.exists():
        st.error(f"Controller library not found at {LIB_PATH}. Run `make` first.")
        st.stop()
    REPORTS.mkdir(exist_ok=True)
    b = get_bench()

    with st.sidebar:
        st.title("🔋 BMS Test Bench")
        st.write("A software-in-the-loop bench: a C battery controller runs on a virtual CAN bus.")
        st.write("Drive it live, inject faults, run the tests, and trace every result to a requirement.")
        st.divider()
        if st.button("Restart bench", width="stretch"):
            with b.lock:
                b.restart()
        st.caption("Restart = power-on: clears the controller, clock, charts and CAN log.")

    st.title("Battery management system test bench")
    t1, t2, t3, t4 = st.tabs(["Live control", "Test runner", "Traceability", "AI suggestions"])
    with t1:
        tab_live(b)
    with t2:
        tab_tests()
    with t3:
        tab_trace()
    with t4:
        tab_ai()


main()
