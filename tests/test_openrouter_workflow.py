from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "ai-code-review.yml"


def test_ai_review_workflow_uses_openrouter_instead_of_deepinfra():
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "OPENROUTER__KEY" in workflow
    assert "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free" in workflow
    assert "DEEPINFRA" not in workflow
