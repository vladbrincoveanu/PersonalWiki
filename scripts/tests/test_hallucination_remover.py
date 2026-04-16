import pytest
import subprocess
import tempfile
from pathlib import Path


def test_detects_print_in_source():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('print("debug")\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "print(" in result.stdout


def test_detects_breakpoint():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('breakpoint()\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "breakpoint()" in result.stdout


def test_detects_unreachable_if_false():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('if False:\n    x = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir],
            capture_output=True, text=True
        )
        assert "if False" in result.stdout


def test_auto_removes_print_with_fix():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('print("debug")\nx = 1\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir, "--fix"],
            capture_output=True, text=True
        )
        content = test_file.read_text()
        assert "print" not in content
        assert "x = 1" in content


def test_auto_removes_breakpoint_with_fix():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('x = 1\nbreakpoint()\ny = 2\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir, "--fix"],
            capture_output=True, text=True
        )
        content = test_file.read_text()
        assert "breakpoint()" not in content
        assert "x = 1" in content
        assert "y = 2" in content


def test_auto_removes_print_and_if_false_combined():
    """Test that print and if False: are both removed correctly when using --fix.

    This verifies the bugfix: line numbers from AST analysis are based on the
    original content, not modified content after print removal.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "sample.py"
        test_file.write_text('print("debug")\nx = 1\nif False:\n    y = 2\nz = 3\n')
        result = subprocess.run(
            ["python", "scripts/hallucination_remover.py", "--path", tmpdir, "--fix"],
            capture_output=True, text=True
        )
        content = test_file.read_text()
        # print should be removed
        assert "print" not in content
        # if False block should be removed
        assert "if False" not in content
        # remaining code should be intact
        assert "x = 1" in content
        assert "z = 3" in content
        # y = 2 inside the if False block should also be gone
        assert "y = 2" not in content