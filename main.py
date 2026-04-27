from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yt_dlp

app = FastAPI(title="Super Media Downloader API")

class URLRequest(BaseModel):
    url: str

@app.post("/api/download")
async def download_media(request: URLRequest):
    url = request.url
    
    # Configure yt-dlp to extract data without downloading the file locally
    ydl_opts = {
        'format': 'best', # Gets the best quality video/audio combined
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract information from the link
            info = ydl.extract_info(url, download=False)
            
            # Prepare the response payload
            response_data = {
                "title": info.get('title', 'Unknown Title'),
                "platform": info.get('extractor_key', 'Unknown'),
                "thumbnail": info.get('thumbnail'),
                "description": info.get('description'),
                "duration": info.get('duration'),
                "media": {}
            }

            # Get the direct video URL (MP4)
            if 'url' in info:
                response_data["media"]["video_url"] = info['url']
            
            # Extract Audio (MP3) URL if available in the formats
            # Note: Many platforms mix audio and video. This looks for the best audio stream.
            formats = info.get('formats', [])
            audio_url = None
            for f in formats:
                if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                    audio_url = f.get('url')
                    break # Found an audio-only stream
            
            if audio_url:
                response_data["media"]["audio_mp3_url"] = audio_url
            else:
                response_data["media"]["audio_mp3_url"] = "Audio extraction not supported for this specific link format."

            return {
                "success": True,
                "data": response_data
            }

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Could not extract media: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# To run this server, use the command:
# uvicorn main:app --reload

