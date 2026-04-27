FROM python:3.10-slim

# Install FFmpeg - THIS IS THE CRITICAL STEP
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn yt-dlp
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
