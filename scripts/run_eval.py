"""
Eval runner — execute all 12 test cases against the ClaimPilot API and
write docs/eval_report.md.

Run from the project root:
    python -m scripts.run_eval
    python -m scripts.run_eval --api-url http://localhost:8000
    python -m scripts.run_eval --format images

TC002 (Unreadable Document) always runs in 'images' format regardless of
--format, because blur_gate only fires on image files; PDF paths skip it by design.

Requires: httpx  (pip install httpx  — already in frontend/requirements.txt)
"""

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT            = Path(__file__).parent.parent
TEST_CASES_PATH = ROOT / "frontend" / "data" / "test_cases.json"
TEST_DOCS_DIR   = ROOT / "frontend" / "data" / "test_docs"
REPORT_PATH     = ROOT / "docs" / "eval_report.md"

DEFAULT_API_URL = "https://claimpilot-api-pg29.onrender.com"
DEFAULT_FORMAT  = "text_pdfs"
TIMEOUT_SECONDS = 120

# ---------------------------------------------------------------------------
# Filename resolution — mirrors frontend/views/test_cases.py exactly
# ---------------------------------------------------------------------------

_TYPE_TO_FILENAME: dict[str, dict[str, str]] = {
    "PRESCRIPTION":      {"images": "prescription.jpg",      "scanned_pdfs": "prescription.pdf",      "text_pdfs": "prescription_text.pdf",      "mixed": "prescription_text.pdf"},
    "HOSPITAL_BILL":     {"images": "hospital_bill.jpg",     "scanned_pdfs": "hospital_bill.pdf",     "text_pdfs": "hospital_bill_text.pdf",     "mixed": "hospital_bill.jpg"},
    "LAB_REPORT":        {"images": "lab_report.jpg",        "scanned_pdfs": "lab_report.pdf",        "text_pdfs": "lab_report_text.pdf",        "mixed": "lab_report_text.pdf"},
    "PHARMACY_BILL":     {"images": "pharmacy_bill.jpg",     "scanned_pdfs": "pharmacy_bill.pdf",     "text_pdfs": "pharmacy_bill_text.pdf",     "mixed": "pharmacy_bill.jpg"},
    "DENTAL_REPORT":     {"images": "dental_report.jpg",     "scanned_pdfs": "dental_report.pdf",     "text_pdfs": "dental_report_text.pdf",     "mixed": "dental_report.jpg"},
    "DISCHARGE_SUMMARY": {"images": "discharge_summary.jpg", "scanned_pdfs": "discharge_summary.pdf", "text_pdfs": "discharge_summary_text.pdf", "mixed": "discharge_summary_text.pdf"},
}


def _resolve_filename(doc: dict, fmt: str) -> str:
    actual_type = doc.get("actual_type", "")
    mapping = _TYPE_TO_FILENAME.get(actual_type, {})
    target = mapping.get(fmt, mapping.get("images", ""))

    explicit = doc.get("file_name")
    if not explicit:
        return target

    # TC001–TC003 have explicit file_names — apply the same suffix swap
    stem = explicit.rsplit(".", 1)[0]
    if target.endswith("_text.pdf"):
        return stem + "_text.pdf"
    if target.endswith(".pdf"):
        return stem + ".pdf"
    return explicit   # images — use original filename unchanged


def build_payload(tc: dict, fmt: str) -> tuple[dict | None, list[str]]:
    inp      = tc["input"]
    tc_id    = tc["case_id"]
    warnings: list[str] = []
    docs: list[dict] = []

    for doc in inp.get("documents", []):
        fname = _resolve_filename(doc, fmt)
        if not fname:
            warnings.append(f"{tc_id}: cannot determine filename for a doc — skipping")
            continue

        file_path = TEST_DOCS_DIR / tc_id / fname
        if not file_path.exists():
            warnings.append(f"{tc_id}: missing file '{fname}' — run frontend/data/generate_test_docs.py")
            continue

        suffix = file_path.suffix.lower()
        mime   = "application/pdf" if suffix == ".pdf" else "image/jpeg"
        docs.append({
            "file_name": fname,
            "file_data": base64.b64encode(file_path.read_bytes()).decode(),
            "mime_type": mime,
        })

    if not docs:
        return None, warnings

    payload: dict = {
        "member_id":      inp["member_id"],
        "policy_id":      inp["policy_id"],
        "claim_category": inp["claim_category"],
        "treatment_date": inp["treatment_date"],
        "claimed_amount": inp["claimed_amount"],
        "documents":      docs,
    }
    for opt in ("hospital_name", "claims_history", "simulate_component_failure", "ytd_claims_amount"):
        if inp.get(opt) is not None:
            payload[opt] = inp[opt]

    return payload, warnings


# ---------------------------------------------------------------------------
# Pass / fail evaluation
# ---------------------------------------------------------------------------

def evaluate(tc: dict, response: dict, status_code: int) -> tuple[bool, str]:
    """Return (passed, reason_string)."""
    expected          = tc.get("expected", {})
    expected_decision = expected.get("decision")
    is_validation_err = "error_type" in response

    if status_code not in (200,):
        return False, f"HTTP {status_code}: {response.get('detail', str(response))[:120]}"

    # TC001, TC002: expected decision is null — system must stop before adjudication
    if expected_decision is None and tc["case_id"] in ("TC001", "TC002"):
        if is_validation_err:
            return True, "System correctly stopped before making a decision"
        actual = response.get("decision", "none")
        return False, f"Expected early stop (validation error); got decision={actual}"

    # TC003: expected null — patient name mismatch; system returns REJECTED + PATIENT_NAME_MISMATCH
    if expected_decision is None and tc["case_id"] == "TC003":
        actual = response.get("decision")
        reasons = response.get("rejection_reasons", [])
        if actual == "REJECTED" and "PATIENT_NAME_MISMATCH" in reasons:
            return True, "REJECTED with PATIENT_NAME_MISMATCH — system correctly declined the claim"
        if is_validation_err:
            return True, "Stopped early — acceptable outcome for patient mismatch"
        return False, f"Expected REJECTED/PATIENT_NAME_MISMATCH or early stop; got decision={actual}, reasons={reasons}"

    actual_decision = response.get("decision")
    if actual_decision != expected_decision:
        return False, f"Expected {expected_decision}, got {actual_decision}"

    # Check approved amount when specified (tolerance ±1 INR for rounding)
    exp_amount = expected.get("approved_amount")
    act_amount = response.get("approved_amount")
    if exp_amount is not None and act_amount is not None:
        if abs(float(act_amount) - float(exp_amount)) > 1:
            return False, (
                f"Decision correct ({actual_decision}) but amount wrong: "
                f"got ₹{float(act_amount):,.0f}, expected ₹{exp_amount:,}"
            )

    return True, f"Decision matches: {actual_decision}"


# ---------------------------------------------------------------------------
# Report formatting helpers
# ---------------------------------------------------------------------------

def _fc(val) -> str:
    """Format INR currency."""
    return f"₹{float(val):,.2f}" if val is not None else "—"


def _fconf(val) -> str:
    """Format confidence score."""
    return f"{float(val):.2f}" if val is not None else "—"


def _trace_highlights(response: dict) -> str:
    trace = response.get("trace", {})
    if not trace:
        return "_No trace available_"

    lines: list[str] = []

    if "blur_gate" in trace:
        bg = trace["blur_gate"]
        lines.append(f"- **blur_gate**: `{bg.get('result', '?')}`")
        for c in bg.get("checks", []):
            v = c.get("variance")
            suffix = f" (variance={v})" if v is not None else f" ({c.get('reason', '')})"
            lines.append(f"  - `{c.get('file', '?')}` → `{c.get('result', '?')}`{suffix}")

    if "extraction" in trace:
        ex = trace["extraction"]
        status = "failed" if ex.get("error") else "ok"
        lines.append(f"- **extraction**: {status}, {ex.get('document_count', 0)} doc(s)")
        for d in ex.get("documents", []):
            conf = d.get("confidence", "?")
            lines.append(f"  - `{d.get('file', '?')}` → `{d.get('classified_type', '?')}` (confidence={conf})")
        if ex.get("patient_name_consistent") is False:
            lines.append("  - ⚠ patient name inconsistency detected")

    if "patient_name_check" in trace:
        pnc = trace["patient_name_check"]
        lines.append(f"- **patient_name_check**: `{pnc.get('result', '?')}` — {pnc.get('details', '')}")

    if "document_validation" in trace:
        dv = trace["document_validation"]
        lines.append(f"- **document_validation**: `{dv.get('result', '?')}`")
        if dv.get("required_types"):
            lines.append(f"  - required: {', '.join(dv['required_types'])}")
        if dv.get("classified_types"):
            lines.append(f"  - classified: {', '.join(dv['classified_types'])}")
        if dv.get("missing_types"):
            lines.append(f"  - missing: {', '.join(dv['missing_types'])}")

    if "adjudicate" in trace:
        adj = trace["adjudicate"]
        if adj.get("skipped"):
            lines.append(f"- **adjudicate**: skipped — {adj.get('reason', '?')}")
        else:
            conf = adj.get("confidence_score", "?")
            lines.append(f"- **adjudicate**: `{adj.get('decision', '?')}` at confidence={conf}")
            if adj.get("gemini_decision"):
                lines.append(f"  - Gemini said `{adj['gemini_decision']}`, overridden → `{adj.get('decision')}`")
            if adj.get("rejection_reasons"):
                lines.append(f"  - rejection reasons: {', '.join(f'`{r}`' for r in adj['rejection_reasons'])}")
            if adj.get("fraud_signals"):
                lines.append(f"  - fraud signals: {', '.join(adj['fraud_signals'])}")
            if adj.get("warnings"):
                lines.append(f"  - warnings: {', '.join(adj['warnings'])}")
            if adj.get("eligibility_date"):
                lines.append(f"  - eligibility date: {adj['eligibility_date']}")
            calc = adj.get("calculation", {})
            if calc and (calc.get("is_network_hospital") or calc.get("copay_percent")):
                parts = []
                if calc.get("is_network_hospital"):
                    parts.append(f"network discount {calc.get('network_discount_percent', 0)}% = {_fc(calc.get('network_discount_amount'))}")
                if calc.get("copay_percent"):
                    parts.append(f"co-pay {calc.get('copay_percent', 0)}% = {_fc(calc.get('copay_amount'))}")
                lines.append(f"  - calculation: {' → '.join(parts)} → final {_fc(calc.get('final_approved'))}")
            dental_approved = adj.get("dental_approved", [])
            dental_rejected = adj.get("dental_rejected", [])
            if dental_approved:
                da_str = ", ".join(d["description"] + " (" + _fc(d["amount"]) + ")" for d in dental_approved)
                lines.append(f"  - dental approved: {da_str}")
            if dental_rejected:
                dr_str = ", ".join(d["description"] + " (" + _fc(d["amount"]) + ")" for d in dental_rejected)
                lines.append(f"  - dental rejected: {dr_str}")

    if "save_to_db" in trace:
        sdb = trace["save_to_db"]
        if sdb.get("success"):
            lines.append(f"- **save_to_db**: ✓ persisted (`{sdb.get('claim_id', '?')}`)")
        else:
            lines.append(f"- **save_to_db**: ✗ failed after {sdb.get('attempts', '?')} attempt(s) — {sdb.get('error', '?')}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------

def build_report(results: list[dict], api_url: str, fmt: str, run_at: str) -> str:
    total  = len(results)
    passed = sum(1 for r in results if r["passed"])
    failed = total - passed

    lines: list[str] = [
        "# Evaluation Report",
        "",
        f"> Generated: {run_at}  ",
        f"> API: `{api_url}`  ",
        f"> Document format: `{fmt}` (TC002 always runs as `images`)  ",
        f"> Result: **{passed}/{total} passed**",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Case | Name | Expected | Actual | Amount | Confidence | Result |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in results:
        exp_decision = r["expected"].get("decision") or "early stop"
        response     = r["response"]
        act_decision = response.get("decision") or response.get("error_type") or "—"
        badge        = "✅ PASS" if r["passed"] else "❌ FAIL"
        lines.append(
            f"| {r['case_id']} | {r['case_name']} "
            f"| `{exp_decision}` | `{act_decision}` "
            f"| {_fc(response.get('approved_amount'))} "
            f"| {_fconf(response.get('confidence_score'))} "
            f"| {badge} |"
        )

    lines += [
        "",
        f"**{passed} passed, {failed} failed** out of {total} test cases.",
        "",
        "---",
        "",
        "## Detailed Results",
        "",
    ]

    for r in results:
        tc       = r["tc"]
        response = r["response"]
        badge    = "✅ PASS" if r["passed"] else "❌ FAIL"
        expected = tc.get("expected", {})

        lines += [
            f"### {r['case_id']} — {r['case_name']}  {badge}",
            "",
            f"**Description:** {tc['description']}",
            "",
            "**Expected:**",
        ]

        if expected.get("decision"):
            lines.append(f"- Decision: `{expected['decision']}`")
        else:
            lines.append("- No decision (system must stop before adjudication)")
        if expected.get("approved_amount"):
            lines.append(f"- Approved amount: ₹{expected['approved_amount']:,}")
        if expected.get("notes"):
            lines.append(f"- Notes: {expected['notes']}")
        if expected.get("system_must"):
            for must in expected["system_must"]:
                lines.append(f"- _{must}_")

        lines += ["", "**Actual output:**"]

        if "error_type" in response:
            lines += [
                f"- Error type: `{response.get('error_type')}`",
                f"- Message: _{response.get('message', '—')}_",
            ]
            if response.get("what_was_uploaded"):
                lines.append(f"- Uploaded: {', '.join(f'`{t}`' for t in response['what_was_uploaded'])}")
            if response.get("what_is_required"):
                lines.append(f"- Required: {', '.join(f'`{t}`' for t in response['what_is_required'])}")
            if response.get("unreadable_file"):
                lines.append(f"- Unreadable file: `{response['unreadable_file']}`")
        else:
            decision = response.get("decision", "—")
            lines += [
                f"- Decision: `{decision}`",
                f"- Approved amount: {_fc(response.get('approved_amount'))}",
                f"- Confidence score: {_fconf(response.get('confidence_score'))}",
                f"- Reason: _{response.get('reason') or '—'}_",
            ]
            if response.get("rejection_reasons"):
                lines.append(f"- Rejection reasons: {', '.join(f'`{r}`' for r in response['rejection_reasons'])}")
            if response.get("failed_components"):
                lines.append(f"- Failed components: {', '.join(f'`{c}`' for c in response['failed_components'])}")
            if response.get("claim_id"):
                lines.append(f"- Claim ID: `{response['claim_id']}`")

        lines += ["", "**Pipeline trace:**", ""]
        lines.append(_trace_highlights(response))
        lines.append("")

        if not r["passed"] and r.get("fail_reason"):
            lines += [
                "**Why it failed:**",
                "",
                f"> {r['fail_reason']}",
                "",
            ]

        elapsed = r.get("elapsed_s", 0)
        lines.append(f"_Response time: {elapsed:.1f}s_")
        lines += ["", "---", ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Run ClaimPilot eval against the API.")
    parser.add_argument(
        "--api-url", default=DEFAULT_API_URL,
        help=f"Base URL of the ClaimPilot API (default: {DEFAULT_API_URL})",
    )
    parser.add_argument(
        "--format", default=DEFAULT_FORMAT,
        choices=["images", "scanned_pdfs", "text_pdfs", "mixed"],
        help="Document format to send (default: text_pdfs). TC002 always uses images.",
    )
    args = parser.parse_args()

    api_url = args.api_url.rstrip("/")
    fmt     = args.format

    if not TEST_CASES_PATH.exists():
        print(f"ERROR: test_cases.json not found at {TEST_CASES_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        test_cases = json.load(f)["test_cases"]

    print(f"\nClaimPilot Eval Runner")
    print(f"  API:    {api_url}")
    print(f"  Format: {fmt}  (TC002 always uses images)")
    print(f"  Cases:  {len(test_cases)}")
    print()

    # Warm up — Render free tier sleeps when idle; first request may take ~30s
    print("Pinging API (may take ~30s if Render instance is cold)...", end=" ", flush=True)
    try:
        ping = httpx.get(f"{api_url}/api/health", timeout=60)
        print(f"OK (HTTP {ping.status_code})")
    except Exception as e:
        print(f"WARN — health check failed: {e}")
        print("Continuing anyway — claims may time out if the service is unavailable.\n")

    print()
    results: list[dict] = []
    passed_count = 0

    for tc in test_cases:
        tc_id   = tc["case_id"]
        tc_name = tc["case_name"]
        tc_fmt  = "images" if tc_id == "TC002" else fmt   # blur test requires images

        print(f"[{tc_id}] {tc_name}  ({tc_fmt})", end=" ... ", flush=True)

        payload, warnings = build_payload(tc, tc_fmt)
        for w in warnings:
            print(f"\n  WARN: {w}", end="")

        if payload is None:
            print("SKIP — no documents loaded")
            results.append({
                "tc": tc, "case_id": tc_id, "case_name": tc_name,
                "expected": tc.get("expected", {}),
                "response": {"error_type": "SCRIPT_ERROR", "message": "No documents loaded"},
                "passed": False, "fail_reason": "No documents loaded — check test_docs/ directory",
                "elapsed_s": 0.0,
            })
            continue

        t0 = time.monotonic()
        try:
            resp    = httpx.post(f"{api_url}/api/claims", json=payload, timeout=TIMEOUT_SECONDS)
            elapsed = time.monotonic() - t0
            status  = resp.status_code
            try:
                response = resp.json()
            except Exception:
                response = {"error_type": "PARSE_ERROR", "message": resp.text[:200]}

        except httpx.TimeoutException:
            elapsed  = time.monotonic() - t0
            status   = 0
            response = {"error_type": "TIMEOUT", "message": f"No response after {TIMEOUT_SECONDS}s"}

        except Exception as e:
            elapsed  = time.monotonic() - t0
            status   = 0
            response = {"error_type": "REQUEST_ERROR", "message": str(e)}

        ok, reason = evaluate(tc, response, status)
        if ok:
            passed_count += 1

        badge      = "PASS" if ok else "FAIL"
        actual_str = response.get("decision") or response.get("error_type") or f"HTTP {status}"
        print(f"{badge}  ({actual_str}, {elapsed:.1f}s)")

        results.append({
            "tc": tc, "case_id": tc_id, "case_name": tc_name,
            "expected": tc.get("expected", {}),
            "response": response,
            "passed": ok, "fail_reason": reason if not ok else "",
            "elapsed_s": elapsed,
        })

    total = len(results)
    print(f"\nResult: {passed_count}/{total} passed\n")

    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report = build_report(results, api_url, fmt, run_at)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Report written: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
