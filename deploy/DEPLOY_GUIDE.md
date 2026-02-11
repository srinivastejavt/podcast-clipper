# 🚀 Deploy Podcast Clipper to Google Cloud (FREE)

## V2 Pipeline Features (New!)

The bot now uses a **multi-dimensional scoring system** for better clip selection:

- **7-dimension scoring**: hook, novelty, opinion, value density, shareability, context completeness, persona fit
- **Video Maps**: Speaker-grounded timeline with chapters, claims, and evidence tracking
- **2-stage selection**: Find 20-40 candidates → Deep score → Select top 2 per video
- **Diversity constraints**: Max 2 clips per video, 8+ minutes apart, different topics
- **Clip rationale**: See exactly WHY each clip was selected or rejected

---

## Prerequisites
- Google account
- Credit card (for verification only - won't be charged for free tier)

---

## Step 1: Create Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click "Select a project" → "New Project"
3. Name it: `podcast-clipper-bot`
4. Click "Create"

---

## Step 2: Enable Billing (Required but FREE)

1. Go to [Billing](https://console.cloud.google.com/billing)
2. Link a billing account (you get $300 free credits)
3. The free tier VM won't use these credits - it's always free!

---

## Step 3: Install Google Cloud CLI (on your Mac)

```bash
# Install gcloud CLI
brew install google-cloud-sdk

# Login
gcloud auth login

# Set project
gcloud config set project podcast-clipper-bot
```

---

## Step 4: Create the Free VM

```bash
# Create e2-micro instance (FREE tier)
gcloud compute instances create podcast-bot \
    --zone=us-central1-a \
    --machine-type=e2-micro \
    --image-family=ubuntu-2204-lts \
    --image-project=ubuntu-os-cloud \
    --boot-disk-size=30GB \
    --boot-disk-type=pd-standard
```

---

## Step 5: Setup the Bot on VM

```bash
# SSH into VM
gcloud compute ssh podcast-bot --zone=us-central1-a
```

Then run these commands on the VM:

```bash
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

# Pull the LLM model (this takes a few minutes)
ollama pull llama3.1:8b

# Exit SSH
exit
```

---

## Step 6: Copy Your Project to VM

From your Mac:

```bash
# Copy project files
gcloud compute scp --recurse ~/podcast_writer podcast-bot:~/ --zone=us-central1-a
```

---

## Step 7: Setup Python Environment on VM

```bash
# SSH back in
gcloud compute ssh podcast-bot --zone=us-central1-a

# Setup venv
cd ~/podcast_writer
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Step 8: Create Systemd Service (Auto-restart)

```bash
# Create service file
sudo nano /etc/systemd/system/podcast-bot.service
```

Paste this content:

```ini
[Unit]
Description=Podcast Clipper Bot
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/podcast_writer
Environment=PATH=/home/YOUR_USERNAME/podcast_writer/venv/bin:/usr/bin:/bin
ExecStart=/home/YOUR_USERNAME/podcast_writer/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Replace `YOUR_USERNAME` with your actual username (run `whoami` to find it).

Then enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable podcast-bot
sudo systemctl start podcast-bot
```

---

## Step 9: Verify It's Running

```bash
# Check status
sudo systemctl status podcast-bot

# View logs
journalctl -u podcast-bot -f
```

---

## 📋 Useful Commands

| Action | Command |
|--------|---------|
| SSH into VM | `gcloud compute ssh podcast-bot --zone=us-central1-a` |
| View logs | `journalctl -u podcast-bot -f` |
| Restart bot | `sudo systemctl restart podcast-bot` |
| Stop bot | `sudo systemctl stop podcast-bot` |
| Check status | `sudo systemctl status podcast-bot` |

---

## ⚠️ Important Notes

1. **e2-micro limitations**: 1GB RAM, 2 shared vCPUs
   - Whisper transcription will be slower than on your Mac
   - Consider using a smaller Whisper model if needed

2. **Free tier rules**:
   - Only in US regions (us-west1, us-central1, us-east1)
   - 1 GB egress/month (should be plenty for Telegram)
   - 30 GB disk max

3. **Alternative for heavy processing**:
   - Keep transcription on your Mac
   - Use VM only for Telegram bot + scheduling
   - Or use cloud transcription APIs (Whisper API, AssemblyAI)

---

## 💡 Pro Tips

1. **Set up swap** (helps with 1GB RAM):
   ```bash
   sudo fallocate -l 2G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
   ```

2. **Monitor usage**:
   - Go to [Cloud Console](https://console.cloud.google.com/compute)
   - Check CPU/Memory usage
   - Set up billing alerts (just in case)

3. **Keep costs at $0**:
   - Don't upgrade machine type
   - Stay in US regions
   - Monitor egress bandwidth
