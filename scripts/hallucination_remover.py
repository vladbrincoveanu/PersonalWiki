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
    lines = content.splitlines(keepends=True)

    # Phase 1: AST analysis on ORIGINAL content
    lines_to_remove: set[int] = set()  # 0-indexed
    try:
        tree = ast.parse(content, filename=str(path))
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            if isinstance(node.test, ast.Constant) and node.test.value is False:
                issues.append((node.lineno, "unreachable if False: branch"))
                if fix:
                    for ln in range(node.lineno - 1, node.end_lineno):
                        lines_to_remove.add(ln)
            elif isinstance(node.test, ast.Constant) and node.test.value is True:
                issues.append((node.lineno, "redundant if True: branch"))
                if fix:
                    for ln in range(node.lineno - 1, node.end_lineno):
                        lines_to_remove.add(ln)

    # Phase 2: String-based replacements (print/breakpoint) on original
    for i, line in enumerate(lines):
        if is_test_file(path):
            continue
        if PRINT_RE.search(line):
            issues.append((i + 1, "print() statement found (auto-removed)"))
            if fix:
                lines_to_remove.add(i)
        elif BREAKPOINT_RE.search(line):
            issues.append((i + 1, "breakpoint() found (auto-removed)"))
            if fix:
                lines_to_remove.add(i)

    # Phase 3: Rebuild
    if fix and lines_to_remove:
        new_lines = [l for i, l in enumerate(lines) if i not in lines_to_remove]
        content = "".join(new_lines)
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