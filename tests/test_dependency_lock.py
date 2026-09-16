from pathlib import Path
import re
import unittest


LOCKFILE = Path(__file__).parents[1] / "requirements.lock.txt"


def locked_version(package: str) -> str:
    pattern = re.compile(rf"^{re.escape(package)}==([^\s\\]+)")
    for line in LOCKFILE.read_text().splitlines():
        match = pattern.match(line)
        if match:
            return match.group(1)
    raise AssertionError(f"{package} is missing from {LOCKFILE}")


class DependencyLockTests(unittest.TestCase):
    def test_docling_and_docling_slim_use_the_same_release(self) -> None:
        self.assertEqual(locked_version("docling"), locked_version("docling-slim"))
