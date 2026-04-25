"""
AI24x7 SMS Alert Module
Send SMS alerts via multiple SMS gateway providers.
Supports: Damini SMS API (user will provide), Fast2SMS, MSG91
"""
import os, requests, json
from datetime import datetime

# ─── SMS Gateway Base ───────────────────
class SMSGateway:
    """Base SMS gateway class"""
    def __init__(self, api_key, sender_id="AI24X7V"):
        self.api_key = api_key
        self.sender_id = sender_id
        self.base_url = ""
    
    def send(self, to_number, message):
        raise NotImplementedError
    
    def validate_number(self, number):
        """Ensure number is in E.164 format"""
        digits = ''.join(c for c in str(number) if c.isdigit())
        if len(digits) == 10:
            return f"+91{digits}"
        elif digits.startswith("91") and len(digits) == 12:
            return f"+{digits}"
        elif digits.startswith("+"):
            return digits
        return f"+{digits}"


# ─── Damini SMS API ─────────────────────
class DaminiSMSGateway(SMSGateway):
    """
    Damini SMS API integration.
    API details will be provided by customer.
    Base URL format (to be confirmed):
    https://www.daminisms.in/api/sendSMS
    """
    def __init__(self, api_key, sender_id="AI24X7V", template_id=None):
        super().__init__(api_key, sender_id)
        self.template_id = template_id
        self.base_url = "https://www.daminisms.in/api/sendSMS"  # Update when confirmed
    
    def send(self, to_number, message, priority="normal"):
        """
        Send SMS via Damini SMS API
        
        Args:
            to_number: Phone number (10 digit or with country code)
            message: SMS text (max 160 chars for single SMS)
            priority: 'normal', 'high', 'flash'
        
        Returns:
            dict with success/error info
        """
        to = self.validate_number(to_number)
        msg160 = message[:160] if len(message) > 160 else message
        
        payload = {
            "apikey": self.api_key,
            "sendernumber": self.sender_id,
            "message": msg160,
            "destination numbers": to,
        }
        
        if self.template_id:
            payload["templateid"] = self.template_id
        
        try:
            r = requests.post(self.base_url, json=payload, timeout=15)
            result = r.json()
            
            if r.status_code == 200 and result.get("status") == "success":
                return {
                    "success": True,
                    "message_id": result.get("message_id"),
                    "segments": len(message) // 160 + 1,
                    "cost": result.get("cost", 1)
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "details": result
                }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def send_alert(self, to_number, camera_name, alert_type, message):
        """Send formatted alert SMS"""
        text = (
            f"AI24x7 Alert!\n"
            f"Camera: {camera_name}\n"
            f"Type: {alert_type}\n"
            f"{message}\n"
            f"Reply help to 9223492234"
        )
        return self.send(to_number, text)


# ─── Fast2SMS Fallback ──────────────────
class Fast2SMSGateway(SMSGateway):
    """Fast2SMS - alternative SMS gateway"""
    def __init__(self, api_key, sender_id="AI24X7V"):
        super().__init__(api_key, sender_id)
        self.base_url = "https://www.fast2sms.com/dev/sendSms"
    
    def send(self, to_number, message):
        to = self.validate_number(to_number)
        msg160 = message[:160] if len(message) > 160 else message
        
        payload = {
            "authorization": self.api_key,
            "sender_id": self.sender_id,
            "message": msg160,
            "language": "english",
            "route": "p",
            "numbers": to.replace("+", ""),
        }
        
        try:
            r = requests.post(self.base_url, data=payload, timeout=15)
            result = r.json()
            
            if result.get("return"):
                return {"success": True, "id": result.get("request_id")}
            else:
                return {"success": False, "error": result.get("message", "Failed")}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ─── SMS Alert Manager ──────────────────
class SMSAlertManager:
    """
    Central SMS alert manager.
    Try primary gateway, fallback to secondary.
    """
    def __init__(self, primary="damini", secondary="fast2sms"):
        self.primary_name = primary
        self.secondary_name = secondary
        self.primary = None
        self.secondary = None
    
    def configure_damini(self, api_key, sender_id="AI24X7V", template_id=None):
        self.primary = DaminiSMSGateway(api_key, sender_id, template_id)
    
    def configure_fast2sms(self, api_key, sender_id="AI24X7V"):
        self.secondary = Fast2SMSGateway(api_key, sender_id)
    
    def send(self, to_number, message):
        """Send SMS with fallback"""
        if self.primary:
            result = self.primary.send(to_number, message)
            if result.get("success"):
                return result
            print(f"⚠️ Primary SMS fail: {result.get('error')}, trying fallback")
        
        if self.secondary:
            result = self.secondary.send(to_number, message)
            if result.get("success"):
                return result
            print(f"❌ SMS fail: {result.get('error')}")
            return result
        
        return {"success": False, "error": "NO_SMS_GATEWAY_CONFIGURED"}
    
    def send_alert(self, to_number, camera_name, alert_type, message):
        """Send alert formatted SMS"""
        return self.send(to_number, (
            f"AI24x7 Alert!\n"
            f"Camera: {camera_name}\n"
            f"Type: {alert_type}\n"
            f"{message}"
        ))
    
    def send_bulk_alert(self, to_numbers, camera_name, alert_type, message):
        """Send same alert to multiple numbers"""
        msg = f"AI24x7 Alert!\nCamera: {camera_name}\nType: {alert_type}\n{message}"
        results = []
        for num in to_numbers:
            results.append(self.send(num, msg))
        return results


# ─── Flask Server ───────────────────────
def create_sms_server():
    from flask import Flask, request, jsonify
    app = Flask(__name__)
    
    # Global SMS manager
    sms = SMSAlertManager()
    
    @app.route("/sms/health")
    def health():
        return {"status": "ok", "service": "AI24x7 SMS Gateway"}
    
    @app.route("/sms/configure", methods=["POST"])
    def configure():
        """Configure SMS gateway"""
        data = request.get_json()
        provider = data.get("provider", "damini")
        api_key = data.get("api_key")
        sender = data.get("sender_id", "AI24X7V")
        
        if not api_key:
            return jsonify({"error": "API key required"}), 400
        
        if provider == "damini":
            sms.configure_damini(api_key, sender, data.get("template_id"))
            return jsonify({"success": True, "provider": "damini"})
        elif provider == "fast2sms":
            sms.configure_fast2sms(api_key, sender)
            return jsonify({"success": True, "provider": "fast2sms"})
        else:
            return jsonify({"error": f"Unknown provider: {provider}"}), 400
    
    @app.route("/sms/send", methods=["POST"])
    def send_sms():
        """Send single SMS"""
        data = request.get_json()
        to_num = data.get("to")
        msg = data.get("message")
        
        if not to_num or not msg:
            return jsonify({"error": "Missing 'to' or 'message'"}), 400
        
        result = sms.send(to_num, msg)
        return jsonify(result)
    
    @app.route("/sms/send-alert", methods=["POST"])
    def send_alert():
        """Send alert SMS"""
        data = request.get_json()
        to_num = data.get("to")
        camera = data.get("camera", "Unknown")
        alert_type = data.get("type", "suspicious_activity")
        message = data.get("message", "Activity detected")
        
        if not to_num:
            return jsonify({"error": "Missing 'to'"}), 400
        
        result = sms.send_alert(to_num, camera, alert_type, message)
        return jsonify(result)
    
    @app.route("/sms/bulk", methods=["POST"])
    def send_bulk():
        """Send bulk SMS"""
        data = request.get_json()
        to_numbers = data.get("numbers", [])
        message = data.get("message")
        
        if not to_numbers or not message:
            return jsonify({"error": "Missing 'numbers' or 'message'"}), 400
        
        results = sms.send_bulk_alert(to_numbers, message)
        return jsonify({"total": len(to_numbers), "results": results})
    
    return app


# ─── CLI ─────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI24x7 SMS Alert System")
    parser.add_argument("--send", nargs=2, metavar=("TO", "MESSAGE"), help="Send SMS")
    parser.add_argument("--alert", nargs=4, metavar=("TO", "CAMERA", "TYPE", "MSG"), help="Send alert SMS")
    parser.add_argument("--configure", choices=["damini","fast2sms"], help="Configure SMS gateway")
    
    args = parser.parse_args()
    
    sms = SMSAlertManager()
    
    if args.configure == "damini":
        api_key = input("Damini API Key: ").strip()
        sms.configure_damini(api_key)
        print("✅ Damini SMS configured!")
    elif args.configure == "fast2sms":
        api_key = input("Fast2SMS API Key: ").strip()
        sms.configure_fast2sms(api_key)
        print("✅ Fast2SMS configured!")
    elif args.send:
        to_num, msg = args.send
        result = sms.send(to_num, msg)
        if result.get("success"):
            print(f"✅ SMS sent to {to_num}")
        else:
            print(f"❌ SMS fail: {result.get('error')}")
    elif args.alert:
        to_num, camera, alert_type, msg = args.alert
        result = sms.send_alert(to_num, camera, alert_type, msg)
        if result.get("success"):
            print(f"✅ Alert SMS sent to {to_num}")
        else:
            print(f"❌ SMS fail: {result.get('error')}")
    else:
        parser.print_help()
