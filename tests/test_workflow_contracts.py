from pathlib import Path

import pytest
import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def workflow(name):
    # BaseLoader retains the Actions `on` key instead of treating it as a bool.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("name", ["ci.yml", "security.yml", "dependency-review.yml"])
def test_required_checks_run_for_every_pr_target(name):
    events = workflow(name)["on"]
    assert "pull_request" in events
    filters = events["pull_request"] or {}
    assert not any(key in filters for key in ("branches", "branches-ignore", "paths", "paths-ignore"))


@pytest.mark.parametrize(
    ("name", "job", "required_name", "needs"),
    [("ci.yml", "gate", "Required CI summary", ["static", "test", "integration", "docker"]),
     ("security.yml", "security_gate", "Security summary", ["codeql", "python_audit"])],
)
def test_summary_names_match_repository_ruleset(name, job, required_name, needs):
    summary = workflow(name)["jobs"][job]
    assert summary["name"] == required_name
    assert summary["if"] == "always()"
    assert summary["needs"] == needs


def test_extended_suite_installs_ocr_before_running_pdf_tests():
    steps = workflow("extended.yml")["jobs"]["extended"]["steps"]
    commands = [step.get("run", "") for step in steps]
    ocr_steps = [i for i, command in enumerate(commands) if "apt-get install" in command and "tesseract-ocr" in command]
    test_step = next(i for i, command in enumerate(commands) if "python -m pytest" in command)
    assert ocr_steps and ocr_steps[0] < test_step
