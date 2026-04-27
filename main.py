import asyncio
import os
import tempfile
import subprocess
from typing import Dict, Any
from urllib.parse import quote

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
import yt_dlp
import uvicorn

app = FastAPI(title="TikTok & Instagram Downloader – Single Endpoint")

# ✅ Enable CORS for all origins (adjust as needed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],          # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],          # Allows all headers
)

# ---------- Helper functions (unchanged) ----------
def extract_info(url: str) -> Dict[str, Any]:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # 'cookiefile': 'cookies.txt',  # if needed
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def select_best_formats(info: dict, preferred_height: int = 720) -> tuple:
    thumbnail = info.get('thumbnail')
    formats = info.get('formats', [])
    if not formats:
        return info.get('url'), None, thumbnail

    combined = []
    video_only = []
    audio_only = []
    for f in formats:
        if f.get('vcodec') != 'none' and f.get('acodec') != 'none':
            combined.append(f)
        elif f.get('vcodec') != 'none':
            video_only.append(f)
        elif f.get('acodec') != 'none':
            audio_only.append(f)

    best_combined = None
    if combined:
        combined.sort(key=lambda f: (
            abs(f.get('height', 0) - preferred_height) if f.get('height') else 9999,
            -f.get('height', 0)
        ))
        best_combined = combined[0]

    video_only.sort(key=lambda f: (
        abs(f.get('height', 0) - preferred_height) if f.get('height') else 9999,
        -f.get('height', 0)
    ))
    best_video = video_only[0] if video_only else None

    audio_only.sort(key=lambda f: f.get('abr', 0), reverse=True)
    best_audio = audio_only[0] if audio_only else None

    if best_combined:
        video_url = best_combined['url']
        audio_url = None
    elif best_video:
        video_url = best_video['url']
        audio_url = best_audio['url'] if best_audio else None
    else:
        video_url = None
        audio_url = best_audio['url'] if best_audio else None

    return video_url, audio_url, thumbnail

def convert_to_mp3(input_url: str) -> str:
    tmp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_mp3.close()
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", input_url,
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            tmp_mp3.name
        ], check=True, capture_output=True)
        return tmp_mp3.name
    except subprocess.CalledProcessError as e:
        if os.path.exists(tmp_mp3.name):
            os.unlink(tmp_mp3.name)
        raise RuntimeError(f"FFmpeg conversion failed: {e.stderr.decode()}") from e

# ---------- Endpoints ----------
@app.get("/download")
async def get_everything(
    request: Request,
    url: str = Query(..., description="TikTok or Instagram post/story/video URL"),
    quality: int = Query(720, description="Preferred video height (e.g., 720, 1080)")
):
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")

    video_url, audio_url, thumbnail = select_best_formats(info, preferred_height=quality)

    # Build absolute MP3 download URL
    mp3_url = None
    if audio_url:
        base = str(request.base_url).rstrip("/")
        mp3_url = f"{base}/download-audio?url={quote(url, safe='')}&quality={quality}"

    # Handle carousels – use first media
    if info.get('_type') == 'playlist' and 'entries' in info:
        info = info['entries'][0]

    response = {
        "success": True,
        "platform": info.get('extractor_key', 'unknown'),
        "title": info.get('title'),
        "description": info.get('description'),
        "uploader": info.get('uploader'),
        "duration": info.get('duration'),
        "thumbnail": thumbnail,
        "video_url": video_url,
        "mp3_url": mp3_url,
        "formats_available": [
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "height": f.get("height"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "filesize": f.get("filesize"),
            }
            for f in info.get("formats", [])
        ] if info.get("formats") else None,
    }
    return JSONResponse(content=response)

@app.get("/download-audio")
async def serve_mp3(
    url: str = Query(...),
    quality: int = Query(720)
):
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")

    _, audio_url, _ = select_best_formats(info, preferred_height=quality)
    if not audio_url:
        raise HTTPException(status_code=404, detail="No audio stream found.")

    try:
        mp3_path = await loop.run_in_executor(None, convert_to_mp3, audio_url)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    def cleanup():
        if os.path.exists(mp3_path):
            os.unlink(mp3_path)

    return FileResponse(
        mp3_path,
        media_type="audio/mpeg",
        filename=f"{info.get('title', 'audio')}.mp3",
        background=BackgroundTask(cleanup)
    )

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
