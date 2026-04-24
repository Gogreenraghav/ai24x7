# AI24x7 - CCTV Camera RTSP Configuration
# =========================================
# Yahan apne cameras ke RTSP URLs daalo
# Format: rtsp://username:password@ip_address:554/stream
# =========================================

CAMERAS = [
    {"id": 1, "name": "Main Gate",    "rtsp": "rtsp://admin:password@192.168.1.10:554/stream1"},
    {"id": 2, "name": "Reception",   "rtsp": "rtsp://admin:password@192.168.1.11:554/stream1"},
    {"id": 3, "name": "Hall",        "rtsp": "rtsp://admin:password@192.168.1.12:554/stream1"},
    {"id": 4, "name": "Office",      "rtsp": "rtsp://admin:password@192.168.1.13:554/stream1"},
    {"id": 5, "name": "Parking",     "rtsp": "rtsp://admin:password@192.168.1.14:554/stream1"},
    {"id": 6, "name": "Warehouse",   "rtsp": "rtsp://admin:password@192.168.1.15:554/stream1"},
    {"id": 7, "name": "Canteen",     "rtsp": "rtsp://admin:password@192.168.1.16:554/stream1"},
    {"id": 8, "name": "Corridor",   "rtsp": "rtsp://admin:password@192.168.1.17:554/stream1"},
    {"id": 9, "name": "Storage",     "rtsp": "rtsp://admin:password@192.168.1.18:554/stream1"},
    {"id": 10, "name": "Roof",      "rtsp": "rtsp://admin:password@192.168.1.19:554/stream1"},
]

# AI24x7 Cloud API (humara server)
API_URL = "http://43.242.224.231:5050/analyze"
API_HEALTH = "http://43.242.224.231:5050/health"

# Telegram Alert
TELEGRAM_TOKEN = "8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY"
TELEGRAM_CHAT_ID = "8566322083"
