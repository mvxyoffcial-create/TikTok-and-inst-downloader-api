import asyncio
import os
import tempfile
import subprocess
from typing import Dict, Any, Optional
from urllib.parse import quote

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
import yt_dlp
import httpx
import uvicorn

app = FastAPI(title="TikTok & Instagram Downloader – Fixed")

# CORS – adjust in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Cookie loading ──────────────────────────────
def get_cookie_path() -> Optional[str]:
    """Return the path to the cookies.txt file if it exists."""
    # You can also use an environment variable: return os.getenv('COOKIE_TXT', 'cookies.txt')
    if os.path.exists('cookies.txt'):
        return 'cookies.txt'
    return None

# ── yt-dlp helpers ──────────────────────────────
def extract_info(url: str) -> Dict[str, Any]:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # Add cookies if available
        'cookiefile': get_cookie_path(),
        # Use a common User-Agent to mimic a browser
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        },
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

    # Combined stream closest to preferred height
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


async def proxy_file(url: str, referer: str, media_type: str):
    """Stream a file from an upstream URL with proper headers, bypassing CDN blocks."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': referer,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream('GET', url, headers=headers) as upstream:
            async def stream():
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            return StreamingResponse(stream(), media_type=media_type)

# ── MP3 conversion ──────────────────────────────
def convert_to_mp3(input_url: str, referer: str) -> str:
    tmp_mp3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_mp3.close()
    try:
        subprocess.run([
            "ffmpeg", "-y",
            "-headers", f"Referer: {referer}",
            "-i", input_url,
            "-codec:a", "libmp3lame", "-qscale:a", "2",
            tmp_mp3.name
        ], check=True, capture_output=True)
        return tmp_mp3.name
    except subprocess.CalledProcessError as e:
        if os.path.exists(tmp_mp3.name):
            os.unlink(tmp_mp3.name)
        raise RuntimeError(f"FFmpeg conversion failed: {e.stderr.decode()}") from e


# ── Endpoint 1: Get all info + proxy links ─────
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

    # Handle Instagram carousels (multi-image) – return first entry
    if info.get('_type') == 'playlist' and 'entries' in info:
        info = info['entries'][0]

    platform = info.get('extractor_key', 'unknown')
    referer = f"https://www.{platform}.com/"

    # Build proxied download links (hide raw CDN URLs)
    base = str(request.base_url).rstrip("/")
    proxy_video_url = f"{base}/proxy-video?url={quote(video_url)}&referer={quote(referer)}" if video_url else None
    proxy_audio_url = None
    if audio_url:
        proxy_audio_url = f"{base}/proxy-audio?url={quote(audio_url)}&referer={quote(referer)}&quality={quality}&original_url={quote(url)}"

    response = {
        "success": True,
        "platform": platform,
        "title": info.get('title'),
        "description": info.get('description'),
        "uploader": info.get('uploader'),
        "duration": info.get('duration'),
        "thumbnail": thumbnail,
        # These links will work because they stream through YOUR server with proper headers
        "video_url": proxy_video_url,
        "mp3_url": proxy_audio_url,
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


# ── Endpoint 2: Proxy video download ──────────
@app.get("/proxy-video")
async def proxy_video(
    url: str = Query(...),
    referer: str = Query(...)
):
    return await proxy_file(url, referer, "video/mp4")


# ── Endpoint 3: Proxy audio download (MP3) ────
@app.get("/proxy-audio")
async def proxy_audio(
    url: str = Query(...),
    referer: str = Query(...),
    quality: int = Query(720),
    original_url: str = Query(...)
):
    try:
        loop = asyncio.get_event_loop()
        mp3_path = await loop.run_in_executor(None, convert_to_mp3, url, referer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    def cleanup():
        if os.path.exists(mp3_path):
            os.unlink(mp3_path)

    return FileResponse(
        mp3_path,
        media_type="audio/mpeg",
        filename=f"audio.mp3",
        background=BackgroundTask(cleanup)
    )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
