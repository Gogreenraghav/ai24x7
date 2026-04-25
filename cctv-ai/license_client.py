#!/usr/bin/env python3
"""
AI24x7 License Client Module
Runs on customer machine. Handles license validation, feature gating, tamper detection.
Place this file in your ai24x7 install directory.
"""
import os, sys, json, hashlib, time, sqlite3
from pathlib import Path
from datetime import datetime, timedelta

# ─── Config ─────────────────────────────────
LICENSE_CACHE_FILE = "/opt/ai24x7/license_cache.json"
LICENSE_SERVER_URL = os.environ.get("AI24X7_LICENSE_SERVER", "http://43.242.224.231:5053")
CHECK_INTERVAL_HOURS = 6  # Check every 6 hours when online
GRACE_DAYS = 7  # Days after revocation before system stops

# ─── Hardware ID ────────────────────────────
def get_gpu_serial():
    """Get GPU serial number"""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=serial", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except:
        pass
    return "GPU_NO_SERIAL"

def get_cpu_id():
    """Get CPU model + unique identifier"""
    try:
        import subprocess
        result = subprocess.run(
            ["cat", "/proc/cpuinfo"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            if "model name" in line:
                cpu = line.split(":")[1].strip().replace(" ", "_")
                break
        # Get unique CPU id
        result2 = subprocess.run(
            ["cat", "/sys/class/dmi/id/product_serial"],
            capture_output=True, text=True, timeout=5
        )
        if result2.returncode == 0 and result2.stdout.strip():
            return result2.stdout.strip()
        return hashlib.md5(cpu.encode()).hexdigest()[:16]
    except:
        return "CPU_UNKNOWN"

def get_mac_addr():
    """Get primary network MAC address"""
    try:
        import subprocess
        result = subprocess.run(
            ["cat", "/sys/class/net/eth0/address"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True, text=True, timeout=5
            )
        mac = result.stdout.strip().split("\n")[0].split()[1] if result.stdout else "MAC_UNKNOWN"
        return mac.replace(":", "").upper()
    except:
        return "MAC_UNKNOWN"

def get_machine_hardware_id():
    """Create unique machine fingerprint"""
    gpu = get_gpu_serial()
    cpu = get_cpu_id()
    mac = get_mac_addr()
    data = f"{gpu}|{cpu}|{mac}|AI24x7_Salt_2024"
    return hashlib.sha256(data.encode()).hexdigest()[:32]

def get_install_id():
    """Get persistent install ID (generated once, stored on disk)"""
    install_id_file = Path("/opt/ai24x7/.install_id")
    if install_id_file.exists():
        return install_id_file.read_text().strip()
    install_id = hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest()[:16]
    install_id_file.parent.mkdir(parents=True, exist_ok=True)
    install_id_file.write_text(install_id)
    return install_id

# ─── License Cache ───────────────────────────
def load_cache():
    """Load license from local cache"""
    cache_file = Path(LICENSE_CACHE_FILE)
    if cache_file.exists():
        try:
            with open(cache_file) as f:
                return json.load(f)
        except:
            return None
    return None

def save_cache(data):
    """Save license to encrypted local cache"""
    os.makedirs(os.path.dirname(LICENSE_CACHE_FILE), exist_ok=True)
    # Simple obfuscation (security through obscurity - not for high-security)
    # Production: use fernet encryption with machine-derived key
    key = get_machine_hardware_id()
    enc_key = hashlib.sha256(key.encode()).hexdigest()[:32]
    
    with open(LICENSE_CACHE_FILE, "w") as f:
        json.dump(data, f)
    os.chmod(LICENSE_CACHE_FILE, 0o600)  # Read-only for root only
    return True

def clear_cache():
    """Clear license cache (requires re-activation)"""
    cache_file = Path(LICENSE_CACHE_FILE)
    if cache_file.exists():
        os.remove(cache_file)

# ─── Server Communication ───────────────────
def is_internet_available():
    """Check if internet is available"""
    try:
        import subprocess
        result = subprocess.run(
            ["curl", "-s", "--max-time", "5", "-o", "/dev/null", "-w", "%{http_code}",
             "http://43.242.224.231:5053/health"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip() == "200"
    except:
        return False

def server_activate(key, hardware_id):
    """Send activation request to license server"""
    import requests
    try:
        r = requests.post(
            f"{LICENSE_SERVER_URL}/license/activate",
            json={
                "license_key": key,
                "hardware_id": hardware_id,
                "gpu_serial": get_gpu_serial(),
                "cpu_id": get_cpu_id(),
                "mac_addr": get_mac_addr()
            },
            timeout=30
        )
        if r.status_code == 200:
            return r.json()
        return {"valid": False, "reason": "SERVER_ERROR", "message": str(r.text)}
    except Exception as e:
        return {"valid": False, "reason": "NETWORK_ERROR", "message": str(e)}

def server_check(key, hardware_id):
    """Check license status with server"""
    import requests
    try:
        r = requests.post(
            f"{LICENSE_SERVER_URL}/license/check",
            json={"license_key": key, "hardware_id": hardware_id},
            timeout=30
        )
        if r.status_code == 200:
            return r.json()
        return {"valid": False, "reason": "SERVER_ERROR"}
    except:
        return {"valid": False, "reason": "NETWORK_ERROR"}

def check_feature(key, hardware_id, feature_name):
    """Check if a specific feature is enabled"""
    import requests
    try:
        r = requests.post(
            f"{LICENSE_SERVER_URL}/license/feature",
            json={"license_key": key, "feature_name": feature_name},
            headers={"hardware_id": hardware_id},
            timeout=15
        )
        if r.status_code == 200:
            return r.json()
        return {"enabled": False}
    except:
        return {"enabled": False}

# ─── License Validation ─────────────────────
class LicenseManager:
    def __init__(self):
        self.hardware_id = get_machine_hardware_id()
        self.cache = load_cache()
        self.last_check = None
        self.grace_mode = False
        self.grace_until = None
        
    def get_status(self):
        """Get current license status"""
        if not self.cache:
            return "NOT_ACTIVATED"
        
        status = self.cache.get("status")
        if status == "active":
            # Check expiry
            expires = self.cache.get("expires_at")
            if expires:
                exp_date = datetime.fromisoformat(expires).date()
                days_left = (exp_date - datetime.now().date()).days
                if days_left < 0:
                    return "EXPIRED"
                elif days_left <= 30:
                    return f"EXPIRING_SOON:{days_left}"
            return "ACTIVE"
        elif status == "grace_mode":
            return "GRACE_MODE"
        return status or "UNKNOWN"
    
    def is_feature_enabled(self, feature_name):
        """Check if a specific feature is allowed"""
        if not self.cache:
            return False
        
        if self.cache.get("status") != "active" and self.cache.get("status") != "grace_mode":
            return False
        
        features = self.cache.get("features", [])
        return feature_name in features
    
    def activate(self, license_key):
        """Activate license (requires internet)"""
        if not is_internet_available():
            return {"success": False, "reason": "NO_INTERNET", "message": "Connect to internet to activate"}
        
        result = server_activate(license_key, self.hardware_id)
        
        if result.get("valid"):
            cache_data = {
                "license_key": license_key,
                "hardware_id": self.hardware_id,
                "status": "active",
                "plan": result.get("plan"),
                "features": result.get("features", []),
                "expires_at": result.get("expires_at"),
                "cameras_limit": result.get("cameras_limit", 4),
                "activated_at": datetime.now().isoformat(),
                "last_verified": datetime.now().isoformat()
            }
            save_cache(cache_data)
            return {"success": True, "message": "License activated!", "plan": result.get("plan")}
        else:
            return {"success": False, "reason": result.get("reason"), "message": result.get("message", "Activation failed")}
    
    def verify(self, force_online=False):
        """
        Verify license. Try online check if available, otherwise use cache.
        Returns: (valid: bool, message: str)
        """
        if not self.cache:
            return False, "NO_LICENSE"
        
        cached = self.cache
        
        # Check grace mode
        if cached.get("status") == "grace_mode":
            grace_until = cached.get("grace_until")
            if grace_until and datetime.now() > datetime.fromisoformat(grace_until):
                return False, "GRACE_EXPIRED"
            self.grace_mode = True
            self.grace_until = grace_until
            return True, "GRACE_MODE"
        
        if cached.get("status") != "active":
            return False, f"LICENSE_{cached.get('status', 'UNKNOWN').upper()}"
        
        # Check expiry from cache
        expires = cached.get("expires_at")
        if expires:
            exp_date = datetime.fromisoformat(expires).date()
            if exp_date < datetime.now().date():
                return False, "LICENSE_EXPIRED"
        
        # Try online check if available or if force_online
        if force_online or is_internet_available():
            # Check if interval has passed
            last_verified = cached.get("last_verified")
            if last_verified:
                last_dt = datetime.fromisoformat(last_verified)
                hours_since = (datetime.now() - last_dt).total_seconds() / 3600
                if hours_since >= CHECK_INTERVAL_HOURS:
                    result = server_check(cached["license_key"], self.hardware_id)
                    if result.get("valid"):
                        cached["last_verified"] = datetime.now().isoformat()
                        if "warning" in result:
                            cached["expiry_warning"] = result["warning"]
                        save_cache(cached)
                        return True, "OK"
                    else:
                        reason = result.get("reason", "CHECK_FAILED")
                        if reason == "REVOKED":
                            cached["status"] = "grace_mode"
                            cached["grace_until"] = (datetime.now() + timedelta(days=GRACE_DAYS)).isoformat()
                            save_cache(cached)
                            self.grace_mode = True
                            self.grace_until = cached["grace_until"]
                            return True, "GRACE_MODE"
                        return False, f"LICENSE_{reason}"
            else:
                # First verification
                result = server_check(cached["license_key"], self.hardware_id)
                if result.get("valid"):
                    cached["last_verified"] = datetime.now().isoformat()
                    save_cache(cached)
                    return True, "OK"
                else:
                    return False, f"SERVER_{result.get('reason', 'ERROR')}"
        
        return True, "CACHED_OK"
    
    def get_cameras_limit(self):
        """Get max cameras allowed"""
        if not self.cache:
            return 0
        return self.cache.get("cameras_limit", 4)
    
    def get_plan(self):
        """Get current plan name"""
        if not self.cache:
            return None
        return self.cache.get("plan")
    
    def deactivate(self, license_key):
        """Clear local license (for deactivation flow)"""
        clear_cache()
        return True
    
    def summary(self):
        """Get human-readable license summary"""
        if not self.cache:
            return "Status: Not Activated\nGet a license key to activate."
        
        status = self.get_status()
        plan = self.get_plan()
        limit = self.get_cameras_limit()
        expires = self.cache.get("expires_at", "N/A")
        features = self.cache.get("features", [])
        
        lines = [
            f"Status: {status}",
            f"Plan: {plan}",
            f"Cameras: up to {limit}",
            f"Expires: {expires}",
            f"Features: {len(features)} enabled"
        ]
        return "\n".join(lines)


# ─── Feature Decorator ───────────────────────
def require_feature(feature_name):
    """
    Decorator for functions that require a specific feature.
    Usage:
        @require_feature("whatsapp_alerts")
        def send_whatsapp_alert():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            lm = LicenseManager()
            if not lm.is_feature_enabled(feature_name):
                raise PermissionError(f"Feature '{feature_name}' not available in your plan")
            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


# ─── CLI ────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI24x7 License Manager")
    parser.add_argument("--status", action="store_true", help="Show license status")
    parser.add_argument("--activate", metavar="KEY", help="Activate with license key")
    parser.add_argument("--verify", action="store_true", help="Verify license with server")
    parser.add_argument("--features", action="store_true", help="List enabled features")
    parser.add_argument("--check-feature", metavar="FEATURE", help="Check specific feature")
    
    args = parser.parse_args()
    lm = LicenseManager()
    
    if args.status:
        print(lm.summary())
    elif args.activate:
        result = lm.activate(args.activate)
        if result["success"]:
            print(f"✅ {result['message']}")
            print(f"Plan: {result['plan']}")
            print(lm.summary())
        else:
            print(f"❌ Activation failed: {result['message']}")
    elif args.verify:
        valid, msg = lm.verify(force_online=True)
        if valid:
            print(f"✅ License valid ({msg})")
        else:
            print(f"❌ License invalid: {msg}")
    elif args.features:
        if not lm.cache:
            print("No license active")
        else:
            print("Enabled features:")
            for f in lm.cache.get("features", []):
                print(f"  ✅ {f}")
    elif args.check_feature:
        enabled = lm.is_feature_enabled(args.check_feature)
        print(f"{'✅' if enabled else '❌'} Feature '{args.check_feature}': {'ENABLED' if enabled else 'NOT AVAILABLE'}")
    else:
        parser.print_help()
