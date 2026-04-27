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
    cookie_path = "cookies.txt"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        # SET QUALITY TO 720P: This looks for the best video up to 720p + best audio
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
        
        # BYPASS 403: Mimic a real Chrome browser on Windows
        'impersonate': 'chrome', 
        
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Referer': 'https://www.tiktok.com/',
        }
    }

    if os.path.exists(cookie_path):
        ydl_opts['cookiefile'] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            
            # Format the response
            response_data = {
                "title": info.get('title', 'Media'),
                "platform": info.get('extractor_key'),
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration'),
                "media": {
                    "video_url_720p": None,
                    "audio_mp3_url": None
                }
            }

            # Get the direct Video link
            response_data["media"]["video_url_720p"] = info.get('url')

            # Extract the best Audio-only link (MP3)
            formats = info.get('formats', [])
            audio_streams = [f for f in formats if f.get('vcodec') == 'none' and f.get('acodec') != 'none']
            
            if audio_streams:
                # Sort by quality/bitrate
                best_audio = sorted(audio_streams, key=lambda x: x.get('abr', 0), reverse=True)[0]
                response_data["media"]["audio_mp3_url"] = best_audio.get('url')
            else:
                # Fallback if no separate audio stream is found
                response_data["media"]["audio_mp3_url"] = info.get('url')

            return {"success": True, "data": response_data}

    except Exception as e:
        error_msg = str(e)
        if "403" in error_msg or "Forbidden" in error_msg:
            raise HTTPException(status_code=403, detail="TikTok/Instagram blocked the server IP. Try using cookies.txt or a proxy.")
        raise HTTPException(status_code=400, detail=error_msg)
