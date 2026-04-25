"""
AI24x7 WhatsApp Bot - Text Command Handler
Receives WhatsApp messages via webhook and responds with commands.
Requires: WhatsApp Business API Cloud or Twilio WhatsApp Sandbox
"""
import os, json, sqlite3, requests, hashlib
from datetime import datetime, timedelta
from pathlib import Path

# ─── Config ───────────────────────────────
BOT_VERSION = "1.0.0"
DB_PATH = "/opt/ai24x7/ai24x7_super_admin.db"
LICENSE_CLIENT = "/opt/ai24x7-super-admin/license_client.py"
WA_VERIFY_TOKEN = os.environ.get("WA_VERIFY_TOKEN", "ai24x7_verify_2024")
WA_ACCESS_TOKEN = os.environ.get("WA_ACCESS_TOKEN", "")
WA_PHONE = os.environ.get("WA_PHONE", "")  # Your WhatsApp Business number

# ─── Import license manager ─────────────
sys.path.insert(0, "/opt/ai24x7-super-admin")
try:
    import license_client as lc
    LICENSE_OK = True
except:
    LICENSE_OK = False
    print("⚠️ License client not available")

# ─── Database ────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ─── License Check ───────────────────────
def check_license():
    if not LICENSE_OK:
        return True, "license_check_skip"
    try:
        import license_client as lc
        lm = lc.LicenseManager()
        valid, msg = lm.verify(force_online=False)
        return valid, msg
    except:
        return True, "license_error"

def check_feature(feature):
    if not LICENSE_OK:
        return True
    try:
        import license_client as lc
        lm = lc.LicenseManager()
        return lm.is_feature_enabled(feature)
    except:
        return True

# ─── WhatsApp API Helpers ────────────────
def wa_send_message(to_number, text):
    """Send WhatsApp text message via Graph API"""
    if not WA_ACCESS_TOKEN or not WA_PHONE:
        return {"success": False, "error": "WA_API_NOT_CONFIGURED"}
    
    url = f"https://graph.facebook.com/v18.0/{WA_PHONE}/messages"
    headers = {"Authorization": f"Bearer {WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": text[:4096]}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    return r.json()

def wa_send_image(to_number, image_url, caption=""):
    """Send WhatsApp image with caption"""
    if not WA_ACCESS_TOKEN:
        return {"success": False, "error": "WA_API_NOT_CONFIGURED"}
    
    url = f"https://graph.facebook.com/v18.0/{WA_PHONE}/messages"
    headers = {"Authorization": f"Bearer {WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "image",
        "image": {"link": image_url, "caption": caption[:4096]}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    return r.json()

def wa_send_buttons(to_number, text, buttons):
    """Send interactive buttons"""
    if not WA_ACCESS_TOKEN:
        return {"success": False, "error": "WA_API_NOT_CONFIGURED"}
    
    url = f"https://graph.facebook.com/v18.0/{WA_PHONE}/messages"
    headers = {"Authorization": f"Bearer {WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text[:4096]},
            "action": {
                "buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"][:25]}} for b in buttons[:3]]
            }
        }
    }
    r = requests.post(url, headers=headers, json=payload, timeout=15)
    return r.json()

# ─── Telegram Bot (Fallback) ───────────
def tg_send_message(chat_id, text):
    """Send Telegram message as fallback"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    r = requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    return r.json()

# ─── Command Handlers ───────────────────
def cmd_status(customer_phone):
    """Show all camera statuses"""
    conn = get_db()
    rows = conn.execute("""
        SELECT m.hostname, m.status, m.health_score, m.last_heartbeat,
               (SELECT COUNT(*) FROM cameras WHERE machine_id = m.id AND status='online') as cam_online,
               (SELECT COUNT(*) FROM cameras WHERE machine_id = m.id) as cam_total
        FROM machines m
        JOIN customers c ON m.customer_id = c.id
        WHERE c.phone = ?
    """, (customer_phone,)).fetchall()
    conn.close()
    
    if not rows:
        return "❌ No system found for this number. Contact support."
    
    msg = "📊 *AI24x7 System Status*\n\n"
    for m in rows:
        status_icon = {"online":"🟢","offline":"🔴","warning":"🟡"}.get(m["status"], "⚫")
        last_seen = m["last_heartbeat"]
        if last_seen:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(last_seen)
                mins_ago = int((datetime.now() - dt).total_seconds() / 60)
                last_seen = f"{mins_ago}m ago"
            except:
                pass
        
        msg += f"{status_icon} *{m['hostname']}*\n"
        msg += f"   Cameras: {m['cam_online']}/{m['cam_total']} online\n"
        msg += f"   Last seen: {last_seen or 'Never'}\n"
        msg += f"   Health: {m['health_score']}%\n\n"
    
    return msg

def cmd_alerts(customer_phone, limit=10):
    """Show recent alerts"""
    conn = get_db()
    rows = conn.execute("""
        SELECT a.type, a.severity, a.message, a.status, a.created_at,
               c.name as customer_name
        FROM alerts a
        JOIN customers c ON a.customer_id = c.id
        WHERE c.phone = ?
        ORDER BY a.created_at DESC
        LIMIT ?
    """, (customer_phone, limit)).fetchall()
    conn.close()
    
    if not rows:
        return "🎉 No recent alerts! All clear."
    
    msg = f"🔔 *Last {len(rows)} Alerts*\n\n"
    for a in rows:
        sev = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(a["severity"], "⚪")
        status_icon = {"new":"🆕","acknowledged":"👀","resolved":"✅"}.get(a["status"], "❓")
        time = a["created_at"][:16] if a["created_at"] else "?"
        msg += f"{sev}{status_icon} {a['type'].upper()}\n"
        msg += f"   {a['message'][:80]}\n"
        msg += f"   {time}\n\n"
    
    return msg

def cmd_camera(customer_phone, cam_num):
    """Get specific camera status or screenshot"""
    if not check_feature("cctv_ai_analysis"):
        return "❌ CCTV feature not available in your plan. Upgrade to Business plan."
    
    conn = get_db()
    row = conn.execute("""
        SELECT ca.*, m.customer_id
        FROM cameras ca
        JOIN machines m ON ca.machine_id = m.id
        JOIN customers c ON m.customer_id = c.id
        WHERE c.phone = ?
        AND ca.name LIKE ?
    """, (customer_phone, f"%{cam_num}%")).fetchone()
    conn.close()
    
    if not row:
        return f"❌ Camera '{cam_num}' not found."
    
    status_icon = {"online":"🟢","offline":"🔴","error":"🟠"}.get(row["status"], "⚫")
    msg = f"📹 *Camera {row['name']}*\n"
    msg += f"   Status: {status_icon} {row['status']}\n"
    msg += f"   Location: {row['location'] or 'N/A'}\n"
    msg += f"   Resolution: {row['resolution']}\n"
    if row["last_motion"]:
        msg += f"   Last motion: {row['last_motion'][:16]}\n"
    msg += f"   RTSP: {row['rtsp_url'][:50]}...\n"
    return msg

def cmd_system(customer_phone):
    """Get system health: CPU, RAM, GPU, Storage"""
    conn = get_db()
    rows = conn.execute("""
        SELECT m.*, c.name as customer_name
        FROM machines m
        JOIN customers c ON m.customer_id = c.id
        WHERE c.phone = ?
    """, (customer_phone,)).fetchall()
    conn.close()
    
    if not rows:
        return "❌ No system found."
    
    msg = "🖥️ *System Health*\n\n"
    for m in rows:
        msg += f"📍 *{m['customer_name']}*\n"
        msg += f"   CPU: {m['cpu_model'] or 'N/A'}\n"
        msg += f"   RAM: {m['ram_gb'] or '?'}GB\n"
        msg += f"   GPU: {m['gpu_model'] or 'N/A'}\n"
        msg += f"   GPU VRAM: {m['gpu_vram_gb'] or '?'}GB\n"
        msg += f"   Bandwidth: {m['bandwidth_mbps'] or '?'} Mbps\n"
        msg += f"   Status: {m['status']}\n"
        msg += f"   Health Score: {m['health_score']}%\n\n"
    
    return msg

def cmd_help():
    """Show all available commands"""
    return """🤖 *AI24x7 WhatsApp Bot Commands*

*Status & Info:*
• `status` - All camera statuses
• `system` - CPU/RAM/GPU health
• `alerts` - Recent alert history
• `camera 1` - Camera 1 details
• `camera 2` - Camera 2 details

*Reports:*
• `report today` - Today's summary
• `report week` - Weekly summary
• `bill` - Billing status

*Actions:*
• `restart` - Restart AI agent
• `ack` - Acknowledge latest alert
• `help` - Show this menu

*Just type a command to use it!*"""

def cmd_report(customer_phone, period="today"):
    """Generate daily/weekly report"""
    if not check_feature("daily_reports"):
        return "❌ Reports not available in your plan."
    
    conn = get_db()
    
    if period == "today":
        today = datetime.now().date().isoformat()
        alerts = conn.execute("""
            SELECT COUNT(*) FROM alerts a
            JOIN customers c ON a.customer_id = c.id
            WHERE c.phone = ? AND a.created_at LIKE ?
        """, (customer_phone, today + "%")).fetchone()[0]
        
        known = conn.execute("""
            SELECT COUNT(*) FROM alerts a
            JOIN customers c ON a.customer_id = c.id
            WHERE c.phone = ? AND a.created_at LIKE ? AND a.status = 'resolved'
        """, (customer_phone, today + "%")).fetchone()[0]
        
        unknown = conn.execute("""
            SELECT COUNT(*) FROM alerts a
            JOIN customers c ON a.customer_id = c.id
            WHERE c.phone = ? AND a.created_at LIKE ? AND a.status = 'new'
        """, (customer_phone, today + "%")).fetchone()[0]
        
        cameras = conn.execute("""
            SELECT COUNT(*) FROM cameras ca
            JOIN machines m ON ca.machine_id = m.id
            JOIN customers c ON m.customer_id = c.id
            WHERE c.phone = ? AND ca.status = 'online'
        """, (customer_phone,)).fetchone()[0]
        
        total_cams = conn.execute("""
            SELECT COUNT(*) FROM cameras ca
            JOIN machines m ON ca.machine_id = m.id
            JOIN customers c ON m.customer_id = c.id
            WHERE c.phone = ?
        """, (customer_phone,)).fetchone()[0]
        
        msg = f"📋 *AI24x7 Daily Report*\n📅 {datetime.now().strftime('%d %b %Y')}\n\n"
        msg += f"   🟢 Online Cameras: {cameras}/{total_cams}\n"
        msg += f"   🔔 Total Alerts: {alerts}\n"
        msg += f"   ✅ Resolved: {known}\n"
        msg += f"   🆕 New: {unknown}\n"
        msg += f"   📊 System Uptime: {int(cameras/max(total_cams,1)*100)}%\n"
    
    elif period == "week":
        week_ago = (datetime.now() - timedelta(days=7)).date().isoformat()
        alerts = conn.execute("""
            SELECT COUNT(*) FROM alerts a
            JOIN customers c ON a.customer_id = c.id
            WHERE c.phone = ? AND a.created_at >= ?
        """, (customer_phone, week_ago)).fetchone()[0]
        
        msg = f"📋 *AI24x7 Weekly Report*\n📅 Last 7 days\n\n"
        msg += f"   🔔 Total Alerts: {alerts}\n"
        msg += f"   Type 'report week' for detailed breakdown\n"
    
    else:
        msg = "Usage: `report today` or `report week`"
    
    conn.close()
    return msg

def cmd_billing(customer_phone):
    """Show billing status"""
    conn = get_db()
    bill = conn.execute("""
        SELECT b.*, p.name as plan_name
        FROM billing b
        JOIN plans p ON b.plan_id = p.id
        JOIN customers c ON b.customer_id = c.id
        WHERE c.phone = ?
        ORDER BY b.due_date DESC LIMIT 3
    """, (customer_phone,)).fetchall()
    conn.close()
    
    if not bill:
        return "❌ No billing records found."
    
    msg = "💰 *Billing Status*\n\n"
    for b in bill:
        status = {"paid":"✅","pending":"⏳","overdue":"🔴"}.get(b["status"], "❓")
        msg += f"{status} {b['plan_name']}\n"
        msg += f"   Amount: ₹{b['amount']:,.0f}\n"
        msg += f"   Due: {b['due_date']}\n"
        msg += f"   Status: {b['status']}\n\n"
    
    return msg

def cmd_acknowledge(customer_phone):
    """Acknowledge the latest new alert"""
    conn = get_db()
    alert = conn.execute("""
        SELECT a.id, a.type, a.message, a.created_at
        FROM alerts a
        JOIN customers c ON a.customer_id = c.id
        WHERE c.phone = ? AND a.status = 'new'
        ORDER BY a.created_at DESC LIMIT 1
    """, (customer_phone,)).fetchone()
    conn.close()
    
    if not alert:
        return "✅ No new alerts to acknowledge!"
    
    try:
        import license_client as lc
        lm = lc.LicenseManager()
        lm.db.acknowledge_alert(alert["id"])
    except:
        # Direct DB update
        conn2 = get_db()
        conn2.execute("UPDATE alerts SET status='acknowledged' WHERE id=?", (alert["id"],))
        conn2.commit()
        conn2.close()
    
    return f"✅ Alert acknowledged:\n🔔 {alert['type'].upper()}\n{alert['message'][:100]}"

# ─── Main Router ─────────────────────────
COMMANDS = {
    "status": cmd_status,
    "system": cmd_system,
    "alerts": cmd_alerts,
    "report today": lambda p: cmd_report(p, "today"),
    "report week": lambda p: cmd_report(p, "week"),
    "bill": cmd_billing,
    "billing": cmd_billing,
    "ack": cmd_acknowledge,
    "acknowledge": cmd_acknowledge,
    "help": lambda p: cmd_help(),
    "?": lambda p: cmd_help(),
}

def route_message(text, phone):
    """Route incoming message to appropriate handler"""
    text = text.strip().lower()
    
    # Camera command: "camera 1", "cam 2", etc.
    if text.startswith("camera ") or text.startswith("cam "):
        num = text.split()[1] if len(text.split()) > 1 else "1"
        return cmd_camera(phone, num)
    
    # Generic command
    handler = COMMANDS.get(text)
    if handler:
        return handler(phone)
    
    # Unknown command
    return f"❓ Unknown command: '{text}'\n\nType `help` for all commands."

# ─── Webhook Handler ────────────────────
def handle_wa_webhook(payload):
    """
    Handle incoming WhatsApp webhook.
    payload: WhatsApp Cloud API webhook JSON
    Returns: response text or None
    """
    try:
        entry = payload.get("entry", [])
        if not entry:
            return None
        
        changes = entry[0].get("changes", [])
        if not changes:
            return None
        
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        
        for msg in messages:
            from_num = msg["from"]
            msg_text = msg.get("text", {}).get("body", "")
            msg_id = msg["id"]
            
            # Log message
            print(f"📱 WA from {from_num}: {msg_text}")
            
            # Route and respond
            response_text = route_message(msg_text, from_num)
            
            # Send response via WhatsApp
            wa_send_message(from_num, response_text)
            
            return {"ok": True, "response": response_text}
        
        return {"ok": True, "handled": False}
    
    except Exception as e:
        print(f"❌ WhatsApp webhook error: {e}")
        return {"ok": False, "error": str(e)}

# ─── Flask App ────────────────────────────
def create_app():
    from flask import Flask, request, jsonify
    app = Flask(__name__)
    
    @app.route("/webhook", methods=["GET"])
    def webhook_verify():
        """WhatsApp webhook verification"""
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and token == WA_VERIFY_TOKEN:
            return challenge, 200
        return "Verification failed", 403
    
    @app.route("/webhook", methods=["POST"])
    def webhook_receive():
        """Handle incoming WhatsApp messages"""
        payload = request.get_json()
        result = handle_wa_webhook(payload)
        return jsonify({"status": "ok"}), 200
    
    @app.route("/health")
    def health():
        return {"status": "ok", "service": "AI24x7 WhatsApp Bot", "version": BOT_VERSION}
    
    @app.route("/send-test", methods=["POST"])
    def send_test():
        """Test endpoint to send message to specific number"""
        from flask import request
        data = request.get_json()
        to_num = data.get("to")
        text = data.get("message", "Test from AI24x7 WhatsApp Bot!")
        
        if not to_num:
            return jsonify({"error": "Missing 'to' number"}), 400
        
        result = wa_send_message(to_num, text)
        return jsonify(result)
    
    @app.route("/send-alert", methods=["POST"])
    def send_alert():
        """Send alert to customer when suspicious activity detected"""
        from flask import request
        data = request.get_json()
        to_num = data.get("to")
        alert_type = data.get("type", "suspicious_activity")
        message = data.get("message", "Suspicious activity detected")
        camera = data.get("camera", "Unknown")
        
        text = f"🚨 *AI24x7 Alert*\n\n📷 Camera: {camera}\n🔔 Type: {alert_type.upper()}\n📝 {message}\n\nReply with `ack` to acknowledge."
        
        if to_num:
            result = wa_send_message(to_num, text)
            return jsonify(result)
        
        return jsonify({"error": "Missing 'to' number"}), 400
    
    return app

if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=5054)
