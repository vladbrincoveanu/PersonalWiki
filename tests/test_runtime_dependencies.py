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


def test_parse_direct_pins_normalizes_names_and_ignores_includes():
    manifest = """
    # Tooling inherits runtime packages.
    -r requirements.txt
    uvicorn[standard]==0.52.4
    lxml_html_clean==0.4.5
    """

    assert _parse_exact_pins(manifest) == {
        "uvicorn": "0.52.4",
        "lxml-html-clean": "0.4.5",
    }
    assert _parse_requirement_names(manifest + "\ntorch>=2.0\n") == {
        "uvicorn",
        "lxml-html-clean",
        "torch",
    }


def test_pin_drift_reports_missing_and_mismatched_versions():
    manifest = "foo==1.0\nbar[extra]==2.0\n"
    lock = "foo==1.0\nbar==3.0\nbaz==4.0\n"

    assert _pin_drift(manifest, lock) == {"bar": ("2.0", "3.0")}


def _normalize_package_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_requirement_names(text):
    packages = set()
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "-")):
            continue
        match = re.match(r"\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?", line)
        if match:
            packages.add(_normalize_package_name(match.group(1)))
    return packages


def _parse_exact_pins(text):
    pins = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "-")):
            continue
        match = re.fullmatch(
            r"\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s;]+)(?:\s*;.*)?\s*",
            line,
        )
        if match:
            pins[_normalize_package_name(match.group(1))] = match.group(2)
    return pins


def _pin_drift(manifest, lock):
    expected = _parse_exact_pins(manifest)
    actual = _parse_exact_pins(lock)
    return {
        package: (version, actual.get(package))
        for package, version in expected.items()
        if actual.get(package) != version
    }


def test_runtime_locks_exclude_heavy_ml_packages():
    for lock_name in ("requirements.lock.txt", "requirements-dev.lock.txt"):
        packages = _parse_requirement_names((ROOT / lock_name).read_text())
        prohibited = {
            package
            for package in packages
            if package in PROHIBITED_PACKAGES
            or package.startswith("docling")
            or package.startswith("nvidia-")
        }
        assert prohibited == set(), f"{lock_name} contains {sorted(prohibited)}"


def test_direct_requirements_exclude_heavy_ml_packages():
    for requirements_name in ("requirements.txt", "requirements-dev.txt"):
        packages = _parse_requirement_names((ROOT / requirements_name).read_text())
        prohibited = {
            package
            for package in packages
            if package in PROHIBITED_PACKAGES
            or package.startswith("docling")
            or package.startswith("nvidia-")
        }
        assert prohibited == set(), f"{requirements_name} contains {sorted(prohibited)}"


def test_direct_requirement_pins_match_generated_locks():
    pairs = (
        ("requirements.txt", "requirements.lock.txt"),
        ("requirements-dev.txt", "requirements-dev.lock.txt"),
    )
    for requirements_name, lock_name in pairs:
        drift = _pin_drift(
            (ROOT / requirements_name).read_text(),
            (ROOT / lock_name).read_text(),
        )
        assert drift == {}, f"{requirements_name} differs from {lock_name}: {drift}"


def test_dockerfile_does_not_install_ffmpeg():
    dockerfile = (ROOT / "Dockerfile").read_text().lower()

    assert "ffmpeg" not in dockerfile
