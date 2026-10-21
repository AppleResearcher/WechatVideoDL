from __future__ import annotations

import re

_ALLOWED_EXTS = {"txt", "md", "mp4", "jpg", "zip"}
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_CHARS_RE = re.compile(r'[\\/:*?"<>|]+')
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_SPACE_RE = re.compile(r"\s+")
_DOT_SEGMENTS_RE = re.compile(r"(?:^|\s)\.{2,}(?=\s|$)")
_JOB_RE = re.compile(r"^wxv_(\d{6})$")


def _truncate_utf8(text: str, max_bytes: int) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    raw = raw[:max_bytes]
    while raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ""


def _safe_title(video_title: str | None) -> str:
    text = str(video_title or "")
    text = _CONTROL_RE.sub(" ", text)
    text = _INVALID_CHARS_RE.sub("-", text)
    text = _DOT_SEGMENTS_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip(" .")
    text = re.sub(r"\.{2,}$", "", text).strip(" .")
    if not text:
        text = "微信视频号"
    base = text.split(".", 1)[0].upper()
    if base in _WINDOWS_RESERVED:
        text = "_" + text
    return text


def artifact_stem(video_title: str | None, job_id: str, max_stem_bytes: int = 180) -> str:
    match = _JOB_RE.fullmatch(str(job_id or ""))
    if not match:
        raise ValueError("invalid job id")
    if max_stem_bytes < 16:
        raise ValueError("max_stem_bytes too small")
    suffix = f"__{match.group(1)}"
    suffix_bytes = len(suffix.encode("utf-8"))
    title_budget = max_stem_bytes - suffix_bytes
    title = _truncate_utf8(_safe_title(video_title), title_budget).rstrip(" .") or "微信视频号"
    stem = f"{title}{suffix}"
    if len(stem.encode("utf-8")) > max_stem_bytes:
        fallback = f"微信视频号{suffix}"
        if len(fallback.encode("utf-8")) <= max_stem_bytes:
            return fallback
        raise ValueError("max_stem_bytes too small")
    return stem


def artifact_filename(video_title: str | None, job_id: str, ext: str) -> str:
    clean_ext = str(ext or "").lower().lstrip(".")
    if clean_ext not in _ALLOWED_EXTS:
        raise ValueError("unsupported artifact extension")
    return f"{artifact_stem(video_title, job_id)}.{clean_ext}"
