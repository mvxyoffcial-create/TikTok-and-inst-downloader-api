import asyncio
import os
import tempfile
import subprocess
from typing import Optional, Dict, Any

from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from starlette.background import BackgroundTask
import yt_dlp
import uvicorn

app = FastAPI(title="TikTok & Instagram Downloader – Single Endpoint")


def extract_info(url: str) -> Dict[str, Any]:
    """Extract media info without downloading."""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # Uncomment and add your cookies file if needed:
        # 'cookiefile': 'cookies.txt',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def select_best_formats(info: dict, preferred_height: int = 720) -> tuple:
    """
    Pick the best video and audio streams targeting the preferred height.
    Returns (video_url, audio_url, thumbnail).
    """
    thumbnail = info.get('thumbnail')
    formats = info.get('formats', [])
    if not formats:
        # Fallback for platforms like TikTok that may put the direct URL in root
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

    # 1) Combined stream closest to preferred height
    best_combined = None
    if combined:
        combined.sort(key=lambda f: (
            abs(f.get('height', 0) - preferred_height) if f.get('height') else 9999,
            -f.get('height', 0)
        ))
        best_combined = combined[0]

    # 2) Video‑only stream closest to preferred height
    video_only.sort(key=lambda f: (
        abs(f.get('height', 0) - preferred_height) if f.get('height') else 9999,
        -f.get('height', 0)
    ))
    best_video = video_only[0] if video_only else None

    # 3) Best audio stream (highest bitrate)
    audio_only.sort(key=lambda f: f.get('abr', 0), reverse=True)
    best_audio = audio_only[0] if audio_only else None

    if best_combined:
        video_url = best_combined['url']
        audio_url = None  # combined stream already contains audio
    elif best_video:
        video_url = best_video['url']
        audio_url = best_audio['url'] if best_audio else None
    else:
        video_url = None
        audio_url = best_audio['url'] if best_audio else None

    return video_url, audio_url, thumbnail


def convert_to_mp3(input_url: str) -> str:
    """Download audio from URL and convert to MP3 using FFmpeg.
    Returns path to temporary MP3 file."""
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


@app.get("/download")
async def get_everything(
    request: Request,
    url: str = Query(..., description="TikTok or Instagram post/story/video URL"),
    quality: int = Query(720, description="Preferred video height (e.g., 720, 1080)")
):
    """
    The **only endpoint you need**.  
    Returns:
    - `video_url` – direct link to the 720p (or chosen quality) video file.
    - `mp3_url` – link to download the MP3 audio (converted on‑the‑fly).
    - `thumbnail` – image URL.
    - Full metadata (title, uploader, duration, etc.)
    """
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")

    video_url, audio_url, thumbnail = select_best_formats(info, preferred_height=quality)

    # Build the absolute URL for the MP3 download
    mp3_download_url = None
    if audio_url:
        # Use request.base_url to make it absolute
        base = str(request.base_url).rstrip("/")
        mp3_download_url = f"{base}/download-audio?url={request.url.query.split('&url=')[-1].split('&')[0]}"  # careful: better to encode properly
        # Simpler: pass the original url param to the mp3 endpoint
        from urllib.parse import quote
        mp3_download_url = f"{base}/download-audio?url={quote(url, safe='')}&quality={quality}"

    # Handle multi‑image posts (carousel) – we take the first media
    if info.get('_type') == 'playlist' and 'entries' in info:
        info = info['entries'][0]  # use the first item for simplicity

    response = {
        "success": True,
        "platform": info.get('extractor_key', 'unknown'),
        "title": info.get('title'),
        "description": info.get('description'),
        "uploader": info.get('uploader'),
        "duration": info.get('duration'),
        "thumbnail": thumbnail,
        "video_url": video_url,
        "mp3_url": mp3_download_url,
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
    url: str = Query(..., description="Original media URL (same as passed to /download)"),
    quality: int = Query(720)
):
    """
    Internal endpoint – converts the best audio stream to MP3 and serves the file.
    Called automatically by the `mp3_url` returned from /download.
    """
    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract_info, url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract info: {str(e)}")

    _, audio_url, _ = select_best_formats(info, preferred_height=quality)
    if not audio_url:
        raise HTTPException(status_code=404, detail="No audio stream found for this media.")

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
