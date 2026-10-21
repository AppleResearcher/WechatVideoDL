from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

import requests

try:
    from .job_files import safe_owned_path
except ImportError:  # Docker executes modules from /app.
    from job_files import safe_owned_path

_REDIRECTS = {301, 302, 303, 307, 308}


def validate_public_http_url(url: str) -> str:
    value = str(url or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("thumbnail URL must be http(s)")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("thumbnail URL credentials are not allowed")
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("thumbnail host cannot be resolved") from exc
    if not infos:
        raise ValueError("thumbnail host cannot be resolved")
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise ValueError("thumbnail host resolved to invalid address") from exc
        if not ip.is_global:
            raise ValueError("thumbnail host is not public")
    return value


def _run_ffmpeg(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _tmp_path(root: Path, suffix: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=".wx-thumb-", suffix=suffix, dir=root)
    os.close(fd)
    return Path(name)


def _fetch_cover(
    root: Path,
    cover_url: str,
    *,
    http_get: Callable = requests.get,
    max_bytes: int,
    max_redirects: int = 3,
) -> Path | None:
    current = cover_url
    for redirect_count in range(max_redirects + 1):
        try:
            current = validate_public_http_url(current)
            response = http_get(
                current,
                stream=True,
                timeout=(5, 15),
                allow_redirects=False,
                headers={"User-Agent": "WechatVideoDL/thumbnail"},
            )
        except Exception:
            return None
        try:
            if response.status_code in _REDIRECTS:
                if redirect_count >= max_redirects:
                    return None
                location = str(response.headers.get("Location") or "").strip()
                if not location:
                    return None
                current = urljoin(current, location)
                try:
                    validate_public_http_url(current)
                except ValueError:
                    return None
                continue
            if response.status_code != 200:
                return None
            content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                return None
            temp = _tmp_path(root, ".cover")
            total = 0
            try:
                with temp.open("wb") as fh:
                    for chunk in response.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > max_bytes:
                            return None
                        fh.write(chunk)
                if total <= 0:
                    return None
                return temp
            finally:
                if total > max_bytes and temp.exists():
                    temp.unlink(missing_ok=True)
        finally:
            try:
                response.close()
            except Exception:
                pass
    return None


def create_thumbnail(
    download_dir: Path,
    target_filename: str,
    cover_url: str | None,
    video_path: Path | None,
    *,
    http_get: Callable = requests.get,
    ffmpeg_bin: str = "ffmpeg",
    max_bytes: int = 8_000_000,
) -> Path | None:
    root = Path(download_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = safe_owned_path(root, target_filename, {"jpg"})
    if target is None:
        return None

    cover_temp: Path | None = None
    output_temp: Path | None = None
    try:
        if cover_url:
            cover_temp = _fetch_cover(root, cover_url, http_get=http_get, max_bytes=max_bytes)
            if cover_temp is not None:
                output_temp = _tmp_path(root, ".jpg")
                if _run_ffmpeg([
                    ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(cover_temp),
                    "-frames:v", "1", "-q:v", "2", str(output_temp),
                ]) and output_temp.exists() and output_temp.stat().st_size > 0:
                    os.replace(output_temp, target)
                    output_temp = None
                    return target

        if video_path is not None and Path(video_path).exists():
            output_temp = _tmp_path(root, ".jpg")
            if _run_ffmpeg([
                ffmpeg_bin, "-y", "-loglevel", "error", "-ss", "0", "-i", str(video_path),
                "-frames:v", "1", "-q:v", "2", str(output_temp),
            ]) and output_temp.exists() and output_temp.stat().st_size > 0:
                os.replace(output_temp, target)
                output_temp = None
                return target
        return None
    finally:
        if cover_temp is not None:
            cover_temp.unlink(missing_ok=True)
        if output_temp is not None:
            output_temp.unlink(missing_ok=True)
