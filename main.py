from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
import asyncio

app = FastAPI(title="Super Media Downloader API")

DOWNLOAD_DIR = "/tmp/downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

class URLRequest(BaseModel):
    url: str

@app.get("/")
async def root():
    try:
        import curl_cffi
        cffi_version = curl_cffi.__version__
    except ImportError:
        cffi_version = "NOT INSTALLED"
    return {"status": "online", "curl_cffi": cffi_version, "yt_dlp": yt_dlp.version.__version__}


def process(url: str) -> dict:
    file_id = str(uuid.uuid4())
    cookie_path = "cookies.txt"

    base_opts = {
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
        },
    }
    if os.path.exists(cookie_path):
        base_opts['cookiefile'] = cookie_path

    # ── Step 1: Download VIDEO ──────────────────────────────────────────────
    video_path = None
    video_opts = {
        **base_opts,
        'format': 'best[height<=720]/best',
        'merge_output_format': 'mp4',
        'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_id}_video.%(ext)s"),
    }

    info = None
    last_error = ""
    for use_imp in [True, False]:
        try:
            if use_imp:
                video_opts['impersonate'] = 'chrome'
            else:
                video_opts.pop('impersonate', None)
            with yt_dlp.YoutubeDL(video_opts) as ydl:
                info = ydl.extract_info(url, download=True)
            # find downloaded video file
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(f"{file_id}_video"):
                    video_path = os.path.join(DOWNLOAD_DIR, f)
                    break
            if video_path:
                break
        except Exception as e:
            last_error = str(e)
            continue

    if not video_path or not info:
        raise Exception(f"Video download failed: {last_error}")

    # ── Step 2: Download AUDIO (mp3) ────────────────────────────────────────
    audio_path = None
    audio_opts = {
        **base_opts,
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, f"{file_id}_audio.%(ext)s"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }

    for use_imp in [True, False]:
        try:
            if use_imp:
                audio_opts['impersonate'] = 'chrome'
            else:
                audio_opts.pop('impersonate', None)
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                ydl.extract_info(url, download=True)
            audio_file = os.path.join(DOWNLOAD_DIR, f"{file_id}_audio.mp3")
            if os.path.exists(audio_file):
                audio_path = audio_file
                break
            # fallback search
            for f in os.listdir(DOWNLOAD_DIR):
                if f.startswith(f"{file_id}_audio"):
                    audio_path = os.path.join(DOWNLOAD_DIR, f)
                    break
            if audio_path:
                break
        except Exception as e:
            last_error = str(e)
            continue

    return {
        "file_id": file_id,
        "title": info.get("title", "Video"),
        "platform": info.get("extractor_key", "unknown"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "video_path": video_path,
        "audio_path": audio_path,
    }


# In-memory store for processed results
_cache: dict = {}


@app.post("/api/download")
async def download_endpoint(request: URLRequest):
    """
    Single endpoint — returns info + download links for video and audio.
    """
    url = request.url
    try:
        result = await asyncio.to_thread(process, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    fid = result["file_id"]
    _cache[fid] = result

    base_url = f"/api/file/{fid}"

    return {
        "success": True,
        "info": {
            "title": result["title"],
            "platform": result["platform"],
            "duration": result["duration"],
            "thumbnail": result["thumbnail"],
            "uploader": result["uploader"],
        },
        "video_url": f"{base_url}/video",
        "audio_url": f"{base_url}/audio" if result["audio_path"] else None,
    }


@app.get("/api/file/{file_id}/video")
async def serve_video(file_id: str):
    entry = _cache.get(file_id)
    if not entry or not entry.get("video_path"):
        raise HTTPException(status_code=404, detail="File not found or expired")
    path = entry["video_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File no longer on disk")
    ext = os.path.splitext(path)[1].lstrip(".")
    filename = f"{entry['title'][:60]}.{ext}".replace("/", "-")
    return FileResponse(path=path, media_type="video/mp4", filename=filename)


@app.get("/api/file/{file_id}/audio")
async def serve_audio(file_id: str):
    entry = _cache.get(file_id)
    if not entry or not entry.get("audio_path"):
        raise HTTPException(status_code=404, detail="Audio not found or expired")
    path = entry["audio_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File no longer on disk")
    filename = f"{entry['title'][:60]}.mp3".replace("/", "-")
    return FileResponse(path=path, media_type="audio/mpeg", filename=filename)
