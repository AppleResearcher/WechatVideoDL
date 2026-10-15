#!/usr/bin/env python3
"""Local-only Whisper worker for WechatVideoDL.

No listening TCP port or Docker socket. Communicates through a private,
shared-volume queue. The script itself never receives Yuanbao credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import threading
import time
from pathlib import Path
from typing import Callable

JOB_ID = re.compile(r"^wxv_\d{6}$")
MODEL_CACHE = {}


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        stream.write(data)
    os.replace(temp, path)


def resolve_video(download_dir: Path, filename: str) -> Path:
    """Permit only existing, regular .mp4 files within this data folder."""
    if not filename or Path(filename).name != filename or not filename.lower().endswith(".mp4"):
        raise ValueError("INVALID_VIDEO_FILENAME")
    target = download_dir / filename
    if target.is_symlink() or not target.is_file():
        raise ValueError("VIDEO_NOT_FOUND")
    resolved = target.resolve()
    if resolved.parent != download_dir.resolve():
        raise ValueError("UNSAFE_VIDEO_PATH")
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError("INVALID_MEDIA")
    return resolved


def default_transcriber(video: Path, model_name: str) -> str:
    import torch
    import whisper
    torch.set_num_threads(4)
    cache = MODEL_CACHE
    if model_name not in cache:
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        # The operator must prefetch a permitted model; runtime downloads
        # during a user-facing job are deliberately not supported.
        from whisper import _MODELS
        url = _MODELS.get(model_name)
        if url is None:
            raise ValueError("UNKNOWN_WHISPER_MODEL")
        model_path = Path.home() / ".cache" / "whisper" / (url.split("/")[-1])
        if not model_path.is_file():
            raise RuntimeError("WHISPER_MODEL_NOT_CACHED")
        cache[model_name] = whisper.load_model(
            model_name, device=device, download_root=str(model_path.parent)
        )
    result = cache[model_name].transcribe(
        str(video), language="zh", task="transcribe", fp16=False, verbose=False
    )
    return str(result.get("text") or "").strip()


def process_request(data_dir: Path, payload: dict, transcribe: Callable[[Path, str], str]) -> dict:
    job_id = str(payload.get("job_id") or "")
    if not JOB_ID.fullmatch(job_id):
        raise ValueError("INVALID_JOB_ID")
    video = resolve_video(data_dir / "downloads", str(payload.get("video_filename") or ""))
    model = str(payload.get("model") or "base")
    if model not in {"base", "small", "medium", "turbo"}:
        raise ValueError("MODEL_NOT_ALLOWED")
    start = time.monotonic()
    text = transcribe(video, model)
    if len(text) < 20:
        raise ValueError("TRANSCRIPT_EMPTY")
    output = data_dir / "downloads" / f"{job_id}.transcript.txt"
    temp = output.with_name("." + output.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        stream.write(text + "\n")
    os.replace(temp, output)
    return {
        "ok": True, "job_id": job_id, "transcript_filename": output.name,
        "characters": len(text), "elapsed_seconds": round(time.monotonic() - start, 1),
    }


def run_once(data_dir: Path, transcribe: Callable[[Path, str], str] = default_transcriber) -> bool:
    queue = data_dir / "transcription_queue"
    queue.mkdir(parents=True, exist_ok=True)
    os.chmod(queue, 0o700)
    items = sorted(queue.glob("wxv_*.processing.json")) + sorted(queue.glob("wxv_*.request.json"))
    for item in items:
        match = re.fullmatch(r"(wxv_\d{6})\.(?:request|processing)\.json", item.name)
        if not match or item.is_symlink():
            continue
        jid = match[1]
        claimed = queue / f"{jid}.processing.json"
        result_file = queue / f"{jid}.result.json"
        if result_file.is_file():
            item.unlink(missing_ok=True)
            continue
        if item != claimed:
            try:
                os.replace(item, claimed)
            except FileNotFoundError:
                continue
        try:
            data = json.loads(claimed.read_text("utf-8"))
            if data.get("job_id") != jid:
                raise ValueError("JOB_ID_MISMATCH")
            result = process_request(data_dir, data, transcribe)
        except Exception as exc:
            reason = str(exc)
            code = reason if reason in {
                "INVALID_VIDEO_FILENAME", "VIDEO_NOT_FOUND", "UNSAFE_VIDEO_PATH",
                "INVALID_MEDIA", "INVALID_JOB_ID", "JOB_ID_MISMATCH",
                "MODEL_NOT_ALLOWED", "UNKNOWN_WHISPER_MODEL",
                "WHISPER_MODEL_NOT_CACHED", "TRANSCRIPT_EMPTY",
            } else "TRANSCRIPTION_FAILED"
            result = {"ok": False, "job_id": jid, "error_code": code}
        atomic_json(result_file, result)
        claimed.unlink(missing_ok=True)
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--model", choices=["base","small","medium","turbo"], default="base")
    args = parser.parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve(strict=True)
    if not (data_dir / "downloads").is_dir():
        raise SystemExit("Invalid WechatVideoDL data directory")
    queue = data_dir / "transcription_queue"
    queue.mkdir(mode=0o700, exist_ok=True)
    os.chmod(queue, 0o700)
    if args.once:
        run_once(data_dir)
        return
    stop = threading.Event()
    def heartbeat():
        while not stop.is_set():
            atomic_json(queue / "worker.status.json", {
                "ready": True, "at": time.time(), "model": args.model, "pid": os.getpid(),
            })
            stop.wait(3)
    threading.Thread(target=heartbeat, daemon=True, name="transcriber-heartbeat").start()
    try:
        while True:
            if not run_once(data_dir):
                time.sleep(3)
    finally:
        stop.set()


if __name__ == "__main__":
    main()
