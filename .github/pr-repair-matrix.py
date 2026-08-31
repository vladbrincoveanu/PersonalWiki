import json
import os
import urllib.request


def api(path):
    request = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


repo = os.environ["GITHUB_REPOSITORY"]
event = os.environ["GITHUB_EVENT_NAME"]
event_path = os.environ["GITHUB_EVENT_PATH"]
with open(event_path, encoding="utf-8") as handle:
    payload = json.load(handle)

if event in {"schedule", "workflow_dispatch"}:
    prs = api(f"repos/{repo}/pulls?state=open&per_page=100")
else:
    number = payload.get("pull_request", {}).get("number") or payload.get("issue", {}).get("number")
    prs = [api(f"repos/{repo}/pulls/{number}")] if number else []

include = []
for pr in prs:
    if pr.get("head", {}).get("repo", {}).get("full_name") != repo:
        continue
    include.append(
        {
            "number": pr["number"],
            "head_ref": pr["head"]["ref"],
            "head_sha": pr["head"]["sha"],
        }
    )

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
    output.write("matrix=" + json.dumps({"include": include}, separators=(",", ":")) + "\n")
