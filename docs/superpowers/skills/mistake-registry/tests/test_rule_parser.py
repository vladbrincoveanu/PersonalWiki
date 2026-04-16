# docs/superpowers/skills/mistake-registry/tests/test_rule_parser.py
import subprocess
import tempfile
import os

def test_draft_generates_valid_yaml_frontmatter():
    """Draft command should output markdown with valid YAML frontmatter."""
    result = subprocess.run(
        ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
         "draft", "--pattern-key", "http-timeout", "--count", "4",
         "--last-seen", "2026-04-14", "--files", "src/http/*.py"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    output = result.stdout
    assert output.startswith("---")
    assert "name: http-timeout" in output
    assert "last_triggered: null" in output

def test_write_creates_file():
    """Write command should create the rule file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        draft = os.path.join(tmpdir, "draft.md")
        rule_path = os.path.join(tmpdir, "rules", "test-rule.md")
        with open(draft, "w") as f:
            f.write("---\nname: test\ndescription: test\npaths: []\n---\ntest")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "write", "--rule-path", rule_path, "--draft", draft],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert os.path.exists(rule_path)

def test_read_rule_extracts_metadata():
    """Read command should parse existing rule and return JSON metadata."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write("---\nname: test-rule\ndescription: Test desc\npaths:\n  - '**/*.py'\nlast_triggered: 2026-04-01\n---\n- prescription")
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "read", "--rule-path", path],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["name"] == "test-rule"
        assert data["last_triggered"] == "2026-04-01"
    finally:
        os.unlink(path)