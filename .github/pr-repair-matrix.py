import json
import os
import urllib.request
from pathlib import Path

from pr_repair_utils import validate_ref, validate_sha


_CONTROLLER_REF = "codex/pr-repair-agent"
_MAX_MATRIX_ENTRIES = 256


def api_all(path: str, token: str) -> list:
    results = []
    url = "https://api.github.com/" + path
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
            if isinstance(data, list):
                results.extend(data)
            elif data:
                results.append(data)
            url = None
            for part in response.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part[part.find("<") + 1 : part.find(">")]
                    break
    return results


def _event_pr_number(payload: dict) -> int | None:
    candidates = (
        payload.get("pull_request", {}).get("number"),
        payload.get("issue", {}).get("number"),
        payload.get("review", {}).get("pull_request", {}).get("number"),
        payload.get("comment", {}).get("pull_request", {}).get("number"),
    )
    return next((number for number in candidates if isinstance(number, int) and number > 0), None)


def build_matrix_entries(prs: list[dict], repo: str, default_branch: str) -> list[dict]:
    default_branch = validate_ref(default_branch, "default branch")
    entries = []
    for pr in prs:
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_repo = (head.get("repo") or {}).get("full_name")
        if (
            pr.get("state", "open") != "open"
            or head_repo != repo
            or head.get("ref") in {_CONTROLLER_REF, default_branch}
        ):
            continue
        entries.append(
            {
                "number": pr["number"],
                "head_ref": validate_ref(head["ref"], "head ref"),
                "head_sha": validate_sha(head["sha"], "head SHA"),
                "base_ref": validate_ref(base["ref"], "base ref"),
                "base_sha": validate_sha(base["sha"], "base SHA"),
            }
        )
    if len(entries) > _MAX_MATRIX_ENTRIES:
        raise RuntimeError(f"too many open PRs for one matrix: {len(entries)}")
    return entries


def write_matrix(entries: list[dict], output_path: Path) -> None:
    with output_path.open("a", encoding="utf-8") as output:
        output.write("matrix=" + json.dumps({"include": entries}, separators=(",", ":")) + "\n")
        output.write("has_prs=" + ("true" if entries else "false") + "\n")


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    event = os.environ["GITHUB_EVENT_NAME"]
    event_path = os.environ["GITHUB_EVENT_PATH"]
    token = os.environ["GITHUB_TOKEN"]
    default_branch = os.environ["DEFAULT_BRANCH"]
    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))

    if event in {"schedule", "workflow_dispatch"}:
        prs = api_all(f"repos/{repo}/pulls?state=open&per_page=100", token)
    elif event == "issue_comment" and not payload.get("issue", {}).get("pull_request"):
        prs = []
    else:
        number = _event_pr_number(payload)
        prs = api_all(f"repos/{repo}/pulls/{number}", token) if number else []

    entries = build_matrix_entries(prs, repo, default_branch)
    write_matrix(entries, Path(os.environ["GITHUB_OUTPUT"]))


if __name__ == "__main__":
    main()
