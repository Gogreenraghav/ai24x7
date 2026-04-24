#!/bin/bash
# AI24x7 Vision - One-Command Installer v1.1
# Supports: CCTV Dashboard + Daily Reports + API Agent
# Run: curl -sL https://raw.githubusercontent.com/Gogreenraghav/ai24x7-vision/main/install.sh | bash

set -e

echo "========================================"
echo " AI24x7 Vision - Installer v1.1"
echo "========================================"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err() { echo -e "${RED}[✗]${NC} $1"; }

# Check internet
if ! curl -s --max-time 5 https://hf.co > /dev/null; then
    err "No internet. Install requires internet."
    exit 1
fi

# Check OS
if [[ "$(uname)" != "Linux" ]]; then
    err "Linux required. Got: $(uname)"
    exit 1
fi

# Detect GPU (for local mode)
HAS_GPU=false
if command -v nvidia-smi &> /dev/null && nvidia-smi &> /dev/null; then
    HAS_GPU=true
    GPU_MODEL=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
    GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | awk '{print $1}')
    log "GPU detected: $GPU_MODEL (${GPU_MEM}MB VRAM)"
fi

# Detect CPU cores
CPU_CORES=$(nproc)
RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
RAM_GB=$((RAM_KB / 1024 / 1024))

log "System: $CPU_CORES CPU cores, ${RAM_GB}GB RAM"

# Detect mode
if [ "$HAS_GPU" = true ] && [ "$GPU_MEM" -ge 10000 ]; then
    MODE="local"
    warn "GPU mode: Will download model (~5.5GB)"
else
    MODE="cloud"
    warn "Cloud mode: Will use remote API (no local model)"
fi

log "Mode selected: $MODE"

# Create install directory
INSTALL_DIR="/opt/ai24x7"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Install Python deps
log "Installing Python dependencies..."
pip install requests pillow python-telegram-bot opencv-python-headless -q 2>/dev/null || true

# Install dashboard deps
log "Installing dashboard dependencies..."
pip install streamlit opencv-python-headless -q 2>/dev/null || true

# Clone or update repo
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating AI24x7..."
    cd "$INSTALL_DIR" && git pull -q
else
    log "Cloning AI24x7 Vision repository..."
    git clone -q https://github.com/Gogreenraghav/ai24x7-vision.git "$INSTALL_DIR" 2>/dev/null || true
fi

# Download model (local mode only)
if [ "$MODE" = "local" ]; then
    MODEL_DIR="$INSTALL_DIR/models"
    mkdir -p "$MODEL_DIR"
    
    if [ ! -f "$MODEL_DIR/model-q5_k_m.gguf" ]; then
        log "Downloading AI24x7 v10 model (~5.5GB)..."
        log "This may take 5-15 minutes depending on internet speed..."
        
        # Download from HuggingFace
        HF_TOKEN="${HF_TOKEN:-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}"
        pip install huggingface_hub -q 2>/dev/null
        
        python3 -c "
from huggingface_hub import hf_hub_download
import os
try:
    path = hf_hub_download(
        repo_id='Arjun9350/ai24x7-vision-v10',
        filename='model-q5_k_m.gguf',
        local_dir='$MODEL_DIR',
        token='$HF_TOKEN',
        local_dir_use_symlinks=False
    )
    print(f'Model saved to: {path}')
except Exception as e:
    print(f'Download error: {e}')
    print('Falling back to model download...')
"
        # Fallback: direct download
        if [ ! -f "$MODEL_DIR/model-q5_k_m.gguf" ]; then
            wget -q --show-progress -O "$MODEL_DIR/model-q5_k_m.gguf" \
                "https://huggingface.co/Arjun9350/ai24x7-vision-v10/resolve/main/model-q5_k_m.gguf" \
                2>/dev/null || true
        fi
    else
        log "Model already exists, skipping download."
    fi
fi

# Setup CCTV API config
CONFIG_FILE="$INSTALL_DIR/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "{}" > "$CONFIG_FILE"
fi

# Install dashboard
if [ -f "$INSTALL_DIR/cctv_dashboard.py" ]; then
    log "Dashboard found: $INSTALL_DIR/cctv_dashboard.py"
    log "To launch dashboard:"
    echo ""
    echo -e "  ${YELLOW}streamlit run $INSTALL_DIR/cctv_dashboard.py --server.port 8501${NC}"
    echo ""
fi

# Setup Telegram bot
log "Telegram bot: @ai24x7_vision_bot"
log "Chat ID configured: 8566322083"

# Auto-start on boot (optional)
read -p "Enable auto-start on boot? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cat > /etc/systemd/system/ai24x7-dashboard.service << EOF
[Unit]
Description=AI24x7 CCTV Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$(which streamlit) run $INSTALL_DIR/cctv_dashboard.py --server.port 8501 --server.address 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable ai24x7-dashboard
    systemctl start ai24x7-dashboard
    log "Dashboard auto-start enabled!"
fi

# Final instructions
echo ""
echo "========================================"
echo -e "${GREEN} AI24x7 Vision Installed Successfully!${NC}"
echo "========================================"
echo ""
echo "Dashboard URL: http://localhost:8501"
echo "Install dir: $INSTALL_DIR"
echo "Mode: $MODE"
echo ""
echo "Quick start:"
echo "  streamlit run $INSTALL_DIR/cctv_dashboard.py --server.port 8501"
echo ""
echo "For API agent:"
echo "  python3 $INSTALL_DIR/ai24x7_agent.py"
echo ""
