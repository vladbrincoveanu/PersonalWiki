import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "check_pr_agent_review.py"


def run_gate(payload=None):
    env = os.environ.copy()
    if payload is None:
        env.pop("PR_AGENT_REVIEW_JSON", None)
    else:
        env["PR_AGENT_REVIEW_JSON"] = json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(GATE)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_passes_review_without_key_issues_or_security_concerns():
    result = run_gate({
        "estimated_effort_to_review_[1-5]": 4,
        "relevant_tests": "yes",
        "key_issues_to_review": [],
        "security_concerns": "No",
    })

    assert result.returncode == 0
    assert "no blocking findings" in result.stdout.lower()


def test_gate_accepts_explicit_no_security_concern_prose():
    result = run_gate({
        "key_issues_to_review": [],
        "security_concerns": "No security concerns identified.",
    })

    assert result.returncode == 0


def test_gate_fails_review_with_key_issue():
    result = run_gate({
        "key_issues_to_review": [{
            "issue_header": "[high] Possible Bug",
            "issue_content": "A concurrent claim can send twice.",
            "relevant_file": "delivery.py",
            "start_line": 10,
            "end_line": 12,
        }],
        "security_concerns": "No",
    })

    assert result.returncode == 1
    assert "[high] Possible Bug" in result.stdout
    assert "delivery.py" in result.stdout


def test_gate_allows_low_severity_key_issue_with_warning():
    result = run_gate({
        "key_issues_to_review": [{
            "issue_header": "[low] Defensive cleanup",
            "issue_content": "A fallback could be clearer.",
            "relevant_file": "delivery.py",
            "start_line": 10,
            "end_line": 12,
        }],
        "security_concerns": "No",
    })

    assert result.returncode == 0
    assert "::warning" in result.stdout


def test_gate_escapes_percent_encoded_workflow_commands():
    result = run_gate({
        "key_issues_to_review": [{
            "issue_header": "[low] Model output",
            "issue_content": "Literal %0A::error should stay text.",
            "relevant_file": "delivery.py",
        }],
        "security_concerns": "No",
    })

    assert result.returncode == 0
    assert "%250A::error" in result.stdout


def test_gate_warns_when_key_issue_has_no_severity():
    result = run_gate({
        "key_issues_to_review": [{
            "issue_header": "Possible Bug",
            "issue_content": "Severity was omitted.",
            "relevant_file": "delivery.py",
        }],
        "security_concerns": "No",
    })

    assert result.returncode == 0
    assert "severity" in result.stdout.lower()


def test_gate_fails_review_with_security_concern():
    result = run_gate({
        "key_issues_to_review": [],
        "security_concerns": "Authentication bypass: unsigned requests are accepted.",
    })

    assert result.returncode == 1
    assert "Authentication bypass" in result.stdout


def test_gate_fails_closed_when_review_output_is_missing():
    result = run_gate()

    assert result.returncode == 1
    assert "missing" in result.stdout.lower()


def test_gate_fails_closed_when_review_output_is_invalid_json():
    env = os.environ.copy()
    env["PR_AGENT_REVIEW_JSON"] = "not-json"
    result = subprocess.run(
        [sys.executable, str(GATE)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "invalid" in result.stdout.lower()
