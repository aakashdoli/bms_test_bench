"""Build the traceability report: requirements.md + reports/results.json.

Writes reports/traceability.md and reports/traceability.html.
Exit code 1 if any requirement has no test, so CI catches the gap.

Usage: python tools/trace_report.py [--requirements FILE] [--results FILE] [--out DIR]
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQ_ROW = re.compile(r"^\|\s*(REQ-\d{2})\s*\|\s*(.+?)\s*\|\s*$")


def read_requirements(path: Path) -> dict[str, str]:
    """Return {ID: description} from the markdown table in requirements.md."""
    reqs = {}
    for line in path.read_text().splitlines():
        if m := REQ_ROW.match(line):
            reqs[m.group(1)] = m.group(2)
    return reqs


def build_rows(reqs: dict[str, str], results: dict) -> tuple[list[dict], list[str]]:
    """One row per requirement, plus a list of IDs used by tests but not in requirements.md."""
    rows = []
    for rid, text in reqs.items():
        tests = [t for t in results["tests"] if rid in t["reqs"]]
        outcomes = {t["outcome"] for t in tests}
        if not tests:
            status = "NO TESTS"
        elif outcomes & {"failed", "error"}:
            status = "FAIL"
        elif outcomes == {"passed"}:
            status = "PASS"
        else:
            status = "NOT RUN"          # some tests skipped or deselected
        rows.append({"id": rid, "text": text, "status": status, "tests": tests,
                     "passed": sum(t["outcome"] == "passed" for t in tests)})
    unknown = sorted({r for t in results["tests"] for r in t["reqs"]} - reqs.keys())
    return rows, unknown


def write_markdown(rows, unknown, results, path: Path):
    covered = sum(r["status"] != "NO TESTS" for r in rows)
    out = ["# Traceability report", "",
           f"Generated from test run at {results['generated']}.", "",
           f"**{covered} of {len(rows)} requirements covered.** "
           f"Tests: {results['summary'].get('passed', 0)} passed of {results['summary']['total']}.", ""]
    for r in rows:
        if r["status"] == "NO TESTS":
            out.append(f"> ⚠️ **WARNING: {r['id']} has no tests.**")
    for rid in unknown:
        out.append(f"> ⚠️ Tests reference {rid}, which is not in requirements.md.")
    out += ["", "| Requirement | Description | Tests | Result |", "|---|---|---|---|"]
    icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "NO TESTS": "⚠️ NO TESTS", "NOT RUN": "⏸ NOT RUN"}
    for r in rows:
        names = "<br>".join(f"`{t['name']}`" for t in r["tests"]) or "-"
        out.append(f"| {r['id']} | {r['text']} | {r['passed']}/{len(r['tests'])} passed<br>"
                   f"{names} | {icon[r['status']]} |")
    path.write_text("\n".join(out) + "\n")


def write_html(rows, unknown, results, path: Path):
    covered = sum(r["status"] != "NO TESTS" for r in rows)
    e = html.escape
    warnings = "".join(f'<p class="warn">WARNING: {e(r["id"])} has no tests.</p>'
                       for r in rows if r["status"] == "NO TESTS")
    warnings += "".join(f'<p class="warn">Tests reference {e(u)}, which is not in '
                        f'requirements.md.</p>' for u in unknown)
    body = ""
    for r in rows:
        tests = "".join(f'<li class="{e(t["outcome"])}">{e(t["name"])}</li>' for t in r["tests"])
        body += (f'<tr><td><b>{e(r["id"])}</b></td><td>{e(r["text"])}</td>'
                 f'<td>{r["passed"]}/{len(r["tests"])} passed<ul>{tests}</ul></td>'
                 f'<td><span class="badge {r["status"].replace(" ", "-")}">{r["status"]}</span></td></tr>')
    path.write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Traceability report</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 1100px; padding: 0 16px; color: #1f2328; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border-bottom: 1px solid #d0d7de; padding: 8px; text-align: left; vertical-align: top; }}
 ul {{ margin: 4px 0 0; padding-left: 18px; font-size: 0.85em; font-family: ui-monospace, monospace; }}
 li.failed, li.error {{ color: #cf222e; }}
 .badge {{ padding: 2px 8px; border-radius: 10px; font-weight: 600; color: #fff; white-space: nowrap; }}
 .PASS {{ background: #1a7f37; }} .FAIL {{ background: #cf222e; }}
 .NO-TESTS {{ background: #bc4c00; }} .NOT-RUN {{ background: #6e7781; }}
 .warn {{ background: #ffebe9; border-left: 4px solid #cf222e; padding: 8px 12px; }}
</style></head><body>
<h1>Traceability report</h1>
<p>Generated from test run at {e(results['generated'])}.</p>
<p><b>{covered} of {len(rows)} requirements covered.</b>
 Tests: {results['summary'].get('passed', 0)} passed of {results['summary']['total']}.</p>
{warnings}
<table><tr><th>Requirement</th><th>Description</th><th>Tests</th><th>Result</th></tr>{body}</table>
</body></html>
""")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--requirements", type=Path, default=ROOT / "requirements.md")
    p.add_argument("--results", type=Path, default=ROOT / "reports" / "results.json")
    p.add_argument("--out", type=Path, default=ROOT / "reports")
    args = p.parse_args()

    if not args.results.exists():
        print(f"No results at {args.results}. Run `pytest` first.")
        return 1
    reqs = read_requirements(args.requirements)
    results = json.loads(args.results.read_text())
    rows, unknown = build_rows(reqs, results)

    args.out.mkdir(parents=True, exist_ok=True)
    write_markdown(rows, unknown, results, args.out / "traceability.md")
    write_html(rows, unknown, results, args.out / "traceability.html")

    for r in rows:
        print(f"  {r['id']}  {r['status']:<8}  {r['passed']}/{len(r['tests'])} tests passed")
    missing = [r["id"] for r in rows if r["status"] == "NO TESTS"]
    covered = len(rows) - len(missing)
    print(f"\n{covered} of {len(rows)} requirements covered. Report: {args.out / 'traceability.html'}")
    if missing:
        print(f"ERROR: no tests for {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
