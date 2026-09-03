import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from pr_repair_utils import validate_model_decision, validate_patch_paths, validate_sha


DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
_MAX_DIFF_CHARS = 120_000


def _command(workspace: Path, *args: str, binary: bool = False):
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        check=True,
        capture_output=True,
        text=not binary,
    ).stdout


def _git_paths(workspace: Path, *args: str) -> set[str]:
    output = _command(workspace, *args, binary=True)
    return {path.decode("utf-8") for path in output.split(b"\0") if path}


def _working_tree_paths(workspace: Path) -> set[str]:
    return (
        _git_paths(workspace, "diff", "--name-only", "-z")
        | _git_paths(workspace, "diff", "--cached", "--name-only", "-z")
        | _git_paths(workspace, "ls-files", "--others", "--exclude-standard", "-z")
    )


def apply_repair_patch(workspace: Path, patch_text: str) -> set[str]:
    """Apply and stage only paths declared by a validated model patch."""
    workspace = workspace.resolve()
    expected_paths = validate_patch_paths(patch_text)
    if _working_tree_paths(workspace):
        raise RuntimeError("target worktree must be clean before applying a repair")

    with tempfile.NamedTemporaryFile("w", suffix=".patch", encoding="utf-8") as handle:
        handle.write(patch_text)
        handle.flush()
        check_command = [
            "git", "-C", str(workspace), "apply", "--check", "--recount", handle.name
        ]
        apply_command = ["git", "-C", str(workspace), "apply", "--recount", handle.name]
        subprocess.run(check_command, check=True, capture_output=True, text=True)
        subprocess.run(apply_command, check=True, capture_output=True, text=True)

    actual_paths = _working_tree_paths(workspace)
    if actual_paths != expected_paths:
        raise RuntimeError(
            f"repair changed unexpected paths: expected {sorted(expected_paths)}, "
            f"got {sorted(actual_paths)}"
        )

    subprocess.run(
        ["git", "-C", str(workspace), "add", "--", *sorted(expected_paths)],
        check=True,
        capture_output=True,
        text=True,
    )
    staged_paths = _git_paths(workspace, "diff", "--cached", "--name-only", "-z")
    if staged_paths != expected_paths:
        raise RuntimeError(
            f"staging changed unexpected paths: expected {sorted(expected_paths)}, "
            f"got {sorted(staged_paths)}"
        )
    return expected_paths


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_result(artifact_dir: Path, result: dict) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "repair-result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    (artifact_dir / "repair-result.md").write_text(
        result.get("summary", "No summary returned.") + "\n", encoding="utf-8"
    )


def build_request_body(instructions: str, context: dict, diff: str, model: str | None = None) -> dict:
    return {
        "model": model or DEFAULT_MODEL,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a careful software repair agent. Return JSON only with exactly these keys: "
                    "action (one of patch, no_change, blocked), patch (a unified git diff string), "
                    "summary (string), tests (array of strings), and fixed_comment_ids (array of integers). "
                    "Never return shell commands."
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


def _model_request(request_body: dict) -> dict:
    request = urllib.request.Request(
        os.environ.get("OPENROUTER_ENDPOINT", DEFAULT_ENDPOINT),
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/vladbrincoveanu/PersonalWiki",
            "X-OpenRouter-Title": "PR Repair Agent",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"OpenRouter request failed ({error.code}): {detail}") from error


def _strip_json_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return content


def _safe_artifact_dir(workspace: Path) -> Path:
    artifact_dir = Path(os.environ["REPAIR_ARTIFACT_DIR"]).resolve()
    if artifact_dir == workspace or workspace in artifact_dir.parents:
        raise ValueError("repair artifacts must be outside the target worktree")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def validate_context_heads(context: dict, expected_head_sha: str, expected_base_sha: str) -> None:
    pull_request = context.get("pull_request") or {}
    context_head_sha = validate_sha(pull_request.get("head_sha"), "context head SHA")
    context_base_sha = validate_sha(pull_request.get("base_sha"), "context base SHA")
    if context_head_sha != expected_head_sha:
        raise ValueError("context head SHA does not match the selected PR commit")
    if context_base_sha != expected_base_sha:
        raise ValueError("context base SHA does not match the selected PR base")


def main() -> None:
    workspace = Path(os.environ["REPAIR_WORKSPACE"]).resolve()
    artifact_dir = _safe_artifact_dir(workspace)
    context = _read_json(artifact_dir / "pr-repair-context.json")
    instructions = (artifact_dir / "pr-repair-prompt.md").read_text(encoding="utf-8")
    if not isinstance(context, dict):
        raise ValueError("repair context must be an object")

    expected_head_sha = validate_sha(os.environ["EXPECTED_HEAD_SHA"], "expected head SHA")
    expected_base_sha = validate_sha(os.environ["EXPECTED_BASE_SHA"], "expected base SHA")
    validate_context_heads(context, expected_head_sha, expected_base_sha)
    if _command(workspace, "rev-parse", "HEAD").strip() != expected_head_sha:
        raise ValueError("target HEAD does not match the selected PR commit")
    diff = _command(workspace, "diff", "--no-ext-diff", "--binary", f"{expected_base_sha}...HEAD")
    if len(diff) > _MAX_DIFF_CHARS:
        diff = diff[:_MAX_DIFF_CHARS] + "\n[diff truncated]\n"

    request_body = build_request_body(
        instructions,
        context,
        diff,
        model=os.environ.get("OPENROUTER_MODEL"),
    )
    result = _model_request(request_body)
    choices = result.get("choices") or []
    raw_content = (choices[0].get("message") or {}).get("content") if choices else None
    try:
        decision = validate_model_decision(json.loads(_strip_json_fence(raw_content)))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        _write_result(
            artifact_dir,
            {
                "action": "blocked",
                "patch": "",
                "summary": f"Model result rejected: {type(exc).__name__}",
                "tests": [],
                "fixed_comment_ids": [],
                "changed_paths": [],
            },
        )
        return

    if decision["action"] == "patch":
        try:
            decision["changed_paths"] = sorted(apply_repair_patch(workspace, decision["patch"]))
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
            decision = {
                **decision,
                "action": "blocked",
                "patch": "",
                "summary": f"Patch rejected: {type(exc).__name__}",
                "changed_paths": [],
            }
    else:
        decision["changed_paths"] = []
    _write_result(artifact_dir, decision)


if __name__ == "__main__":
    main()
