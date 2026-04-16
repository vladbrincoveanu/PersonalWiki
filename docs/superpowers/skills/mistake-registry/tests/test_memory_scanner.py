# docs/superpowers/skills/mistake-registry/tests/test_memory_scanner.py
import subprocess
import tempfile
import os

MEMORY_SAMPLE = """---
name: error-timeout-1
type: error
command: "curl https://api.example.com"
error: "Connection timeout"
file: "src/http/client.py"
timestamp: 2026-04-10
---
some content

---
name: error-timeout-2
type: error
command: "fetch /data"
error: "TimeoutError"
file: "services/api.ts"
timestamp: 2026-04-12
---

---
name: error-missing-await
type: error
command: "git push"
error: "SyntaxError: 'await' outside async function"
file: "src/bot.py"
timestamp: 2026-04-11
---
"""

def test_scanner_extracts_error_entries():
    """Scanner should extract all type:error entries."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        import json
        data = json.loads(result.stdout)
        assert data["total_entries"] == 3
    finally:
        os.unlink(path)

def test_scanner_clusters_by_pattern():
    """Scanner should cluster timeout errors together."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        clusters = data["clusters"]
        # Should have 2 clusters: timeout (2) and missing-await (1)
        assert len(clusters) == 2
        timeout_cluster = next(c for c in clusters if "timeout" in c["pattern_key"])
        assert timeout_cluster["count"] == 2
        assert "2026-04-12" in timeout_cluster["last_seen"]
    finally:
        os.unlink(path)

def test_scanner_threshold():
    """Scanner should only include clusters with count >= threshold."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
        f.write(MEMORY_SAMPLE)
        path = f.name
    try:
        result = subprocess.run(
            ["python", "docs/superpowers/skills/mistake-registry/memory_scanner.py",
             "--memory-path", path, "--min-count", "3"],
            capture_output=True, text=True
        )
        import json
        data = json.loads(result.stdout)
        assert len(data["clusters"]) == 0  # No cluster has 3+
    finally:
        os.unlink(path)