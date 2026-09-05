from pathlib import Path

import yaml


def test_privileged_repair_uses_only_default_branch_workflow_events():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/pr-repair-agent.yml"
    workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    assert not {"pull_request_review", "pull_request_review_comment"} & workflow["on"].keys()
    assert {"issue_comment", "schedule", "workflow_dispatch"} <= workflow["on"].keys()
    assert workflow["jobs"]["prepare"].get("if") == (
        "github.workflow_ref == format('{0}/.github/workflows/pr-repair-agent.yml@refs/heads/{1}', "
        "github.repository, github.event.repository.default_branch)"
    )
