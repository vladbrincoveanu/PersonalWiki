import json
import os
import subprocess
import tempfile
import urllib.request


def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


with open("pr-repair-context.json", encoding="utf-8") as handle:
    context = json.load(handle)
with open("pr-repair-prompt.md", encoding="utf-8") as handle:
    instructions = handle.read()

diff = command("git", "diff", "--no-ext-diff", "origin/main...HEAD")
if len(diff) > 120_000:
    diff = diff[:120_000] + "\n[diff truncated]\n"

request_body = {
    "model": os.environ.get("DEEPINFRA_MODEL", "deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731"),
    "temperature": 0.1,
    "response_format": {"type": "json_object"},
    "messages": [
        {
            "role": "system",
            "content": (
                "You are a careful software repair agent. Return JSON only with exactly these keys: "
                "action (one of patch, no_change, blocked), patch (a unified git diff string), "
                "summary (string), and tests (array of strings). Never return shell commands."
            ),
        },
        {
            "role": "user",
            "content": (
                instructions
                + "\n\nCurrent PR state:\n"
                + json.dumps(context, indent=2)
                + "\n\nCurrent PR diff:\n```diff\n"
                + diff
                + "\n```\n"
                + "Return a minimal patch only for verified actionable findings. "
                + "If no safe fix is possible, return action=blocked or action=no_change and an empty patch."
            ),
        },
    ],
}

request = urllib.request.Request(
    os.environ.get("DEEPINFRA_ENDPOINT", "https://api.deepinfra.com/v1/openai/chat/completions"),
    data=json.dumps(request_body).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {os.environ['DEEPINFRA_TOKEN']}",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=300) as response:
    result = json.load(response)

content = result["choices"][0]["message"]["content"].strip()
if content.startswith("```"):
    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
decision = json.loads(content)

with open("repair-result.json", "w", encoding="utf-8") as handle:
    json.dump(decision, handle, indent=2)

with open("repair-result.md", "w", encoding="utf-8") as handle:
    handle.write(decision.get("summary", "No summary returned.") + "\n")

if decision.get("action") != "patch" or not decision.get("patch", "").strip():
    raise SystemExit(0)

patch_text = decision["patch"]
for line in patch_text.splitlines():
    if not line.startswith("+++ b/"):
        continue
    path = line[6:]
    if (
        path.startswith("/")
        or path.startswith(".github/workflows/")
        or path.startswith(".github/pr-repair-")
        or path in {".env", ".env.local", ".gitconfig"}
        or ".." in path.split("/")
    ):
        print(f"Refusing model patch for protected path: {path}")
        raise SystemExit(0)
with tempfile.NamedTemporaryFile("w", suffix=".patch", encoding="utf-8") as handle:
    handle.write(patch_text)
    handle.flush()
    subprocess.run(["git", "apply", "--check", handle.name], check=True)
    subprocess.run(["git", "apply", handle.name], check=True)
