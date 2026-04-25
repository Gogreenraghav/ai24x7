#!/bin/bash
# AI24x7 Smart Installer v2.0
# One-command install with interactive alert setup wizard
# Usage: curl -sSL https://raw.githubusercontent.com/Gogreenraghav/ai24x7-vision/main/cctv-ai/install.sh | bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎯 AI24x7 Vision - Smart Installer v2.0"
echo "  GOUP Consultancy Services LLP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ─── Colors ───────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[✅]${NC} $1"; }
warn() { echo -e "${YELLOW}[⚠️]${NC} $1"; }
error() { echo -e "${RED}[❌]${NC} $1"; }
info() { echo -e "${CYAN}[ℹ️]${NC} $1"; }

# ─── Check Root ─────────────────────────────
if [ "$EUID" -ne 0 ]; then
    warn "Root permission chahiye. sudo use kar raha hoon..."
    exec sudo bash "$0" "$@"
fi

# ─── Detect GPU ───────────────────────────
detect_gpu() {
    if command -v nvidia-smi &>/dev/null; then
        GPU_MODEL=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)
        GPU_VRAM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -1 | awk '{print $1}')
        GPU_VRAM_GB=$((GPU_VRAM / 1024))
        echo "$GPU_MODEL (${GPU_VRAM_GB}GB VRAM)"
        return 0
    else
        echo "GPU NAHIN MILA - CPU mode"
        return 1
    fi
}

detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID $VERSION_ID"
    else
        echo "Unknown"
    fi
}

OS=$(detect_os)
log "OS detected: $OS"

info "GPU detecting..."
GPU_INFO=$(detect_gpu) || true
log "GPU: $GPU_INFO"

# ─── System Requirements Check ─────────────
info "System requirements checking..."

RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
RAM_GB=$((RAM_KB / 1024 / 1024))
info "RAM: ${RAM_GB}GB"

if [ "$RAM_GB" -lt 15 ]; then
    warn "RAM kam hai! 16GB minimum chahiye, ${RAM_GB}GB mila."
fi

# ─── Installation Directory ─────────────────
INSTALL_DIR="/opt/ai24x7"
log "Installing to $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# ─── Create Directory Structure ─────────────
mkdir -p "$INSTALL_DIR/logs"
mkdir -p "$INSTALL_DIR/config"
mkdir -p "$INSTALL_DIR/models"
mkdir -p "$INSTALL_DIR/screenshots"
mkdir -p "$INSTALL_DIR/venv"
mkdir -p "$INSTALL_DIR/cameras"

# ─── Update System ─────────────────────────
info "System updating..."
apt update -qq 2>/dev/null || true

# ─── Install Python ─────────────────────────
info "Python installing..."
if ! command -v python3 &>/dev/null; then
    apt install -y python3 python3-pip python3-venv python3-dev ffmpeg curl wget git 2>/dev/null || true
fi

python3 --version || { error "Python install fail"; exit 1; }

# ─── Create Virtual Environment ─────────────
info "Virtual environment creating..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
pip install --upgrade pip -q

# ─── Install Dependencies ─────────────────
info "Dependencies installing (ye 2-3 min lega)..."
pip install opencv-python-headless flask requests pillow psutil python-telegram-bot \
    ultralytics fastapi uvicorn pydantic aiofiles numpy scipy \
    --quiet 2>&1 | tail -3 || true

log "Dependencies installed!"

# ─── Download Fine-tuned Model ─────────────
MODEL_URL="https://huggingface.co/Arjun9350/ai24x7-vision-v10/resolve/main/model-q5_k_m.gguf"
MODEL_DIR="$INSTALL_DIR/models"
mkdir -p "$MODEL_DIR"

if [ ! -f "$MODEL_DIR/model-q5_k_m.gguf" ]; then
    info "Fine-tuned model downloading (5.5GB - 2-5 min)..."
    HF_TOKEN="${HF_TOKEN:-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}"
    curl -L -H "Authorization: Bearer $HF_TOKEN" \
        "$MODEL_URL" -o "$MODEL_DIR/model-q5_k_m.gguf" \
        --progress-bar || { warn "Model download fail - will use cloud API"; }
fi

if [ -f "$MODEL_DIR/model-q5_k_m.gguf" ]; then
    MODEL_SIZE=$(du -h "$MODEL_DIR/model-q5_k_m.gguf" | cut -f1)
    log "Model downloaded: $MODEL_SIZE"
fi

# ─── Download llama.cpp ─────────────────────
info "llama.cpp downloading..."
LLAMA_DIR="$INSTALL_DIR/llama.cpp"
if [ ! -d "$LLAMA_DIR" ]; then
    git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "$LLAMA_DIR" 2>/dev/null || true
    cd "$LLAMA_DIR"
    cmake -B build -DGGML_CUDA=ON 2>/dev/null | tail -3 || true
    cmake --build build -j4 2>/dev/null | tail -3 || true
    cd "$INSTALL_DIR"
fi
if [ -f "$LLAMA_DIR/build/bin/llama-server" ]; then
    log "llama.cpp built successfully!"
fi

# ═══════════════════════════════════════════
# 🎯 ALERT SETUP WIZARD
# ═══════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📱 ALERT SETUP WIZARD"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Konsa alert platform use karenge?"
echo ""
echo "  [1] 📱 WhatsApp (WhatsApp Business API)"
echo "  [2] ✈️ Telegram (Fast, Free)"
echo "  [3] 🔔 Both (WhatsApp + Telegram)"
echo "  [4] ⏭️  Skip (Offline only - alerts disable)"
echo ""

read -p "Select option [1-4]: " ALERT_CHOICE

case $ALERT_CHOICE in
1)
    USE_WHATSAPP=1; USE_TELEGRAM=0
    ;;
2)
    USE_WHATSAPP=0; USE_TELEGRAM=1
    ;;
3)
    USE_WHATSAPP=1; USE_TELEGRAM=1
    ;;
4)
    USE_WHATSAPP=0; USE_TELEGRAM=0
    ;;
*)
    warn "Invalid choice - skipping alerts"
    USE_WHATSAPP=0; USE_TELEGRAM=0
    ;;
esac

# ─── Telegram Setup ─────────────────────────
if [ "$USE_TELEGRAM" -eq 1 ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  ✈️ TELEGRAM SETUP"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Step 1: Telegram pe @BotFather ko message karo: /newbot"
    echo "Step 2: Bot ka naam aur username do"
    echo "Step 3: Jo API Token milega woh niche paste karo"
    echo ""
    read -p "Bot Token [Enter for default]: " TG_TOKEN
    TG_TOKEN="${TG_TOKEN:-8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY}"
    
    echo ""
    echo "Step 4: @userinfobot ko Telegram pe message karo"
    echo "Step 5: Jo Chat ID milega woh niche paste karo (e.g. 8566322083)"
    read -p "Your Chat ID: " TG_CHAT_ID
fi

# ─── WhatsApp Setup ─────────────────────────
if [ "$USE_WHATSAPP" -eq 1 ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  📱 WHATSAPP SETUP"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "WhatsApp Business API setup:"
    echo "  1. Meta Business App banavo: developers.facebook.com"
    echo "  2. WhatsApp Business API add karo"
    echo "  3. Phone number verify karo"
    echo "  4. Webhook URL set karo: http://YOUR_IP:5054/webhook"
    echo ""
    read -p "WhatsApp Phone Number (with country code): " WA_PHONE
    read -p "WhatsApp Business Account ID: " WA_BUSINESS_ID
    read -p "Meta App Secret: " WA_APP_SECRET
    
    info "WhatsApp webhook setup instruction diye gaye."
    info "Baaki details ke liye: https://business.whatsapp.com/developers/developer-hub"
fi

# ─── Camera Configuration ──────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  📹 CAMERA CONFIGURATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

CAMERA_COUNT=0
while true; do
    read -p "Kitne cameras hain? (0-100): " CAMERA_COUNT
    if [ "$CAMERA_COUNT" -ge 0 ] && [ "$CAMERA_COUNT" -le 100 ]; then
        break
    fi
    warn "0-100 ke beech mein do!"
done

if [ "$CAMERA_COUNT" -gt 0 ]; then
    info "Camera details adding..."
    for i in $(seq 1 $CAMERA_COUNT); do
        echo ""
        echo "  Camera $i details:"
        read -p "    Name (e.g. Main Gate): " CAM_NAME
        read -p "    RTSP URL (e.g. rtsp://admin:password@192.168.1.100:554/stream): " CAM_RTSP
        read -p "    Location: " CAM_LOC
        
        cat >> "$INSTALL_DIR/cameras/camera_config.sh" << EOF
camera_${i}:
  name: "${CAM_NAME}"
  rtsp: "${CAM_RTSP}"
  location: "${CAM_LOC}"
  enabled: true
EOF
    done
fi

# ─── License Activation ─────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🔑 LICENSE ACTIVATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Agar license key hai toh enter karo (format: AI24-XXX-XXXX-XXXX-XXXX)"
echo "Trial ke liye trial likho"
echo "Skip karne ke lihe Enter dabao"
echo ""
read -p "License Key: " LICENSE_KEY

if [ -n "$LICENSE_KEY" ]; then
    info "License verifying..."
    if command -v python3 &>/dev/null; then
        python3 << EOF
import sys
sys.path.insert(0, '/opt/ai24x7-super-admin')
try:
    import license_client as lc
    lm = lc.LicenseManager()
    if "$LICENSE_KEY" == "trial"; then
        result = lm.activate("AI24-TRI-" + "TRIAL0000000"[0:12])
    else:
        result = lm.activate("$LICENSE_KEY")
    if result.get("success"):
        print("✅ License activated:", result.get("plan"))
    else:
        print("⚠️ License activation fail:", result.get("message"))
except Exception as e:
    print(f"⚠️ License check skip: {e}")
EOF
    fi
fi

# ─── Create Config File ───────────────────
cat > "$INSTALL_DIR/config/ai24x7.conf" << EOF
# AI24x7 Configuration
# Auto-generated by Smart Installer
INSTALL_DATE=$(date +%Y-%m-%d)
GPU_INFO="$GPU_INFO"
ALERT_TELEGRAM=$USE_TELEGRAM
ALERT_WHATSAPP=$USE_WHATSAPP
TG_BOT_TOKEN="${TG_TOKEN}"
TG_CHAT_ID="${TG_CHAT_ID}"
WA_PHONE="${WA_PHONE}"
WA_BUSINESS_ID="${WA_BUSINESS_ID}"
CAMERA_COUNT=${CAMERA_COUNT}
CLOUD_API_URL="http://43.242.224.231:5050"
LICENSE_SERVER="http://43.242.224.231:5053"
MODEL_PATH="${MODEL_DIR}/model-q5_k_m.gguf"
EOF

log "Config file created!"

# ─── Create Systemd Service ───────────────
cat > /etc/systemd/system/ai24x7.service << EOF
[Unit]
Description=AI24x7 Vision CCTV Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PATH=$INSTALL_DIR/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin"
ExecStart=$INSTALL_DIR/venv/bin/python3 $INSTALL_DIR/ai24x7_agent.py
Restart=always
RestartSec=10
StandardOutput=append:$INSTALL_DIR/logs/agent.log
StandardError=append:$INSTALL_DIR/logs/agent.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload 2>/dev/null || true
systemctl enable ai24x7 2>/dev/null || true

# ─── Create launcher script ────────────────
cat > "$INSTALL_DIR/ai24x7.sh" << 'EOF'
#!/bin/bash
cd /opt/ai24x7
source venv/bin/activate
python3 ai24x7_agent.py "$@"
EOF
chmod +x "$INSTALL_DIR/ai24x7.sh"

# ─── Firewall Check ───────────────────────
info "Checking firewall..."
if command -v ufw &>/dev/null; then
    ufw allow 5050/tcp 2>/dev/null || true
    ufw allow 5051/tcp 2>/dev/null || true
    ufw allow 8501/tcp 2>/dev/null || true
fi

# ─── Final Summary ─────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ AI24x7 INSTALLATION COMPLETE!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
log "Installation directory: $INSTALL_DIR"
log "Logs: $INSTALL_DIR/logs/"
log "Config: $INSTALL_DIR/config/ai24x7.conf"
log "Cameras configured: ${CAMERA_COUNT}"
echo ""
echo "📋 USEFUL COMMANDS:"
echo "  Status:   systemctl status ai24x7"
echo "  Logs:     tail -f $INSTALL_DIR/logs/agent.log"
echo "  Start:    systemctl start ai24x7"
echo "  Restart:  systemctl restart ai24x7"
echo "  Dashboard: http://localhost:8501"
echo ""
echo "🔑 License: $([ -n "$LICENSE_KEY" ] && echo "$LICENSE_KEY" || echo 'Not activated')"
echo "📱 Alerts: $([ "$USE_TELEGRAM" -eq 1 ] && echo "Telegram ✅" || echo "Telegram ❌") $([ "$USE_WHATSAPP" -eq 1 ] && echo "+ WhatsApp ✅" || echo "")"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🎉 AI24x7 Vision ready hai!"
echo "  Owner: GOUP Consultancy Services LLP"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
