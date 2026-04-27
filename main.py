from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp
import os

app = FastAPI(title="Super Media Downloader API")

class URLRequest(BaseModel):
    url: str

@app.get("/")
async def root():
    return {"status": "online"}

@app.post("/api/download")
async def download_media(request: URLRequest):
    url = request.url
    cookie_path = "cookies.txt"
    
    # Base options
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        # Default to 720p or best available below it
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        # Crucial for TikTok: mimic a real browser
        'impersonate': 'chrome',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.tiktok.com/',
        }
    }

    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 1. Extract information
            info = ydl.extract_info(url, download=False)
            
            # 2. Get Video Link (720p)
            video_url = info.get('url')
            
            # 3. Get Audio Link (Best Quality)
            formats = info.get('formats', [])
            audio_url = None
            audio_streams = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
            
            if audio_streams:
                # Get the highest bitrate audio
                best_audio = sorted(audio_streams, key=lambda x: x.get('abr', 0), reverse=True)[0]
                audio_url = best_audio.get('url')
            else:
                # If no separate audio, the video URL usually contains both
                audio_url = video_url

            return {
                "success": True,
                "data": {
                    "title": info.get('title', 'TikTok/Instagram Video'),
                    "platform": info.get('extractor_key'),
                    "video_url_720p": video_url,
                    "audio_mp3_url": audio_url,
                    "thumbnail": info.get('thumbnail')
                }
            }

    except Exception as e:
        error_msg = str(e)
        if "impersonate" in error_msg.lower():
            # Fallback if the server still fails to impersonate
            return {"success": False, "error": "Server dependency error. Please check Dockerfile libraries."}
        raise HTTPException(status_code=400, detail=error_msg)
