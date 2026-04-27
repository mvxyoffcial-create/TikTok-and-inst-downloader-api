from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp
import os

app = FastAPI(title="Super Media Downloader API")

class URLRequest(BaseModel):
    url: str

@app.get("/")
async def root():
    return {"status": "online", "message": "API is live. Use /api/download"}

@app.post("/api/download")
async def download_media(request: URLRequest):
    url = request.url
    
    # Path to cookies file (explained in Step 2)
    cookie_path = "cookies.txt"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'format': 'best',
        # Bypass blocks with headers
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Origin': 'https://www.instagram.com',
            'Referer': 'https://www.instagram.com/',
        }
    }

    # If you uploaded a cookies.txt, use it automatically
    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # 1. Get the Best Video URL
            video_url = info.get('url')
            
            # 2. Extract the Best Audio URL (MP3)
            # We look for the best quality audio-only stream
            formats = info.get('formats', [])
            audio_url = None
            
            # Filter for audio-only streams
            audio_streams = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
            if audio_streams:
                # Sort by bitrate to get best quality
                best_audio = sorted(audio_streams, key=lambda x: x.get('abr', 0), reverse=True)[0]
                audio_url = best_audio.get('url')
            else:
                # Fallback to the main URL if no separate audio found
                audio_url = video_url

            return {
                "success": True,
                "data": {
                    "title": info.get('title', 'Media'),
                    "platform": info.get('extractor_key'),
                    "thumbnail": info.get('thumbnail'),
                    "video_url": video_url,
                    "audio_url": audio_url
                }
            }

    except Exception as e:
        # Better error reporting
        error_str = str(e)
        if "login" in error_str.lower() or "empty media" in error_str.lower():
            raise HTTPException(status_code=403, detail="Instagram login required. Please update cookies.txt.")
        raise HTTPException(status_code=400, detail=error_str)
