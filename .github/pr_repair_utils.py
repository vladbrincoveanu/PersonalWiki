import re


_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REF_RE = re.compile(r"[A-Za-z0-9._/-]+")
_DIFF_HEADER_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)$")


def validate_ref(value: str, field: str) -> str:
    if not isinstance(value, str) or not _REF_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    if (
        value.startswith("/")
        or value.endswith("/")
        or value.startswith("-")
        or value.endswith(".")
        or ".." in value
        or "//" in value
        or "@{" in value
    ):
        raise ValueError(f"invalid {field}")
    return value


def validate_sha(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _validate_path(path: str) -> str:
    if (
        not path
        or path.startswith(("/", "\\"))
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise ValueError(f"invalid patch path: {path!r}")

    if path == ".git" or path.startswith(".git/") or path == ".github" or path.startswith(".github/"):
        raise ValueError(f"protected patch path: {path}")
    if path == "controller" or path.startswith("controller/"):
        raise ValueError(f"protected patch path: {path}")
    if path in {
        ".env",
        ".env.local",
        ".gitconfig",
        "pr-repair-context.json",
        "pr-repair-prompt.md",
        "repair-result.json",
        "repair-result.md",
    }:
        raise ValueError(f"protected patch path: {path}")
    return path


def _path_from_header(line: str, marker: str, prefix: str) -> str | None:
    value = line[len(marker):].split("\t", 1)[0]
    if value == "/dev/null":
        return None
    if not value.startswith(prefix):
        raise ValueError(f"unsupported patch header: {line}")
    return _validate_path(value[len(prefix):])


def validate_patch_paths(patch_text: str) -> set[str]:
    """Validate every old and new path in a textual patch before applying it."""
    if not isinstance(patch_text, str) or not patch_text.strip():
        raise ValueError("empty patch")

    paths: set[str] = set()
    saw_diff = False
    saw_old_header = False
    saw_new_header = False
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            match = _DIFF_HEADER_RE.fullmatch(line)
            if not match:
                raise ValueError("unsupported or quoted diff header")
            paths.add(_validate_path(match.group(1)))
            paths.add(_validate_path(match.group(2)))
            saw_diff = True
        elif line.startswith("--- "):
            path = _path_from_header(line, "--- ", "a/")
            if path:
                paths.add(path)
            saw_old_header = True
        elif line.startswith("+++ "):
            path = _path_from_header(line, "+++ ", "b/")
            if path:
                paths.add(path)
            saw_new_header = True
        elif line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            raise ValueError("rename and copy patches are not supported")
        elif line == "GIT binary patch":
            raise ValueError("binary patches are not supported")

    if not saw_diff or (not saw_old_header and not saw_new_header) or not paths:
        raise ValueError("patch does not contain a supported file diff")
    return paths


def validate_model_decision(decision: object) -> dict:
    if not isinstance(decision, dict):
        raise ValueError("model result must be an object")

    action = decision.get("action")
    if action not in {"patch", "no_change", "blocked"}:
        raise ValueError("model result has an invalid action")

    patch = decision.get("patch", "")
    if not isinstance(patch, str):
        raise ValueError("model result patch must be a string")
    if action == "patch" and not patch.strip():
        raise ValueError("patch action requires a non-empty patch")

    summary = decision.get("summary", "")
    if not isinstance(summary, str):
        raise ValueError("model result summary must be a string")

    tests = decision.get("tests", [])
    if not isinstance(tests, list) or not all(isinstance(test, str) for test in tests):
        raise ValueError("model result tests must be a list of strings")

    fixed_comment_ids = decision.get("fixed_comment_ids", [])
    if not isinstance(fixed_comment_ids, list) or not all(
        isinstance(comment_id, int) and not isinstance(comment_id, bool)
        for comment_id in fixed_comment_ids
    ):
        raise ValueError("model result fixed_comment_ids must be a list of integers")

    return {
        **decision,
        "action": action,
        "patch": patch,
        "summary": summary,
        "tests": tests,
        "fixed_comment_ids": fixed_comment_ids,
    }
