import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


GITHUB_DIR = Path(__file__).parents[1] / ".github"
sys.path.insert(0, str(GITHUB_DIR))


def _load_script(name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, GITHUB_DIR / name)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_openrouter_request_uses_supported_nemotron_configuration():
    repair = _load_script("pr-repair-openrouter.py", "pr_repair_openrouter_config")

    body = repair.build_request_body(
        instructions="Review the change.",
        context={"pull_request": {"base": "main"}},
        diff="diff --git a/example.py b/example.py",
    )

    assert body["model"] == "nvidia/nemotron-3-ultra-550b-a55b:free"
    assert "response_format" not in body


def test_patch_path_validation_rejects_protected_deletion():
    utils = _load_script("pr_repair_utils.py", "pr_repair_utils")
    patch = """\
diff --git a/.github/workflows/secret.yml b/.github/workflows/secret.yml
deleted file mode 100644
--- a/.github/workflows/secret.yml
+++ /dev/null
@@ -1 +0,0 @@
-name: secret
"""

    with pytest.raises(ValueError, match="protected"):
        utils.validate_patch_paths(patch)


def test_patch_path_validation_rejects_protected_rename():
    utils = _load_script("pr_repair_utils.py", "pr_repair_utils")
    patch = """\
diff --git a/.github/pr-repair-context.py b/src/context.py
similarity index 99%
rename from .github/pr-repair-context.py
rename to src/context.py
"""

    with pytest.raises(ValueError, match="protected"):
        utils.validate_patch_paths(patch)


def test_patch_path_validation_rejects_controller_and_generated_paths():
    utils = _load_script("pr_repair_utils.py", "pr_repair_utils")

    for path in ("controller/repair.py", "pr-repair-context.json", ".git/config"):
        patch = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        with pytest.raises(ValueError, match="protected"):
            utils.validate_patch_paths(patch)


def test_patch_path_validation_accepts_regular_file_change():
    utils = _load_script("pr_repair_utils.py", "pr_repair_utils")
    patch = """\
diff --git a/src/repair.py b/src/repair.py
--- a/src/repair.py
+++ b/src/repair.py
@@ -1 +1 @@
-old
+new
"""

    assert utils.validate_patch_paths(patch) == {"src/repair.py"}


def test_model_decision_rejects_invalid_types_before_side_effects():
    utils = _load_script("pr_repair_utils.py", "pr_repair_utils")

    with pytest.raises(ValueError, match="tests"):
        utils.validate_model_decision(
            {
                "action": "patch",
                "patch": "diff --git a/src/a.py b/src/a.py\n",
                "summary": "summary",
                "tests": [{}],
                "fixed_comment_ids": [],
            }
        )


def test_repair_patch_stages_only_paths_from_the_patch(tmp_path):
    repair = _load_script("pr-repair-openrouter.py", "pr_repair_openrouter")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    source = tmp_path / "src" / "repair.py"
    source.parent.mkdir()
    source.write_text("old\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", "src/repair.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "base"], check=True)

    patch = """\
diff --git a/src/repair.py b/src/repair.py
--- a/src/repair.py
+++ b/src/repair.py
@@ -1 +1 @@
-old
+new
"""

    assert repair.apply_repair_patch(tmp_path, patch) == {"src/repair.py"}
    staged = subprocess.run(
        ["git", "-C", str(tmp_path), "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert staged == ["src/repair.py"]


def test_matrix_excludes_controller_and_fork_heads():
    matrix = _load_script("pr-repair-matrix.py", "pr_repair_matrix")
    prs = [
        {
            "number": 1,
            "head": {"ref": "feature/one", "sha": "a" * 40, "repo": {"full_name": "owner/repo"}},
            "base": {"ref": "main", "sha": "b" * 40},
        },
        {
            "number": 2,
            "head": {"ref": "codex/pr-repair-agent", "sha": "c" * 40, "repo": {"full_name": "owner/repo"}},
            "base": {"ref": "main", "sha": "b" * 40},
        },
        {
            "number": 3,
            "head": {"ref": "feature/fork", "sha": "d" * 40, "repo": {"full_name": "other/repo"}},
            "base": {"ref": "main", "sha": "b" * 40},
        },
        {
            "number": 4,
            "state": "open",
            "head": {"ref": "main", "sha": "e" * 40, "repo": {"full_name": "owner/repo"}},
            "base": {"ref": "release", "sha": "f" * 40},
        },
        {
            "number": 5,
            "state": "closed",
            "head": {"ref": "feature/closed", "sha": "1" * 40, "repo": {"full_name": "owner/repo"}},
            "base": {"ref": "main", "sha": "b" * 40},
        },
    ]

    assert matrix.build_matrix_entries(prs, "owner/repo", "main") == [
        {
            "number": 1,
            "head_ref": "feature/one",
            "head_sha": "a" * 40,
            "base_ref": "main",
            "base_sha": "b" * 40,
        }
    ]


def test_report_replies_only_to_verified_unreplied_bot_comments():
    report = _load_script("pr-repair-report.py", "pr_repair_report")
    comments = [
        {"id": 10, "path": "src/a.py", "user": {"type": "Bot"}},
        {"id": 11, "path": "src/b.py", "user": {"type": "Bot"}},
        {"id": 12, "path": "src/c.py", "user": None},
        {"id": 13, "path": "src/d.py", "user": {"type": "Bot"}, "in_reply_to_id": 10},
    ]
    result = {"fixed_comment_ids": [10, 11, 12, 999]}

    assert report.select_reply_comment_ids(comments, result) == [11]


def test_report_reads_current_review_comments_with_pagination(monkeypatch):
    report = _load_script("pr-repair-report.py", "pr_repair_report_pagination")

    class Response:
        def __init__(self, payload, link=""):
            self._payload = json.dumps(payload).encode()
            self.headers = {"Link": link}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args):
            return self._payload

    responses = iter(
        [
            Response([{"id": 1}], '<https://api.github.com/next>; rel="next"'),
            Response([{"id": 2}]),
        ]
    )
    monkeypatch.setattr(report.urllib.request, "urlopen", lambda *args, **kwargs: next(responses))

    assert report.fetch_review_comments("owner/repo", "17", "token") == [{"id": 1}, {"id": 2}]


def test_workflow_keeps_privileged_job_from_running_pr_code():
    workflow = (GITHUB_DIR / "workflows" / "pr-repair-agent.yml").read_text()

    assert "pip install -r requirements.txt" not in workflow
    assert "python -m pytest" not in workflow
    assert "git add -A" not in workflow
    assert "path: controller" not in workflow
    assert "path: target" in workflow
    assert "ref: ${{ matrix.head_sha }}" in workflow
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow
    assert "ref: ${{ matrix.base_sha }}" not in workflow
    assert "ref: ${{ github.sha }}" not in workflow
    assert "DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}" in workflow
    assert "EXPECTED_HEAD_SHA: ${{ matrix.head_sha }}" in workflow
    assert "BASE_SHA: ${{ matrix.base_sha }}" in workflow


def test_workflow_uses_openrouter_repair_credentials():
    workflow = (GITHUB_DIR / "workflows" / "pr-repair-agent.yml").read_text()

    assert "Run OpenRouter repair cycle" in workflow
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in workflow
    assert "OPENROUTER_MODEL: nvidia/nemotron-3-ultra-550b-a55b:free" in workflow
    assert "python .github/pr-repair-openrouter.py" in workflow
    assert "AUTH_HEADER=\"$(printf 'x-access-token:%s' \"$GITHUB_TOKEN\" | base64 -w 0)\"" in workflow
    assert 'http.extraheader=Authorization: Basic ${AUTH_HEADER}' in workflow
    assert "DEEPINFRA" not in workflow


def test_workflow_blocks_until_openrouter_helper_is_trusted():
    workflow = (GITHUB_DIR / "workflows" / "pr-repair-agent.yml").read_text()

    assert 'if [ -f ".github/pr-repair-openrouter.py" ]; then' in workflow
    assert '"action":"blocked"' in workflow
    assert "OpenRouter helper is not yet available on the trusted default branch" in workflow


def test_ci_workflow_has_one_top_level_environment_block():
    workflow = (GITHUB_DIR / "workflows" / "ci.yml").read_text()

    assert workflow.count("\nenv:\n") == 1
    assert 'SENTRY_DSN: ""' in workflow
    assert 'OTEL_EXPORTER_OTLP_ENDPOINT: ""' in workflow
    assert 'OTEL_SDK_DISABLED: "false"' in workflow


def test_prepare_bootstraps_matrix_without_executing_pr_helper_code():
    workflow = (GITHUB_DIR / "workflows" / "pr-repair-agent.yml").read_text()
    prepare = workflow.split("\n  repair:", 1)[0]

    assert "ref: ${{ github.event.repository.default_branch }}" in prepare
    assert "uses: actions/github-script@" in prepare
    assert "github.paginate" in prepare
    assert "python .github/pr-repair-matrix.py" not in prepare


def test_context_artifacts_are_written_to_the_run_directory():
    context = (GITHUB_DIR / "pr-repair-context.py").read_text()
    repair = (GITHUB_DIR / "pr-repair-openrouter.py").read_text()

    assert "REPAIR_ARTIFACT_DIR" in context
    assert "REPAIR_ARTIFACT_DIR" in repair
    assert 'open("pr-repair-context.json"' not in context
    assert 'open(workspace / "repair-result.json"' not in repair


def test_repair_requires_the_matrix_selected_commit():
    repair = _load_script("pr-repair-openrouter.py", "pr_repair_openrouter_heads")
    context = {"pull_request": {"head_sha": "a" * 40, "base_sha": "b" * 40}}

    with pytest.raises(ValueError, match="head SHA"):
        repair.validate_context_heads(context, "c" * 40, "b" * 40)
