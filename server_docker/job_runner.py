from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Iterable

try:
    from .artifact_names import artifact_filename, artifact_stem
    from .history_store import HistoryStore
    from .job_files import safe_owned_path, write_analysis_file
except ImportError:  # Docker executes app modules from /app, not as a package.
    from artifact_names import artifact_filename, artifact_stem
    from history_store import HistoryStore
    from job_files import safe_owned_path, write_analysis_file


RETRYABLE_CODES = {
    "BROWSERLESS_UNREACHABLE", "BROWSERLESS_ERROR", "BROWSERLESS_BAD_JSON",
    "BROWSERLESS_SCRIPT_ERROR", "BROWSERLESS_BAD_RESULT", "YUANBAO_EMPTY_RESPONSE",
    "YUANBAO_PREVIEW_URL_MISSING", "VIDEO_URL_MISSING", "WECHAT_VIDEO_URL_MISSING",
    "DOWNLOAD_TIMEOUT", "DOWNLOAD_FAILED", "DOWNLOAD_VERIFY_FAILED",
}
NON_RETRYABLE_CODES = {
    "INVALID_URL", "INVALID_OUTPUT_FORMAT", "BAD_REQUEST", "UNAUTHORIZED",
    "YUANBAO_LOGIN_REQUIRED", "COOKIE_FILE_MISSING", "COOKIE_EMPTY",
    "SESSION_STATE_INVALID", "FUNCTION_FILE_MISSING",
}


def error_summary(exc: BaseException, attempt: int) -> dict[str, Any]:
    code = str(getattr(exc, "code", exc.__class__.__name__) or exc.__class__.__name__)
    message = str(getattr(exc, "message", str(exc)) or code)
    status = getattr(exc, "status", None)
    return {
        "attempt": attempt,
        "code": code[:120],
        "message": message[:500],
        "status": int(status) if isinstance(status, int) else None,
    }


def is_retryable_error(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "") or "")
    if code in NON_RETRYABLE_CODES:
        return False
    if code in RETRYABLE_CODES:
        return True
    status = getattr(exc, "status", None)
    return isinstance(status, int) and status >= 500


def cleanup_artifacts(download_dir: Path, filenames: Iterable[str | None]) -> None:
    for filename in dict.fromkeys(filenames):
        path = safe_owned_path(download_dir, filename)
        if path and path.exists():
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def run_parse_job(
    job_id: str,
    input_url: str,
    prompt: str | None,
    preset: dict[str, Any] | None,
    output_format: str,
    download_requested: bool,
    *,
    store: HistoryStore,
    download_dir: Path,
    analyzer: Callable[[str, str | None], dict[str, Any]],
    downloader: Callable[[str, str, str], Path],
    max_attempts: int = 3,
    sleeper: Callable[[float], None] = time.sleep,
    thumbnailer: Callable[[Path, str, str | None, Path | None], Path | None] | None = None,
) -> dict[str, Any]:
    if thumbnailer is None:
        try:
            from .thumbnail_service import create_thumbnail as thumbnailer_impl
        except ImportError:
            from thumbnail_service import create_thumbnail as thumbnailer_impl
        thumbnailer = thumbnailer_impl

    started = time.monotonic()
    retry_errors: list[dict[str, Any]] = []
    max_attempts = min(3, max(1, int(max_attempts)))

    for attempt in range(1, max_attempts + 1):
        store.update_job(
            job_id,
            status="running",
            attempts_used=attempt,
            max_attempts=max_attempts,
            retry_errors=retry_errors,
            error_code=None,
            error_message=None,
        )
        provisional: list[str | None] = []
        try:
            result = analyzer(input_url, prompt)
            content = str(result.get("content") or "").strip()
            preview_url = str(result.get("previewUrl") or "").strip()
            direct_url = str(result.get("directUrl") or "").strip()
            card = result.get("card") if isinstance(result.get("card"), dict) else {}
            video_title = str(card.get("title") or "").strip()
            cover_url = str(card.get("coverUrl") or "").strip()
            store.update_job(
                job_id,
                yuanbao_content=content,
                preview_url=preview_url,
                source_direct_url=direct_url,
                video_title=video_title or None,
                cover_url=cover_url or None,
            )
            job = store.get_job(job_id)
            assert job is not None
            stem = artifact_stem(video_title or None, job_id)
            text_path = write_analysis_file(download_dir, job, output_format)
            provisional.append(text_path.name)
            video_path = None
            if download_requested:
                provisional.append(artifact_filename(video_title or None, job_id, "mp4"))
                video_path = downloader(stem, direct_url, preview_url)
                provisional.append(video_path.name)
            thumbnail_path = None
            if cover_url or video_path is not None:
                target_thumbnail = artifact_filename(video_title or None, job_id, "jpg")
                try:
                    thumbnail_path = thumbnailer(download_dir, target_thumbnail, cover_url or None, video_path)
                except Exception:
                    thumbnail_path = None
            elapsed_ms = int((time.monotonic() - started) * 1000)
            row = store.update_job(
                job_id,
                status="completed",
                attempts_used=attempt,
                max_attempts=max_attempts,
                retry_errors=retry_errors,
                error_code=None,
                error_message=None,
                text_filename=text_path.name,
                text_bytes=text_path.stat().st_size,
                video_filename=video_path.name if video_path else None,
                video_bytes=video_path.stat().st_size if video_path else None,
                thumbnail_filename=thumbnail_path.name if thumbnail_path else None,
                elapsed_ms=elapsed_ms,
            )
            assert row is not None
            return row
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            summary = error_summary(exc, attempt)
            retry_errors.append(summary)
            current = store.get_job(job_id) or {}
            cleanup_artifacts(
                download_dir,
                [
                    *provisional,
                    current.get("text_filename"),
                    current.get("video_filename"),
                    current.get("thumbnail_filename"),
                    current.get("bundle_filename"),
                ],
            )
            retryable = is_retryable_error(exc)
            final = (not retryable) or attempt >= max_attempts
            row = store.update_job(
                job_id,
                status="failed" if final else "running",
                attempts_used=attempt,
                max_attempts=max_attempts,
                retry_errors=retry_errors,
                error_code=summary["code"],
                error_message=summary["message"],
                text_filename=None,
                text_bytes=None,
                video_filename=None,
                video_bytes=None,
                thumbnail_filename=None,
                bundle_filename=None,
                elapsed_ms=int((time.monotonic() - started) * 1000) if final else None,
            )
            if final:
                assert row is not None
                return row
            sleeper(attempt)

    raise RuntimeError("unreachable")
