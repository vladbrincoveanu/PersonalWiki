import os
import re
import subprocess
import tempfile
from ingesters import Document

_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->.*$", re.MULTILINE)
_TAG_RE = re.compile(r"<[^>]+>")
_CUE_SETTING_RE = re.compile(r"^(?:align|line|position|size|vertical):.*$", re.MULTILINE)


def _parse_vtt(vtt_text: str) -> str:
    # Remove WEBVTT header block
    text = re.sub(r"^WEBVTT.*?\n\n", "", vtt_text, count=1, flags=re.DOTALL)
    # Remove timestamp cue lines
    text = _TIMESTAMP_RE.sub("", text)
    # Remove cue setting lines (align:, line:, etc.)
    text = _CUE_SETTING_RE.sub("", text)
    # Remove inline HTML tags (<c>, <b>, <i>, timestamps like <00:00:01.000>)
    text = _TAG_RE.sub("", text)
    # Split, strip, drop blanks, deduplicate consecutive identical lines
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    deduped: list[str] = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


def extract_youtube(url: str) -> Document:
    with tempfile.TemporaryDirectory() as tmpdir:
        output_template = os.path.join(tmpdir, "%(id)s")
        cmd = [
            "yt-dlp",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "--output", output_template,
            "--quiet",
            url,
        ]
        subprocess.run(cmd, capture_output=True, timeout=60)

        vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
        if not vtt_files:
            return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")

        with open(os.path.join(tmpdir, vtt_files[0]), encoding="utf-8") as f:
            vtt_text = f.read()

        transcript = _parse_vtt(vtt_text)
        if not transcript.strip():
            return Document(raw_text=f"[NO_TRANSCRIPT] {url}", content_type="video")

        return Document(raw_text=transcript, content_type="video")
