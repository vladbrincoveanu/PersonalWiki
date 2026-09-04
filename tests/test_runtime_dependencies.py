import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_PACKAGES = {
    "openai-whisper",
    "sentence-transformers",
    "torch",
    "torchvision",
    "transformers",
    "triton",
}


def _locked_packages(lock_name):
    packages = set()
    for line in (ROOT / lock_name).read_text().splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)==", line)
        if match:
            packages.add(match.group(1).lower().replace("_", "-"))
    return packages


def test_runtime_locks_exclude_heavy_ml_packages():
    for lock_name in ("requirements.lock.txt", "requirements-dev.lock.txt"):
        packages = _locked_packages(lock_name)
        prohibited = {
            package
            for package in packages
            if package in PROHIBITED_PACKAGES
            or package.startswith("docling")
            or package.startswith("nvidia-")
        }
        assert prohibited == set(), f"{lock_name} contains {sorted(prohibited)}"


def test_dockerfile_does_not_install_ffmpeg():
    dockerfile = (ROOT / "Dockerfile").read_text().lower()

    assert "ffmpeg" not in dockerfile
