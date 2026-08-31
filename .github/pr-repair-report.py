import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from pr_repair_utils import validate_model_decision


def api_all(path: str, token: str) -> list:
    results = []
    url = "https://api.github.com/" + path
    while url:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as response:
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


def fetch_review_comments(repo: str, number: str, token: str) -> list:
    return api_all(f"repos/{repo}/pulls/{number}/comments?per_page=100", token)


def request(method: str, path: str, token: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/" + path,
        data=body,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def select_reply_comment_ids(comments: list[dict], result: dict) -> list[int]:
    """Return only verified, top-level bot comments without an existing reply."""
    fixed_ids = set(result.get("fixed_comment_ids", []))
    replied_to = {
        comment.get("in_reply_to_id")
        for comment in comments
        if isinstance(comment.get("in_reply_to_id"), int)
    }
    selected = []
    for comment in comments:
        comment_id = comment.get("id")
        if not isinstance(comment_id, int) or isinstance(comment_id, bool):
            continue
        if comment_id not in fixed_ids or comment_id in replied_to:
            continue
        if comment.get("in_reply_to_id") or not comment.get("path"):
            continue
        if (comment.get("user") or {}).get("type") != "Bot":
            continue
        selected.append(comment_id)
    return selected


def main() -> None:
    repo = os.environ["GITHUB_REPOSITORY"]
    number = os.environ["PR_NUMBER"]
    token = os.environ["GITHUB_TOKEN"]
    commit_sha = os.environ["COMMIT_SHA"]
    artifact_dir = Path(os.environ["REPAIR_ARTIFACT_DIR"])

    context = json.loads(
        (artifact_dir / "pr-repair-context.json").read_text(encoding="utf-8")
    )
    result = validate_model_decision(
        json.loads((artifact_dir / "repair-result.json").read_text(encoding="utf-8"))
    )
    try:
        comments = fetch_review_comments(repo, number, token)
    except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"Could not refresh review comments: {type(exc).__name__}")
        return
    reply_ids = select_reply_comment_ids(comments, result)
    test_text = "; ".join(result["tests"]) if result["tests"] else "workflow validation passed"
    reply = (
        f"Applied the verified fix in commit `{commit_sha[:12]}`. "
        f"Validation: {test_text}. {result['summary']}"
    )

    for comment_id in reply_ids:
        try:
            request(
                "POST",
                f"repos/{repo}/pulls/{number}/comments/{comment_id}/replies",
                token,
                {"body": reply},
            )
            print(f"Replied to review comment {comment_id}")
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            print(f"Could not reply to review comment {comment_id}: {type(exc).__name__}")


if __name__ == "__main__":
    main()
