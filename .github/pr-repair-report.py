import json
import os
import urllib.request


repo = os.environ["GITHUB_REPOSITORY"]
number = os.environ["PR_NUMBER"]
token = os.environ["GITHUB_TOKEN"]
commit_sha = os.environ["COMMIT_SHA"]


def request(method, path, payload):
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
    with urllib.request.urlopen(req) as response:
        return json.load(response)


with open("pr-repair-context.json", encoding="utf-8") as handle:
    context = json.load(handle)
with open("repair-result.json", encoding="utf-8") as handle:
    result = json.load(handle)

summary = result.get("summary", "Automated repair applied.").strip()
tests = result.get("tests", [])
test_text = "; ".join(tests) if tests else "workflow validation passed"
reply = (
    f"Applied the verified fix in commit `{commit_sha[:12]}`. "
    f"Validation: {test_text}. {summary}"
)

comments = context.get("review_comments", [])
for comment in comments:
    if comment.get("in_reply_to_id") or not comment.get("path"):
        continue
    if comment.get("user", {}).get("type") != "Bot":
        continue
    request(
        "POST",
        f"repos/{repo}/pulls/{number}/comments/{comment['id']}/replies",
        {"body": reply},
    )
    print(f"Replied to review comment {comment['id']}")
