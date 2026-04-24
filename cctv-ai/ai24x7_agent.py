#!/usr/bin/env python3
"""
AI24x7 Vision SaaS - CCTV Camera Agent
Runs on customer machine (₹42K config: AMD Ryzen 7, 32GB RAM, no GPU)
Captures CCTV frames and sends to cloud GPU API for analysis
"""

from flask import Flask, request, jsonify
import os, logging, sys, time, signal
from datetime import datetime
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/opt/ai24x7/logs/agent.log')
    ]
)
logger = logging.getLogger('ai24x7')

app = Flask(__name__)

# Config from environment
CLOUD_API_URL = os.environ.get('CLOUD_API_URL', 'http://43.242.224.231:5050')
API_KEY = os.environ.get('AI24x7_API_KEY', 'ai24x7-demo-key-2024')
CAMERAS_JSON = os.environ.get('CAMERAS', '[{"name":"cam1","rtsp":"rtsp://admin:admin@192.168.1.100:554/stream1"}]')
CHECK_INTERVAL = int(os.environ.get('CHECK_INTERVAL', '30'))  # seconds between checks
CONFIDENCE_THRESHOLD = float(os.environ.get('CONFIDENCE_THRESHOLD', '0.6'))

try:
    import cv2
    OPENCV_OK = True
    logger.info("OpenCV available - RTSP capture enabled")
except ImportError:
    OPENCV_OK = False
    logger.warning("OpenCV not available - RTSP capture disabled, use /analyze endpoint only")

try:
    import telegram
    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    TELEGRAM_OK = True
except:
    TELEGRAM_OK = False
    logger.warning("Telegram not configured")

def send_telegram_alert(cam_name, analysis, confidence=None):
    if not TELEGRAM_OK or not TELEGRAM_CHAT_ID:
        return
    try:
        bot = telegram.Bot(TELEGRAM_BOT_TOKEN)
        conf_text = f"\n\n📊 Confidence: {confidence:.0%}" if confidence else ""
        msg = (f"🚨 *AI24x7 Alert*\n"
               f"📷 Camera: {cam_name}\n"
               f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
               f"{conf_text}\n\n"
               f"{analysis}")
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg, parse_mode='Markdown')
        logger.info(f"Telegram alert sent for {cam_name}")
    except Exception as e:
        logger.warning(f"Telegram alert failed: {e}")

def analyze_image(image_bytes, cam_name="unknown"):
    """Send image to cloud GPU API for analysis"""
    try:
        resp = requests.post(
            f"{CLOUD_API_URL}/analyze",
            files={'image': ('frame.jpg', image_bytes, 'image/jpeg')},
            headers={'X-API-Key': API_KEY},
            timeout=120
        )
        if resp.status_code == 200:
            result = resp.json()
            analysis = result.get('analysis', '')
            logger.info(f"[{cam_name}] Analysis: {analysis[:100]}...")
            return analysis, True
        else:
            logger.error(f"[{cam_name}] API error {resp.status_code}: {resp.text[:200]}")
            return f"Error: {resp.status_code}", False
    except Exception as e:
        logger.error(f"[{cam_name}] Request failed: {e}")
        return f"Connection error: {e}", False

def capture_frame(rtsp_url):
    """Capture single frame from RTSP stream"""
    if not OPENCV_OK:
        return None
    try:
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret, frame = cap.read()
        cap.release()
        if ret:
            ret2, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ret2:
                return buf.tobytes()
    except Exception as e:
        logger.warning(f"RTSP capture failed: {e}")
    return None

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "AI24x7 CCTV Agent",
        "version": "v1.0",
        "cloud_api": CLOUD_API_URL,
        "opencv": OPENCV_OK,
        "telegram": TELEGRAM_OK and bool(TELEGRAM_CHAT_ID)
    })

@app.route('/analyze', methods=['POST'])
def analyze():
    """Direct image analysis - for testing or manual upload"""
    try:
        if 'image' in request.files:
            img_bytes = request.files['image'].read()
        elif 'image_url' in request.form:
            # Download from URL first
            r = requests.get(request.form['image_url'], timeout=30)
            img_bytes = r.content
        else:
            return jsonify({"error": "No image provided"}), 400

        analysis, ok = analyze_image(img_bytes, "direct_upload")
        return jsonify({
            "analysis": analysis,
            "status": "success" if ok else "error",
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route('/camera/<cam_id>/snapshot', methods=['GET'])
def camera_snapshot(cam_id):
    """Capture and analyze a specific camera"""
    import json
    cameras = json.loads(CAMERAS_JSON)
    cam = next((c for c in cameras if c['id'] == cam_id or c['name'] == cam_id), None)
    if not cam:
        return jsonify({"error": f"Camera {cam_id} not found"}), 404

    rtsp = cam.get('rtsp')
    if not rtsp:
        return jsonify({"error": "No RTSP URL configured"}), 400

    img_bytes = capture_frame(rtsp)
    if not img_bytes:
        return jsonify({"error": "Failed to capture frame"}), 500

    analysis, ok = analyze_image(img_bytes, cam['name'])
    return jsonify({
        "camera": cam['name'],
        "analysis": analysis,
        "status": "success" if ok else "error",
        "rtsp": rtsp[:50] + "***"
    })

@app.route('/cameras', methods=['GET'])
def list_cameras():
    import json
    return jsonify({"cameras": json.loads(CAMERAS_JSON)})

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "service": "AI24x7 CCTV Vision Agent",
        "version": "v1.0",
        "endpoints": [
            "/health - health check",
            "/analyze - POST image file for analysis",
            "/camera/<id>/snapshot - capture and analyze camera",
            "/cameras - list configured cameras"
        ]
    })

def run_camera_loop():
    """Background loop: capture and analyze all cameras periodically"""
    import json, threading, time
    cameras = json.loads(CAMERAS_JSON)
    logger.info(f"Camera loop starting with {len(cameras)} cameras, interval={CHECK_INTERVAL}s")

    while True:
        for cam in cameras:
            rtsp = cam.get('rtsp')
            if not rtsp:
                continue
            img_bytes = capture_frame(rtsp)
            if img_bytes:
                analysis, ok = analyze_image(img_bytes, cam['name'])
                if ok and TELEGRAM_OK and TELEGRAM_CHAT_ID:
                    send_telegram_alert(cam['name'], analysis)
            time.sleep(2)  # brief pause between cameras
        time.sleep(CHECK_INTERVAL)

def signal_handler(sig, frame):
    logger.info("Shutting down...")
    sys.exit(0)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    port = int(os.environ.get('PORT', 5051))
    logger.info(f"AI24x7 CCTV Agent starting on port {port}")
    logger.info(f"Cloud API: {CLOUD_API_URL}")

    # Start camera loop in background thread
    if OPENCV_OK:
        t = threading.Thread(target=run_camera_loop, daemon=True)
        t.start()
        logger.info("Camera monitoring thread started")

    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
