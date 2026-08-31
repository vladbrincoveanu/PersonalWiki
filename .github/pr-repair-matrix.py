import json
import os
import urllib.request


def api_all(path):
    results = []
    url = "https://api.github.com/" + path
    while url:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(request) as response:
            data = json.load(response)
            if isinstance(data, list):
                results.extend(data)
            else:
                results.append(data)
            url = None
            for part in response.headers.get("Link", "").split(","):
                if 'rel="next"' in part:
                    url = part[part.find("<") + 1 : part.find(">")]
                    break
    return results


repo = os.environ["GITHUB_REPOSITORY"]
event = os.environ["GITHUB_EVENT_NAME"]
event_path = os.environ["GITHUB_EVENT_PATH"]
with open(event_path, encoding="utf-8") as handle:
    payload = json.load(handle)

if event in {"schedule", "workflow_dispatch"}:
    prs = api_all(f"repos/{repo}/pulls?state=open&per_page=100")
elif event == "issue_comment" and not payload.get("issue", {}).get("pull_request"):
    prs = []
else:
    number = (
        payload.get("pull_request", {}).get("number")
        or payload.get("issue", {}).get("number")
        or payload.get("comment", {}).get("pull_request", {}).get("number")
        or payload.get("review", {}).get("pull_request", {}).get("number")
    )
    prs = api_all(f"repos/{repo}/pulls/{number}") if number else []

include = []
for pr in prs:
    if pr.get("head", {}).get("repo", {}).get("full_name") != repo:
        continue
    include.append(
        {
            "number": pr["number"],
            "head_ref": pr["head"]["ref"],
            "head_sha": pr["head"]["sha"],
            "base_ref": pr["base"]["ref"],
        }
    )

with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
    output.write("matrix=" + json.dumps({"include": include}, separators=(",", ":")) + "\n")
    output.write("has_prs=" + ("true" if include else "false") + "\n")
