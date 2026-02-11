#!/bin/bash

# Podcast Clipper Setup Script

echo "🎙️ Setting up Podcast Clipper..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "⚠️ Ollama not found. Installing..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

# Check if yt-dlp is installed
if ! command -v yt-dlp &> /dev/null; then
    echo "📦 Installing yt-dlp..."
    pip3 install yt-dlp
fi

# Check if ffmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "⚠️ ffmpeg not found. Please install it:"
    echo "  macOS: brew install ffmpeg"
    echo "  Ubuntu: sudo apt install ffmpeg"
    exit 1
fi

# Create virtual environment
echo "🐍 Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies
echo "📦 Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p data/clips data/transcripts data/temp_videos data/logs

# Pull Ollama model
echo "🤖 Pulling Llama 3.1 model (this may take a while)..."
ollama pull llama3.1:8b

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Make sure Ollama is running: ollama serve"
echo "2. Start the bot: python main.py"
echo "3. Open Telegram and message your bot to subscribe"
echo "4. Or test with a single video: python test_single_video.py <youtube_url>"
echo ""
