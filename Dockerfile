FROM python:3.11-slim

# Install FFmpeg with font support for subtitles
RUN apt-get update && \
    apt-get install -y ffmpeg fonts-freefont-ttf && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .

CMD ["python", "bot.py"]
