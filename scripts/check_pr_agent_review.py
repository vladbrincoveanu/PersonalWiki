#!/usr/bin/env python3
"""Fail CI when PR-Agent reports blocking review findings."""

import json
import os
import re
import sys
from typing import Any


NO_SECURITY_CONCERNS = frozenset({
    "no",
    "none",
    "no security concern",
    "no security concerns",
    "no security concern identified",
    "no security concerns identified",
    "no clear security vulnerability is introduced",
    "no clear security vulnerability introduced",
})


def _workflow_message(message: str) -> str:
    """Encode untrusted model text before emitting a workflow command."""
    return " ".join(str(message).splitlines()).strip().replace("%", "%25")


def _error(message: str) -> None:
    print(f"::error title=PR-Agent quality gate::{_workflow_message(message)}")


def _warning(message: str) -> None:
    print(f"::warning title=PR-Agent review finding::{_workflow_message(message)}")


def _load_review() -> dict[str, Any] | None:
    raw = os.environ.get("PR_AGENT_REVIEW_JSON", "").strip()
    if not raw:
        _error("PR-Agent review output is missing; failing closed.")
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        _error(f"PR-Agent review output is invalid JSON: {exc.msg}.")
        return None
    if not isinstance(payload, dict):
        _error("PR-Agent review output must be a JSON object.")
        return None

    # github_action_output currently exposes the inner `review` object. Accept
    # the documented outer shape too so an upstream wrapper change fails safely.
    review = payload.get("review", payload)
    if not isinstance(review, dict):
        _error("PR-Agent review payload does not contain a review object.")
        return None
    return review


def _has_no_security_concerns(value: str) -> bool:
    normalized = " ".join(value.strip().lower().split())
    normalized = normalized.rstrip(".!?").strip()
    return normalized in NO_SECURITY_CONCERNS


def main() -> int:
    review = _load_review()
    if review is None:
        return 1

    issues = review.get("key_issues_to_review")
    if not isinstance(issues, list):
        _error("PR-Agent key_issues_to_review is missing or malformed.")
        return 1

    blocking = False
    for issue in issues:
        if isinstance(issue, dict):
            header = str(issue.get("issue_header") or "Key issue")
            path = str(issue.get("relevant_file") or "unknown file")
            content = str(issue.get("issue_content") or "No details supplied")
            match = re.match(r"^\[(critical|high|medium|low)\]\s+", header, re.I)
            if not match:
                blocking = True
                _error(f"Finding in {path} has no valid severity prefix: {header}")
                continue
            message = f"{header} in {path}: {content}"
            if match.group(1).lower() in {"critical", "high"}:
                blocking = True
                _error(message)
            else:
                _warning(message)
        else:
            blocking = True
            _error(f"PR-Agent reported a malformed key issue: {issue!r}")

    security = review.get("security_concerns")
    if not isinstance(security, str):
        _error("PR-Agent security_concerns is missing or malformed.")
        return 1
    if not _has_no_security_concerns(security):
        blocking = True
        _error(f"Security concern: {security}")

    if blocking:
        print("PR-Agent reported blocking findings; review and resolve them before merge.")
        return 1

    print("PR-Agent completed with no blocking findings.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
