#!/bin/bash
# Google Cloud Deployment Script for Podcast Clipper
# Run this AFTER creating a GCP project and enabling billing

set -e

# Configuration
PROJECT_ID="podcast-clipper-bot"
ZONE="us-central1-a"
INSTANCE_NAME="podcast-bot"
MACHINE_TYPE="e2-micro"

echo "🚀 Setting up Google Cloud for Podcast Clipper..."

# Create the VM
echo "📦 Creating VM instance..."
gcloud compute instances create $INSTANCE_NAME \
    --project=$PROJECT_ID \
    --zone=$ZONE \
    --machine-type=$MACHINE_TYPE \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard \
    --tags=http-server,https-server

echo "✅ VM created!"

# Wait for VM to be ready
echo "⏳ Waiting for VM to be ready..."
sleep 30

# Copy project files to VM
echo "📤 Copying project files..."
gcloud compute scp --recurse --zone=$ZONE \
    ~/podcast_writer $INSTANCE_NAME:~/

# SSH and setup
echo "🔧 Setting up the bot on VM..."
gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command="
    # Update system
    sudo apt-get update && sudo apt-get upgrade -y

    # Install Python 3.11
    sudo apt-get install -y software-properties-common
    sudo add-apt-repository -y ppa:deadsnakes/ppa
    sudo apt-get update
    sudo apt-get install -y python3.11 python3.11-venv python3.11-dev

    # Install ffmpeg
    sudo apt-get install -y ffmpeg

    # Install Ollama
    curl -fsSL https://ollama.com/install.sh | sh

    # Pull the model
    ollama pull llama3.1:8b

    # Setup project
    cd ~/podcast_writer
    python3.11 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt

    # Create systemd service
    sudo tee /etc/systemd/system/podcast-bot.service > /dev/null << 'EOF'
[Unit]
Description=Podcast Clipper Bot
After=network.target ollama.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/podcast_writer
Environment=PATH=/home/$USER/podcast_writer/venv/bin:/usr/bin:/bin
ExecStart=/home/$USER/podcast_writer/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Enable and start service
    sudo systemctl daemon-reload
    sudo systemctl enable podcast-bot
    sudo systemctl start podcast-bot

    echo '✅ Bot is now running!'
"

echo ""
echo "🎉 Deployment complete!"
echo ""
echo "Useful commands:"
echo "  SSH into VM:     gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo "  View logs:       gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='journalctl -u podcast-bot -f'"
echo "  Restart bot:     gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo systemctl restart podcast-bot'"
echo "  Stop bot:        gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --command='sudo systemctl stop podcast-bot'"
