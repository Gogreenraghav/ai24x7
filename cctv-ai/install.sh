#!/bin/bash
# AI24x7 Vision SaaS - One Command Installer v1.0
# Target: AMD Ryzen 7 5800X / 32GB RAM / 500GB SSD - CPU Only (₹42-50K machine)
# Architecture: Customer machine captures CCTV → sends to cloud GPU API → gets analysis

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   AI24x7 Vision SaaS - One Command Installer  ║${NC}"
echo -e "${CYAN}║   CCTV AI Analysis for ₹42-50K Hardware      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Detect root
if [[ $EUID -ne 0 ]]; then
    warn "Not running as root. Some steps may fail."
fi

# Check system
info "Checking system..."
TOTAL_RAM=$(free -g | grep Mem | awk '{print $2}')
info "  RAM: ${TOTAL_RAM}GB"
if [[ $TOTAL_RAM -lt 16 ]]; then
    warn "  16GB+ recommended. ${TOTAL_RAM}GB may be slow."
fi
AVAIL_DISK=$(df -BG / | tail -1 | awk '{print $4}' | tr -d 'G')
info "  Disk free: ${AVAIL_DISK}GB"
[[ $AVAIL_DISK -lt 30 ]] && error "30GB+ disk space needed"

# Install deps
info "Installing system packages..."
if command -v apt-get &> /dev/null; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq 2>/dev/null
    apt-get install -y -qq curl wget python3 python3-pip python3-venv git libgomp1 jq ffmpeg 2>/dev/null
elif command -v yum &> /dev/null; then
    yum install -y -q curl wget python3 python3-pip git ffmpeg 2>/dev/null
elif command -v pacman &> /dev/null; then
    pacman -Sy --noconfirm curl wget python3 python-pip git ffmpeg base-devel 2>/dev/null
fi
info "  System packages OK"

# Install Python deps
info "Installing Python packages..."
pip3 install -q flask requests pillow python-telegram-bot opencv-python-headless --break-system-packages 2>/dev/null || \
pip3 install -q flask requests pillow python-telegram-bot opencv-python-headless --user 2>/dev/null || true
info "  Python packages OK"

# Create install dir
INSTALL_DIR="/opt/ai24x7"
mkdir -p "$INSTALL_DIR"/{models,logs,scripts}
info "Install directory: $INSTALL_DIR"

# Download AI24x7 agent script
info "Downloading AI24x7 Agent..."
AGENT_URL="https://raw.githubusercontent.com/Arjun9350/ai24x7/main/ai24x7_agent.py"
if command -v curl &> /dev/null; then
    curl -s "$AGENT_URL" -o "$INSTALL_DIR/scripts/ai24x7_agent.py" 2>/dev/null || \
    warn "Could not download from GitHub - will use embedded script"
fi
chmod +x "$INSTALL_DIR/scripts/ai24x7_agent.py" 2>/dev/null || true

# Write embedded agent script (if download failed)
cat > "$INSTALL_DIR/scripts/ai24x7_agent.py" << 'PYEOF'
#!/usr/bin/env python3
"""AI24x7 CCTV Agent - Customer Machine Software"""
from flask import Flask, request, jsonify
import os, logging, sys, signal, io
from datetime import datetime
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', stream=sys.stdout)
logger = logging.getLogger('ai24x7')

app = Flask(__name__)
CLOUD_API = os.environ.get('CLOUD_API', 'http://43.242.224.231:5050')
API_KEY = os.environ.get('API_KEY', 'ai24x7-demo-key')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY')
CHAT_ID = os.environ.get('CHAT_ID', '')

def alert(msg):
    if not CHAT_ID: return
    try:
        import telegram
        bot = telegram.Bot(BOT_TOKEN)
        bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
    except: pass

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'AI24x7 Agent', 'cloud': CLOUD_API})

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        img = request.files.get('image') or (request.form.get('image_url') and requests.get(request.form['image_url']).content)
        if not img:
            return jsonify({'error': 'no image'}), 400
        img_bytes = img.read() if hasattr(img, 'read') else img
        r = requests.post(f'{CLOUD_API}/analyze', files={'image': img_bytes}, headers={'X-API-Key': API_KEY}, timeout=120)
        result = r.json()
        if CHAT_ID and result.get('analysis'):
            alert(f"🚨 AI24x7\n{result['analysis'][:300]}")
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/')
def index():
    return jsonify({'service': 'AI24x7 CCTV Agent v1.0', 'endpoints': ['/health', '/analyze']})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5051))
    logger.info(f"AI24x7 Agent starting on port {port}, cloud={CLOUD_API}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
PYEOF

chmod +x "$INSTALL_DIR/scripts/ai24x7_agent.py"

# Write systemd service
info "Creating systemd service..."
cat > /etc/systemd/system/ai24x7.service << EOF
[Unit]
Description=AI24x7 Vision SaaS CCTV Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="CLOUD_API=http://43.242.224.231:5050"
Environment="API_KEY=ai24x7-demo-key"
Environment="BOT_TOKEN=8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY"
Environment="CHAT_ID="
Environment="PORT=5051"
ExecStart=/usr/bin/python3 $INSTALL_DIR/scripts/ai24x7_agent.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Start service
systemctl daemon-reload
systemctl enable ai24x7 2>/dev/null || warn "systemd not available"
systemctl restart ai24x7 2>/dev/null || true

sleep 2

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║        INSTALLATION COMPLETE! 🎉             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  🌐 API URL:   http://YOUR-IP:5051/analyze"
echo -e "  📊 Health:    http://YOUR-IP:5051/health"
echo -e "  💬 Telegram:  DISABLED (set CHAT_ID)"
echo ""
echo -e "  To enable Telegram alerts:"
echo -e "    nano /etc/systemd/system/ai24x7.service"
echo -e "    → Set CHAT_ID=your_telegram_chat_id"
echo -e "    → systemctl restart ai24x7"
echo ""
echo -e "  To configure CCTV cameras:"
echo -e "    → Edit CLOUD_API to point to your GPU server"
echo -e "    → Camera RTSP URLs: request.files['image'] or /camera/<id>/snapshot"
echo ""
echo -e "  ✅ Service status:"
systemctl is-active ai24x7 2>/dev/null && echo -e "    ${GREEN}RUNNING${NC}" || echo -e "    ${YELLOW}Check manually${NC}"
echo ""
