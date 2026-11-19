"""AI test suggestions for HUMAN REVIEW. This script never writes into tests/.

Sends requirements.md and the existing test names to Gemini and asks for
missing edge cases. Writes reports/ai_suggestions.md (and a .json copy that
the dashboard uses for Accept/Reject).

Env:   GEMINI_API_KEY (needed to call the API), GEMINI_MODEL (model name)
Usage: python tools/ai_suggest.py [--dry-run] [--max N]
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"
REPORTS = ROOT / "reports"
HEADING = "AI suggestions: NOT REVIEWED. A human must review before adding any test."

PROMPT = """You are helping a verification engineer test a battery management system controller.
Below are the requirements and the tests that already exist (with the requirement IDs they cover).

Suggest up to {n} MISSING edge-case tests. Rules:
- Link every idea to one or more requirement IDs from the list below.
- Do not repeat something an existing test already covers.
- Write plain-language test ideas (what to send, what to expect). No code.
- If an idea needs behaviour the requirements do not define, say so in the rationale.

REQUIREMENTS:
{requirements}

EXISTING TESTS:
{tests}
"""


def safe_path(path: Path) -> Path:
    """Guard: refuse any output path inside tests/ (responsible-AI rule)."""
    p = path.resolve()
    if p == TESTS_DIR or TESTS_DIR in p.parents:
        raise RuntimeError(f"Refusing to write AI output into tests/: {p}")
    return p


def existing_tests() -> list[str]:
    """Test names with their REQ IDs, from the last run (or from pytest collection)."""
    results = REPORTS / "results.json"
    if results.exists():
        by_name: dict[str, set] = {}
        for t in json.loads(results.read_text())["tests"]:
            by_name.setdefault(t["name"].split("[")[0], set()).update(t["reqs"])
        return [f"{n} ({', '.join(sorted(r))})" for n, r in sorted(by_name.items())]
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return sorted({ln.split("::")[-1].split("[")[0] for ln in out.splitlines() if "::" in ln})


def ask_gemini(prompt: str, model: str, key: str) -> list[dict]:
    """Call Gemini and ask for a JSON list that matches the Suggestion shape."""
    from google import genai               # imported here so CI does not need it
    from google.genai import types
    from pydantic import BaseModel

    class Suggestion(BaseModel):
        title: str
        req_ids: list[str]
        steps: str
        expected: str
        rationale: str

    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[Suggestion], temperature=0.4))
    if resp.parsed is not None:
        return [s.model_dump() for s in resp.parsed]
    return json.loads(resp.text)


def write_outputs(suggestions: list[dict], model: str, known_reqs: set, n_tests: int):
    """Write the review report (.md) and a machine-readable copy (.json)."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for i, s in enumerate(suggestions, 1):
        s["id"] = f"S{i}"
        s["status"] = "not reviewed"
        s["unknown_reqs"] = [r for r in s["req_ids"] if r not in known_reqs]

    md = [f"# {HEADING}", "",
          f"- Model: `{model}`", f"- Generated: {now}",
          f"- Input: requirements.md ({len(known_reqs)} requirements), {n_tests} existing tests",
          "- Every item below is a proposal from an AI model. It may be wrong, duplicate "
          "an existing test, or assume behaviour the requirements do not define.", ""]
    for s in suggestions:
        md += [f"## {s['id']}. {s['title']}", "",
               f"**Requirements:** {', '.join(s['req_ids'])}", ""]
        if s["unknown_reqs"]:
            md += [f"> ⚠️ Unknown requirement ID(s): {', '.join(s['unknown_reqs'])}", ""]
        md += [f"**Steps:** {s['steps']}", "", f"**Expected:** {s['expected']}", "",
               f"**Why:** {s['rationale']}", ""]

    REPORTS.mkdir(exist_ok=True)
    safe_path(REPORTS / "ai_suggestions.md").write_text("\n".join(md))
    safe_path(REPORTS / "ai_suggestions.json").write_text(json.dumps(
        {"heading": HEADING, "model": model, "generated": now, "suggestions": suggestions},
        indent=2))


def main() -> int:
    p = argparse.ArgumentParser(description="AI test suggestions for human review")
    p.add_argument("--dry-run", action="store_true", help="print the prompt, do not call the API")
    p.add_argument("--max", type=int, default=8, help="max number of suggestions")
    args = p.parse_args()

    requirements = (ROOT / "requirements.md").read_text()
    known_reqs = set(re.findall(r"^\|\s*(REQ-\d{2})\s*\|", requirements, re.M))
    tests = existing_tests()
    prompt = PROMPT.format(n=args.max, requirements=requirements, tests="\n".join(tests))

    if args.dry_run:
        print(prompt)
        return 0

    key, model = os.environ.get("GEMINI_API_KEY"), os.environ.get("GEMINI_MODEL")
    if not key or not model:
        missing = " and ".join(v for v, x in (("GEMINI_API_KEY", key), ("GEMINI_MODEL", model)) if not x)
        print(f"AI suggestions skipped: {missing} not set.\n"
              "That is fine: the bench, tests and CI do not need it.\n"
              "To try it:  export GEMINI_API_KEY=<your key>\n"
              "            export GEMINI_MODEL=<a current Gemini model name>")
        return 0

    try:
        suggestions = ask_gemini(prompt, model, key)
    except ImportError:
        print('google-genai is not installed. Run: pip install -e ".[ai]"')
        return 1
    except Exception as e:                 # network, quota, bad model name...
        print(f"AI call failed: {e}")
        return 1

    write_outputs(suggestions, model, known_reqs, len(tests))
    print(f"{HEADING}\nWrote {len(suggestions)} suggestions to reports/ai_suggestions.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
