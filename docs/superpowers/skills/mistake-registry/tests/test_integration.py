"""Full round-trip integration test: scan -> draft -> detect conflict -> write."""
import subprocess
import tempfile
import os
import json

MEMORY_WITH_PATTERNS = """---
name: error-timeout-1
type: error
error: "Connection timeout after 30s"
file: "src/http/client.py"
timestamp: 2026-04-10
---
---
name: error-timeout-2
type: error
error: "TimeoutError: timed out"
file: "src/http/client.py"
timestamp: 2026-04-12
---
---
name: error-timeout-3
type: error
error: "timeout in requests.get"
file: "services/api.py"
timestamp: 2026-04-14
---
"""

def test_full_round_trip():
    with tempfile.TemporaryDirectory() as tmpdir:
        memory_path = os.path.join(tmpdir, "MEMORY.md")
        rules_dir = os.path.join(tmpdir, "rules")
        os.makedirs(rules_dir)
        with open(memory_path, "w") as f:
            f.write(MEMORY_WITH_PATTERNS)

        # 1. Scan memory
        scan_result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", memory_path, "--min-count", "3"],
            capture_output=True, text=True
        )
        assert scan_result.returncode == 0
        data = json.loads(scan_result.stdout)
        assert data["total_entries"] == 3

        # 2. Draft a rule for the top cluster
        draft_result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "draft", "--pattern-key", "timeout",
             "--count", "3", "--last-seen", "2026-04-14",
             "--files", "src/http/*.py", "services/*.py"],
            capture_output=True, text=True
        )
        assert draft_result.returncode == 0
        assert "name: timeout" in draft_result.stdout

        # 3. Save draft to temp file
        draft_path = os.path.join(tmpdir, "draft.md")
        with open(draft_path, "w") as f:
            f.write(draft_result.stdout)

        # 4. Detect conflicts (should be none)
        conflict_result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/conflict_detector.py",
             "--rules-dir", rules_dir, "--new-rule-path", draft_path],
            capture_output=True, text=True
        )
        assert conflict_result.returncode == 0
        conflict_data = json.loads(conflict_result.stdout)
        assert conflict_data["status"] == "ok"

        # 5. Write rule
        rule_path = os.path.join(rules_dir, "timeout.md")
        write_result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "write", "--rule-path", rule_path, "--draft", draft_path],
            capture_output=True, text=True
        )
        assert write_result.returncode == 0
        assert os.path.exists(rule_path)

        # 6. Verify rule contents
        read_result = subprocess.run(
            ["python3", "docs/superpowers/skills/mistake-registry/rule_parser.py",
             "read", "--rule-path", rule_path],
            capture_output=True, text=True
        )
        read_data = json.loads(read_result.stdout)
        assert read_data["name"] == "timeout"