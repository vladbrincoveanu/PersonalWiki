import subprocess
import tempfile
import os
from datetime import datetime, timedelta

def test_update_last_triggered():
    with tempfile.TemporaryDirectory() as tmpdir:
        rule_file = os.path.join(tmpdir, "test-rule.md")
        with open(rule_file, "w") as f:
            f.write("---\nname: test-rule\ndescription: Test\npaths: []\nlast_triggered: 2026-01-01\n---\nprescription")
        result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/rule_updater.py",
             "--rules-dir", tmpdir, "--update-last-triggered", "test-rule"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        # Verify file was updated
        with open(rule_file) as f:
            content = f.read()
        assert "last_triggered: " in content

def test_check_expiration_finds_stale_rule():
    old_date = (datetime.now() - timedelta(days=72)).strftime("%Y-%m-%d")
    with tempfile.TemporaryDirectory() as tmpdir:
        rule_file = os.path.join(tmpdir, "stale-rule.md")
        with open(rule_file, "w") as f:
            f.write(f"---\nname: stale-rule\ndescription: Test\npaths: []\nlast_triggered: {old_date}\n---\nprescription")
        result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/rule_updater.py",
             "--rules-dir", tmpdir, "--check-expiration"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert data["status"] == "success"
        assert len(data["stale"]) == 1
        assert data["stale"][0]["name"] == "stale-rule"
        assert data["stale"][0]["days_ago"] >= 70