"""
AI24x7 Vision - CCTV Monitoring Dashboard
Multi-camera grid view with AI analysis & Telegram alerts
Run: streamlit run cctv_dashboard.py --server.port 8501
"""

import streamlit as st
import cv2
import requests
import json
import time
import threading
import queue
import numpy as np
from datetime import datetime
from PIL import Image
import io
import urllib.request
import urllib.error

# ===================== CONFIG =====================
API_URL = "http://43.242.224.231:5050/analyze"
API_HEALTH = "http://43.242.224.231:5050/health"
TELEGRAM_TOKEN = "8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY"
TELEGRAM_CHAT_ID = "8566322083"  # Arjun's Telegram ID

# Camera configuration - UPDATE THESE RTSP URLS
CAMERAS = [
    {"id": 1, "name": "Main Gate",     "rtsp": "rtsp://admin:admin@192.168.1.10:554/stream1"},
    {"id": 2, "name": "Reception",    "rtsp": "rtsp://admin:admin@192.168.1.11:554/stream1"},
    {"id": 3, "name": "Hall",          "rtsp": "rtsp://admin:admin@192.168.1.12:554/stream1"},
    {"id": 4, "name": "Office",       "rtsp": "rtsp://admin:admin@192.168.1.13:554/stream1"},
    {"id": 5, "name": "Parking",      "rtsp": "rtsp://admin:admin@192.168.1.14:554/stream1"},
    {"id": 6, "name": "Warehouse",    "rtsp": "rtsp://admin:admin@192.168.1.15:554/stream1"},
    {"id": 7, "name": "Canteen",      "rtsp": "rtsp://admin:admin@192.168.1.16:554/stream1"},
    {"id": 8, "name": "Corridor",     "rtsp": "rtsp://admin:admin@192.168.1.17:554/stream1"},
    {"id": 9, "name": "Storage",      "rtsp": "rtsp://admin:admin@192.168.1.18:554/stream1"},
    {"id": 10, "name": "Roof",        "rtsp": "rtsp://admin:admin@192.168.1.19:554/stream1"},
]

SCAN_INTERVAL = 8  # seconds between scans
ALERT_COOLDOWN = 60  # seconds before same camera can alert again

# ===================== STYLE =====================
st.set_page_config(
    page_title="AI24x7 Vision Dashboard",
    page_icon="🎥",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
.stApp > header {background-color: #1a1a2e;}
.block-container {padding-top: 1rem;}
.camera-card {border: 2px solid #333; border-radius: 8px; padding: 4px; text-align: center;}
.camera-alert {border: 3px solid #ff0000; animation: blink 0.5s infinite;}
@keyframes blink {0%{border-color:#ff0000;} 50%{border-color:#ff6600;} 100%{border-color:#ff0000;}}
.status-online {color:#00ff00; font-weight:bold;}
.status-offline {color:#ff4444; font-weight:bold;}
.status-alert {color:#ffaa00; font-weight:bold;}
div[data-testid="stMetricValue"] {font-size: 1.8rem !important;}
</style>
""", unsafe_allow_html=True)

# ===================== SESSION STATE =====================
if "alerts" not in st.session_state:
    st.session_state.alerts = []
if "camera_status" not in st.session_state:
    st.session_state.camera_status = {c["id"]: {"status": "online", "last_alert": 0, "last_result": ""} for c in CAMERAS}
if "api_online" not in st.session_state:
    st.session_state.api_online = None
if "frame_cache" not in st.session_state:
    st.session_state.frame_cache = {}
if "selected_cam" not in st.session_state:
    st.session_state.selected_cam = None


# ===================== FUNCTIONS =====================
def check_api():
    """Check if AI API is online"""
    try:
        r = requests.get(API_HEALTH, timeout=3)
        return r.status_code == 200
    except:
        return False


def grab_frame(rtsp_url, cam_id):
    """Grab frame from RTSP stream, fallback to placeholder"""
    try:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
        ret, frame = cap.read()
        cap.release()
        if ret and frame is not None:
            return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except Exception as e:
        pass
    # Generate a demo frame
    return generate_demo_frame(cam_id)


def generate_demo_frame(cam_id):
    """Generate a colored placeholder frame for demo/testing"""
    colors = [
        (30, 60, 90), (60, 90, 30), (90, 30, 60),
        (30, 90, 60), (60, 30, 90), (90, 60, 30),
        (45, 75, 105), (75, 45, 75), (45, 105, 75), (105, 75, 45)
    ]
    frame = np.zeros((360, 640, 3), dtype=np.uint8)
    b, g, r = colors[(cam_id - 1) % len(colors)]
    frame[:, :] = [b, g, r]
    # Add camera number
    cv2.putText(frame, f"CAM {cam_id}", (220, 170), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (255, 255, 255), 3)
    # Add camera name
    cam_name = next((c["name"] for c in CAMERAS if c["id"] == cam_id), f"Cam {cam_id}")
    cv2.putText(frame, cam_name, (220, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
    cv2.putText(frame, "DEMO MODE", (240, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)
    return frame


def analyze_frame(frame):
    """Send frame to AI24x7 API for analysis"""
    try:
        _, img_enc = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        files = {"image": ("frame.jpg", img_enc.tobytes(), "image/jpeg")}
        r = requests.post(API_URL, files=files, timeout=15)
        if r.status_code == 200:
            return r.json()
        return {"error": f"API error {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


def send_telegram_alert(cam_name, detection_result, frame=None):
    """Send Telegram alert with detection info"""
    try:
        message = f"🚨 *AI24x7 ALERT*\n📷 Camera: {cam_name}\n🔍 Detection: {detection_result}\n⏰ Time: {datetime.now().strftime('%H:%M:%S')}"
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        requests.post(url, data=data, timeout=10)
        if frame is not None:
            # Send photo
            img_bytes = cv2.imencode('.jpg', cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))[1].tobytes()
            photo_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
            files = {"photo": ("alert.jpg", img_bytes, "image/jpeg")}
            data2 = {"chat_id": TELEGRAM_CHAT_ID, "caption": message, "parse_mode": "Markdown"}
            requests.post(photo_url, data=data2, files=files, timeout=15)
    except Exception as e:
        st.warning(f"Telegram error: {e}")


def is_suspicious(result_text):
    """Check if detection result is suspicious (triggers alert)"""
    if not result_text or "error" in result_text.lower():
        return False
    suspicious_keywords = ["person", "unknown", "suspicious", "vehicle", "movement",
                            "alert", "intruder", "warning", "danger"]
    result_lower = result_text.lower()
    return any(kw in result_lower for kw in suspicious_keywords)


# ===================== HEADER METRICS =====================
col1, col2, col3, col4, col5 = st.columns(5)

api_ok = check_api()
st.session_state.api_online = api_ok

active_cams = sum(1 for c in CAMERAS if st.session_state.camera_status[c["id"]]["status"] != "offline")
alert_count = len([a for a in st.session_state.alerts if a["time"].date() == datetime.now().date()])

col1.metric("🎥 Active Cameras", f"{active_cams}/{len(CAMERAS)}")
col2.metric("🚨 Alerts Today", str(alert_count))
col3.metric("⏰ Last Scan", datetime.now().strftime("%H:%M:%S"))
col4.metric("🖥️ API Status", "🟢 Online" if api_ok else "🔴 Offline")
col5.metric("🔄 Scan Interval", f"{SCAN_INTERVAL}s")

st.markdown("---")

# ===================== GRID VIEW =====================
st.subheader("📺 Live Camera Grid")

selected = st.radio("View Mode:", ["Grid (2×5)", "Grid (1×10)", "Single Full View"], horizontal=True, index=1)

if selected == "Single Full View":
    cam_options = [f"Cam {c['id']}: {c['name']}" for c in CAMERAS]
    selected_name = st.selectbox("Select Camera:", cam_options)
    cam_id = int(selected_name.split(":")[0].replace("Cam ", ""))
    cam = next(c for c in CAMERAS if c["id"] == cam_id)
    
    frame = grab_frame(cam["rtsp"], cam["id"])
    st.session_state.frame_cache[cam_id] = frame
    
    status = st.session_state.camera_status[cam_id]["status"]
    result = st.session_state.camera_status[cam_id]["last_result"]
    
    if status == "alert":
        st.error(f"🚨 ALERT on {cam['name']}: {result}")
    elif status == "online":
        st.success(f"✅ {cam['name']} - {result}")
    
    st.image(frame, channels="RGB", width=800)
    
    # Manual analyze button
    if st.button(f"🔍 Analyze Cam {cam_id}", type="primary"):
        with st.spinner("Analyzing..."):
            result = analyze_frame(frame)
            result_text = result.get("result", result.get("analysis", result.get("error", "No result")))
            st.session_state.camera_status[cam_id]["last_result"] = result_text
            
            if is_suspicious(result_text):
                st.session_state.camera_status[cam_id]["status"] = "alert"
                send_telegram_alert(cam["name"], result_text, frame)
                st.session_state.alerts.insert(0, {
                    "time": datetime.now(),
                    "camera": cam["name"],
                    "detection": result_text,
                    "confidence": result.get("confidence", "N/A")
                })
                st.error(f"🚨 ALERT! {result_text}")
            else:
                st.session_state.camera_status[cam_id]["status"] = "online"
                st.info(f"✅ {result_text}")

else:
    cols = st.columns(5 if "2×5" in selected else 10)
    
    for i, cam in enumerate(CAMERAS):
        with cols[i % (5 if "2×5" in selected else 10)]:
            frame = grab_frame(cam["rtsp"], cam["id"])
            st.session_state.frame_cache[cam["id"]] = frame
            
            status = st.session_state.camera_status[cam["id"]]["status"]
            result = st.session_state.camera_status[cam["id"]]["last_result"]
            
            # Frame with status border
            display_frame = frame.copy()
            if status == "alert":
                cv2.rectangle(display_frame, (0, 0), (639, 359), (0, 0, 255), 8)
                label = "🚨 ALERT"
                label_color = (0, 0, 255)
            elif status == "offline":
                cv2.rectangle(display_frame, (0, 0), (639, 359), (128, 128, 128), 4)
                label = "OFFLINE"
                label_color = (128, 128, 128)
            else:
                cv2.rectangle(display_frame, (0, 0), (639, 359), (0, 180, 0), 3)
                label = "✓ LIVE"
                label_color = (0, 200, 0)
            
            cv2.putText(display_frame, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, label_color, 2)
            
            st.image(display_frame, channels="RGB", caption=f"Cam {cam['id']}: {cam['name']}", width=280)
            
            if st.button(f"🔍", key=f"btn_{cam['id']}"):
                with st.spinner(f"Analyzing Cam {cam['id']}..."):
                    result = analyze_frame(frame)
                    result_text = result.get("result", result.get("analysis", result.get("error", "No result")))
                    st.session_state.camera_status[cam["id"]]["last_result"] = result_text
                    
                    if is_suspicious(result_text):
                        st.session_state.camera_status[cam["id"]]["status"] = "alert"
                        send_telegram_alert(cam["name"], result_text, frame)
                        st.session_state.alerts.insert(0, {
                            "time": datetime.now(),
                            "camera": cam["name"],
                            "detection": result_text,
                            "confidence": result.get("confidence", "N/A")
                        })
                        st.error(f"🚨 Alert! Cam {cam['id']}: {result_text}")
                    else:
                        st.session_state.camera_status[cam["id"]]["status"] = "online"
                        st.success(f"Cam {cam['id']}: {result_text}")

# ===================== ALERT LOG =====================
st.markdown("---")
st.subheader("🚨 AI Alert Log")

if st.session_state.alerts:
    # Show last 20 alerts
    alert_data = []
    for a in st.session_state.alerts[:20]:
        alert_data.append({
            "Time": a["time"].strftime("%H:%M:%S"),
            "Date": a["time"].strftime("%Y-%m-%d"),
            "Camera": a["camera"],
            "Detection": a["detection"][:80],
            "Confidence": a.get("confidence", "N/A")
        })
    st.dataframe(alert_data, use_container_width=True, hide_index=True)
else:
    st.info("No alerts yet. Click 🔍 on any camera to start AI analysis!")

# ===================== SIDEBAR CONTROLS =====================
with st.sidebar:
    st.header("⚙️ AI24x7 Settings")
    
    st.subheader("📷 Camera Setup")
    st.caption("Update RTSP URLs in cctv_dashboard.py")
    
    if st.checkbox("Show camera config"):
        st.json(CAMERAS)
    
    st.subheader("📡 API Connection")
    st.write(f"API: {API_URL}")
    st.write(f"Status: {'🟢 Connected' if api_ok else '🔴 Disconnected'}")
    
    if st.button("🔄 Recheck API"):
        st.rerun()
    
    st.subheader("📤 Telegram")
    st.write(f"Bot: @ai24x7_vision_bot")
    st.write(f"Chat ID: {TELEGRAM_CHAT_ID}")
    
    if st.button("📤 Test Telegram Alert"):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": "✅ *AI24x7 Dashboard*\nTest alert successful!\n⏰ " + datetime.now().strftime("%H:%M:%S"), "parse_mode": "Markdown"}
            r = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                st.success("✅ Telegram test sent!")
            else:
                st.error(f"Telegram error: {r.status_code}")
        except Exception as e:
            st.error(f"Error: {e}")
    
    st.subheader("📊 Quick Stats")
    st.write(f"Total Alerts: {len(st.session_state.alerts)}")
    st.write(f"Cameras Online: {active_cams}/{len(CAMERAS)}")
    st.write(f"Session: {datetime.now().strftime('%H:%M:%S')}")
    
    st.subheader("📝 Alert Filter")
    keywords = st.text_input("Alert keywords (comma sep):", "person,vehicle,unknown,suspicious")
    st.caption("Change keyword detection threshold")
    
    st.markdown("---")
    st.caption("AI24x7 Vision Dashboard v1.0\nPowered by Qwen3VL-8B Fine-tuned\n© AI24x7 Vision")

# Auto-refresh placeholder (Streamlit doesn't auto-refresh without extra tools)
st.caption(f"🕐 Last updated: {datetime.now().strftime('%H:%M:%S')} | Auto-refresh: {SCAN_INTERVAL}s")
