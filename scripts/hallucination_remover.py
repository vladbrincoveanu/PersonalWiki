#!/usr/bin/env python3
"""
Hallucination remover — finds dead code, gig tests, and debug artifacts.

Usage:
    python scripts/hallucination_remover.py --path . [--fix]
"""
import ast
import argparse
import re
from pathlib import Path

PRINT_RE = re.compile(r'\bprint\s*\(')
BREAKPOINT_RE = re.compile(r'\bbreakpoint\s*\(')


def is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py")


def scan_file(path: Path, fix: bool = False) -> list[tuple[int, str]]:
    issues = []
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return issues

    original = content

    # Check for print() in non-test files
    if not is_test_file(path):
        for i, line in enumerate(content.splitlines(), 1):
            if PRINT_RE.search(line):
                issues.append((i, "print() statement found (auto-removed)"))
                if fix:
                    content = content.replace(line + "\n", "").replace(line, "")
            if BREAKPOINT_RE.search(line):
                issues.append((i, "breakpoint() found (auto-removed)"))
                if fix:
                    content = content.replace(line + "\n", "").replace(line, "")

    # AST-based checks
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        return issues

    # Track line ranges to remove for if False:/if True: branches
    lines_to_remove = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Constant) and node.test.value is False:
                issues.append((node.lineno, "unreachable if False: branch"))
                if fix:
                    # Collect lines from lineno to end_lineno (1-indexed)
                    for ln in range(node.lineno, node.end_lineno + 1):
                        lines_to_remove.add(ln)
            elif isinstance(node.test, ast.Constant) and node.test.value is True:
                issues.append((node.lineno, "redundant if True: branch"))
                if fix:
                    for ln in range(node.lineno, node.end_lineno + 1):
                        lines_to_remove.add(ln)

    if fix and (content != original or lines_to_remove):
        # Rebuild content without removed lines
        all_lines = content.splitlines(keepends=True)
        # Convert to 0-indexed for filtering
        removed_0indexed = {ln - 1 for ln in lines_to_remove}
        new_lines = [l for i, l in enumerate(all_lines) if i not in removed_0indexed]
        content = "".join(new_lines)

    if fix and content != original:
        path.write_text(content, encoding="utf-8")

    return issues


def scan(path: Path, fix: bool = False) -> dict[Path, list[tuple[int, str]]]:
    results = {}
    for py_file in path.rglob("*.py"):
        if ".venv" in py_file.parts or "__pycache__" in py_file.parts:
            continue
        issues = scan_file(py_file, fix=fix)
        if issues:
            results[py_file] = issues
    return results


def main():
    parser = argparse.ArgumentParser(description="Remove hallucinations from code")
    parser.add_argument("--path", type=str, default=".", help="Directory to scan")
    parser.add_argument("--fix", action="store_true", help="Auto-fix safe patterns")
    args = parser.parse_args()

    scan_path = Path(args.path).resolve()
    results = scan(scan_path, fix=args.fix)

    if not results:
        print("No hallucinations found.")
        return

    for file, issues in sorted(results.items()):
        for lineno, msg in issues:
            print(f"{file}:{lineno} — {msg}")


if __name__ == "__main__":
    main()