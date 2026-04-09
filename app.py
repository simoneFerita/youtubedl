from __future__ import annotations
import os

import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from flask_cors import CORS
from flask import Flask, after_this_request, jsonify, render_template, request, send_file, send_from_directory

app = Flask(__name__)
CORS_ORIGINS = [item.strip() for item in os.getenv("YTDL_CORS_ORIGINS", "*").split(",") if item.strip()]
CORS(
    app,
    resources={
        r"/api/*": {"origins": CORS_ORIGINS},
        r"/youtubedl/api/*": {"origins": CORS_ORIGINS},
        r"/youtubedownload/api/*": {"origins": CORS_ORIGINS},
    },
)

SELECTOR_PATTERN = re.compile(r"^[A-Za-z0-9\+\-\/\.\,\[\]\(\):]+$")


def _is_valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _format_kind(fmt: dict) -> str:
    has_video = fmt.get("vcodec") != "none"
    has_audio = fmt.get("acodec") != "none"

    if has_video and has_audio:
        return "audio+video"
    if has_video:
        return "solo video"
    if has_audio:
        return "solo audio"
    return "altro"


def _resolution_label(fmt: dict) -> str:
    if fmt.get("vcodec") == "none":
        return "Solo audio"

    resolution = fmt.get("resolution")
    if resolution and resolution != "none":
        return resolution

    width = fmt.get("width")
    height = fmt.get("height")
    if width and height:
        return f"{width}x{height}"

    return "Video"


def _build_selector(fmt: dict) -> str:
    format_id = str(fmt.get("format_id"))
    kind = _format_kind(fmt)

    if kind == "solo video":
        return f"{format_id}+bestaudio/best"

    return format_id


def _extract_info(url: str) -> dict:
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if "entries" in info:
        entries = info.get("entries") or []
        if not entries:
            raise ValueError("Playlist vuota o non supportata.")
        info = entries[0]

    return info


def _serialized_formats(info: dict) -> list[dict]:
    available_formats: list[dict] = []

    for fmt in info.get("formats", []):
        if not fmt.get("format_id"):
            continue
        if fmt.get("vcodec") == "none" and fmt.get("acodec") == "none":
            continue

        available_formats.append(
            {
                "format_id": str(fmt.get("format_id")),
                "ext": fmt.get("ext") or "",
                "resolution": _resolution_label(fmt),
                "fps": fmt.get("fps") or 0,
                "filesize": fmt.get("filesize") or fmt.get("filesize_approx") or 0,
                "kind": _format_kind(fmt),
                "note": fmt.get("format_note") or "",
                "selector": _build_selector(fmt),
                "height": fmt.get("height") or 0,
                "abr": fmt.get("abr") or 0,
            }
        )

    available_formats.sort(
        key=lambda item: (
            item["kind"] != "solo audio",
            item["height"],
            item["fps"],
            item["abr"],
            item["filesize"],
        ),
        reverse=True,
    )

    return available_formats


def _pick_downloaded_file(temp_dir: Path, info: dict, ydl: yt_dlp.YoutubeDL) -> Path:
    prepared_name = Path(ydl.prepare_filename(info))
    if prepared_name.exists():
        return prepared_name

    for item in info.get("requested_downloads") or []:
        maybe_path = item.get("filepath")
        if maybe_path and Path(maybe_path).exists():
            return Path(maybe_path)

    produced_files = sorted(
        temp_dir.glob("*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not produced_files:
        raise FileNotFoundError("Nessun file scaricato.")

    return produced_files[0]


def _api_base_path() -> str:
    if request.path.startswith("/youtubedl"):
        return "/youtubedl"
    if request.path.startswith("/youtubedownload"):
        return "/youtubedownload"
    return ""


@app.get("/")
@app.get("/youtubedl")
@app.get("/youtubedownload")
def index():
    return render_template("index.html", api_base_path=_api_base_path())
@app.get("/youtubedl/static/<path:filename>")
@app.get("/youtubedownload/static/<path:filename>")
def static_alias(filename: str):
    return send_from_directory(app.static_folder, filename)


@app.post("/api/formats")
@app.post("/youtubedl/api/formats")
@app.post("/youtubedownload/api/formats")
def get_formats():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()

    if not _is_valid_url(url):
        return jsonify({"error": "Inserisci un URL valido (http/https)."}), 400

    try:
        info = _extract_info(url)
        return jsonify(
            {
                "title": info.get("title", "Senza titolo"),
                "formats": _serialized_formats(info),
            }
        )
    except Exception as exc:
        message = str(exc).strip().splitlines()[0]
        return jsonify({"error": f"Impossibile leggere i formati: {message}"}), 400


@app.post("/api/download")
@app.post("/youtubedl/api/download")
@app.post("/youtubedownload/api/download")
def download():
    payload = request.get_json(silent=True) or {}
    url = str(payload.get("url", "")).strip()
    selector = str(payload.get("selector", "")).strip()

    if not _is_valid_url(url):
        return jsonify({"error": "URL non valido."}), 400

    if not selector or not SELECTOR_PATTERN.fullmatch(selector):
        return jsonify({"error": "Formato selezionato non valido."}), 400

    temp_dir = Path(tempfile.mkdtemp(prefix="web_downloader_"))

    @after_this_request
    def cleanup(response):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return response

    try:
        ydl_opts = {
            "format": selector,
            "outtmpl": str(temp_dir / "%(title).120s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "merge_output_format": "mp4",
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

            if "entries" in info:
                entries = info.get("entries") or []
                if not entries:
                    raise ValueError("Nessun elemento scaricabile trovato.")
                info = entries[0]

            file_path = _pick_downloaded_file(temp_dir, info, ydl)

        return send_file(
            file_path,
            as_attachment=True,
            download_name=file_path.name,
        )
    except yt_dlp.utils.DownloadError as exc:
        message = str(exc).strip().splitlines()[0]
        return jsonify({"error": f"Errore download: {message}"}), 400
    except Exception as exc:
        message = str(exc).strip().splitlines()[0]
        return jsonify({"error": f"Errore interno: {message}"}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
