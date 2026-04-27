from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp
import os

app = FastAPI(title="Super Media Downloader API")

class URLRequest(BaseModel):
    url: str

@app.get("/")
async def root():
    # Also report whether curl_cffi is available
    try:
        import curl_cffi
        cffi_version = curl_cffi.__version__
    except ImportError:
        cffi_version = "NOT INSTALLED"
    return {"status": "online", "curl_cffi": cffi_version, "yt_dlp": yt_dlp.version.__version__}

def get_info(url: str, use_impersonate: bool):
    cookie_path = "cookies.txt"
    opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
        },
    }
    if use_impersonate:
        opts['impersonate'] = 'chrome'

    if os.path.exists(cookie_path):
        opts['cookiefile'] = cookie_path

    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


@app.post("/api/download")
async def download_media(request: URLRequest):
    url = request.url
    info = None
    last_error = ""

    for use_impersonate in [True, False]:
        try:
            info = get_info(url, use_impersonate)
            break
        except Exception as e:
            last_error = str(e)
            # Always try without impersonate as fallback
            continue

    if not info:
        raise HTTPException(status_code=400, detail=last_error)

    video_url = info.get('url')
    formats = info.get('formats', [])
    audio_streams = [
        f for f in formats
        if f.get('vcodec') == 'none' and f.get('acodec') != 'none'
    ]

    if audio_streams:
        best_audio = sorted(audio_streams, key=lambda x: x.get('abr', 0), reverse=True)[0]
        audio_url = best_audio.get('url')
    else:
        audio_url = video_url

    return {
        "success": True,
        "data": {
            "title": info.get('title', 'Video'),
            "platform": info.get('extractor_key'),
            "video_url_720p": video_url,
            "audio_mp3_url": audio_url,
            "thumbnail": info.get('thumbnail'),
        }
    }
