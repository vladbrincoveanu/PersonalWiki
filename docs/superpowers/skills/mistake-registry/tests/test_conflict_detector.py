# docs/superpowers/skills/mistake-registry/tests/test_conflict_detector.py
import subprocess
import tempfile
import os

RULE_SYNC = """---
name: prefer-sync-http
description: Use synchronous HTTP calls only
paths: ["**/*.py"]
last_triggered: 2026-03-01
---
- Use synchronous requests library only
"""

RULE_ASYNC = """---
name: prefer-async-http
description: Use async HTTP calls
paths: ["**/*.py"]
last_triggered: 2026-03-01
---
- Use aiohttp for HTTP calls
"""

def test_no_conflict_when_rules_differ():
    """Rules with unrelated content should not conflict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(os.path.join(rules_dir, "sync.md"), "w") as f:
            f.write(RULE_SYNC)
        with open(os.path.join(rules_dir, "async.md"), "w") as f:
            f.write(RULE_ASYNC)
        new_rule = os.path.join(tmpdir, "new.md")
        with open(new_rule, "w") as f:
            f.write("---\nname: new-rule\ndescription: New unrelated rule\npaths: ['**/*.go']\n---\n- Do something in Go")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", new_rule],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert data["conflicts"] == []

def test_detects_contradiction_in_body():
    """New rule about timeouts vs existing rule about async should not conflict
    (they address different concerns)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(os.path.join(rules_dir, "timeout.md"), "w") as f:
            f.write("---\nname: http-timeout\ndescription: Always set timeout\npaths: ['**/*.py']\n---\n- Always set timeout on HTTP calls")
        new_rule = os.path.join(tmpdir, "new.md")
        with open(new_rule, "w") as f:
            f.write("---\nname: new-timeout\ndescription: Strict timeout policy\npaths: ['**/*.py']\n---\n- Timeout must be under 5 seconds")
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", new_rule],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        # timeout + timeout = same domain, but different prescriptions
        # These don't contradict — they reinforce. status = ok
        assert data["status"] == "ok"