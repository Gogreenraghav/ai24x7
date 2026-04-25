#!/usr/bin/env python3
"""
AI24x7 License Server
Runs on GPU server: http://43.242.224.231:5053
Handles license generation, activation, deactivation
"""
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
import sqlite3, hashlib, secrets, uuid, json
from pathlib import Path
import os

app = FastAPI(title="AI24x7 License Server", version="1.0.0")
DB_PATH = Path(__file__).parent / "ai24x7_licenses.db"

# ─── DB Setup ────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT UNIQUE NOT NULL,
            customer_name TEXT,
            customer_email TEXT,
            customer_phone TEXT,
            hardware_id TEXT,
            plan TEXT NOT NULL DEFAULT 'starter',
            features_json TEXT,
            status TEXT DEFAULT 'unused' CHECK(status IN ('unused','active','expired','revoked')),
            generated_at TEXT DEFAULT (datetime('now')),
            activated_at TEXT,
            expires_at TEXT,
            deactivated_at TEXT,
            deactivated_by TEXT,
            deactivation_reason TEXT,
            last_check_at TEXT,
            grace_mode_until TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS license_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key TEXT NOT NULL,
            hardware_id TEXT,
            result TEXT,
            checked_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()

    # Create default admin
    admin_exists = conn.execute(
        "SELECT id FROM admin_users WHERE username=?", ('arjun',)
    ).fetchone()
    if not admin_exists:
        pw_hash = hashlib.sha256('ai24x7admin2024'.encode()).hexdigest()
        conn.execute("INSERT INTO admin_users (username, password_hash, role) VALUES (?,?,?)",
                    ('arjun', pw_hash, 'super_admin'))
        conn.commit()
    conn.close()

init_db()

# ─── Plan Definitions ────────────────────────
PLANS = {
    "starter": {
        "name": "Vision Only - Starter",
        "cameras": 4,
        "monthly_fee": 999,
        "features": [
            "cctv_ai_analysis", "telegram_alerts", "4_cameras",
            "daily_reports", "local_dashboard", "person_detection"
        ]
    },
    "business": {
        "name": "Vision+Voice - Business",
        "cameras": 10,
        "monthly_fee": 2999,
        "features": [
            "cctv_ai_analysis", "telegram_alerts", "10_cameras",
            "daily_reports", "local_dashboard", "person_detection",
            "voice_ai", "stt", "tts", "voice_commands"
        ]
    },
    "enterprise": {
        "name": "Vision+Voice+Extra - Enterprise",
        "cameras": 999,
        "monthly_fee": 9999,
        "features": [
            "cctv_ai_analysis", "telegram_alerts", "unlimited_cameras",
            "daily_reports", "local_dashboard", "person_detection",
            "voice_ai", "stt", "tts", "voice_commands",
            "whatsapp_alerts", "auto_call", "multi_site", "white_label"
        ]
    },
    "trial": {
        "name": "Trial",
        "cameras": 2,
        "monthly_fee": 0,
        "features": ["cctv_ai_analysis", "telegram_alerts", "2_cameras", "7_day_trial"]
    }
}

def generate_key(plan):
    """Generate a unique license key: AI24-PLAN-XXXX-XXXX-XXXX"""
    prefix = f"AI24-{plan[:3].upper()}"
    random_part = secrets.token_hex(6).upper()
    key = f"{prefix}-{random_part[:4]}-{random_part[4:8]}-{random_part[8:12]}"
    return key

def get_hardware_hash(gpu_serial, cpu_id, mac_addr):
    """Create unique machine fingerprint"""
    data = f"{gpu_serial}|{cpu_id}|{mac_addr}|AI24x7_Salt_2024"
    return hashlib.sha256(data.encode()).hexdigest()[:32]

def plan_features(plan):
    return json.dumps(PLANS.get(plan, PLANS["starter"])["features"])

# ─── Pydantic Models ───────────────────────
class GenerateRequest(BaseModel):
    customer_name: str
    customer_email: Optional[str] = ""
    customer_phone: Optional[str] = ""
    plan: str = "starter"
    validity_months: int = 12

class ActivateRequest(BaseModel):
    license_key: str
    hardware_id: str
    gpu_serial: str = ""
    cpu_id: str = ""
    mac_addr: str = ""

class CheckRequest(BaseModel):
    license_key: str
    hardware_id: str

class DeactivateRequest(BaseModel):
    license_key: str
    reason: str = ""

class FeatureRequest(BaseModel):
    license_key: str
    feature_name: str

# ─── Auth Middleware ────────────────────────
def verify_admin(x_admin_key: str = Header(None)):
    if x_admin_key != "ai24x7-admin-key-2024":
        raise HTTPException(status_code=401, detail="Invalid admin key")

# ─── API Endpoints ───────────────────────────

@app.get("/")
def root():
    return {
        "service": "AI24x7 License Server",
        "version": "1.0.0",
        "status": "running",
        "time": datetime.now().isoformat()
    }

@app.get("/health")
def health():
    return {"status": "ok"}

# ─── LICENSE GENERATION ──────────────────────
@app.post("/admin/license/generate")
def generate_license(data: GenerateRequest, admin_key: str = Header(None)):
    verify_admin(admin_key)
    
    if data.plan not in PLANS:
        raise HTTPException(status_code=400, detail=f"Invalid plan. Options: {list(PLANS.keys())}")
    
    key = generate_key(data.plan)
    plan_info = PLANS[data.plan]
    expires = (datetime.now() + timedelta(days=30*data.validity_months)).date().isoformat()
    
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO licenses (license_key, customer_name, customer_email, customer_phone, plan, features_json, status, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, 'unused', ?)
    """, (key, data.customer_name, data.customer_email, data.customer_phone, data.plan, plan_features(data.plan), expires))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "license_key": key,
        "plan": data.plan,
        "plan_name": plan_info["name"],
        "features": plan_info["features"],
        "expires_at": expires,
        "customer": data.customer_name
    }

@app.get("/admin/licenses")
def list_licenses(admin_key: str = Header(None)):
    verify_admin(admin_key)
    conn = get_db()
    licenses = conn.execute("SELECT * FROM licenses ORDER BY generated_at DESC").fetchall()
    conn.close()
    return [dict(l) for l in licenses]

@app.get("/admin/licenses/{key}")
def get_license(key: str, admin_key: str = Header(None)):
    verify_admin(admin_key)
    conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE license_key=?", (key,)).fetchone()
    conn.close()
    if not lic:
        raise HTTPException(status_code=404, detail="License not found")
    return dict(lic)

# ─── LICENSE ACTIVATION ──────────────────────
@app.post("/license/activate")
def activate_license(data: ActivateRequest):
    """
    Customer machine calls this ONCE when first connected to internet.
    Binds license to hardware.
    """
    conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE license_key=?", (data.license_key,)).fetchone()
    
    if not lic:
        conn.close()
        return {"valid": False, "reason": "INVALID_KEY", "message": "License key not found"}
    
    lic = dict(lic)
    
    if lic["status"] == "active" and lic["hardware_id"] and lic["hardware_id"] != data.hardware_id:
        conn.close()
        return {"valid": False, "reason": "ALREADY_USED", "message": "This license is already activated on another machine"}
    
    if lic["status"] == "revoked":
        conn.close()
        return {"valid": False, "reason": "REVOKED", "message": "License has been revoked"}
    
    if lic["status"] == "expired":
        conn.close()
        return {"valid": False, "reason": "EXPIRED", "message": "License has expired"}
    
    if lic["status"] == "active":
        # Re-confirming existing activation
        features = json.loads(lic["features_json"] or "[]")
        return {
            "valid": True,
            "already_active": True,
            "features": features,
            "plan": lic["plan"],
            "expires_at": lic["expires_at"],
            "grace_mode_until": lic["grace_mode_until"]
        }
    
    # Activate!
    conn.execute("""
        UPDATE licenses SET 
            status='active',
            hardware_id=?,
            activated_at=?,
            last_check_at=?
        WHERE license_key=?
    """, (data.hardware_id, datetime.now().isoformat(), datetime.now().isoformat(), data.license_key))
    conn.commit()
    conn.close()
    
    features = json.loads(lic["features_json"] or "[]")
    return {
        "valid": True,
        "already_active": False,
        "features": features,
        "plan": lic["plan"],
        "cameras_limit": PLANS[lic["plan"]]["cameras"],
        "expires_at": lic["expires_at"],
        "message": "License activated successfully"
    }

# ─── LICENSE CHECK (Background Validation) ───
@app.post("/license/check")
def check_license(data: CheckRequest):
    """
    Customer machine calls this periodically when online.
    """
    conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE license_key=?", (data.license_key,)).fetchone()
    
    if not lic:
        conn.close()
        return {"valid": False, "reason": "INVALID_KEY"}
    
    lic = dict(lic)
    
    # Check hardware match
    if lic["hardware_id"] and lic["hardware_id"] != data.hardware_id:
        conn.close()
        return {"valid": False, "reason": "HARDWARE_MISMATCH", "message": "License bound to different machine"}
    
    # Check status
    if lic["status"] == "revoked":
        conn.execute("UPDATE license_checks SET result='REVOKED' WHERE license_key=?", (data.license_key,))
        conn.commit()
        conn.close()
        return {"valid": False, "reason": "REVOKED", "grace_days": 0}
    
    if lic["status"] == "expired":
        conn.execute("UPDATE license_checks SET result='EXPIRED' WHERE license_key=?", (data.license_key,))
        conn.commit()
        conn.close()
        return {"valid": False, "reason": "EXPIRED", "grace_days": 0}
    
    # Check expiry date
    if lic["expires_at"]:
        exp = datetime.fromisoformat(lic["expires_at"]).date()
        today = datetime.now().date()
        days_left = (exp - today).days
        if days_left < 0:
            conn.execute("UPDATE licenses SET status='expired' WHERE license_key=?", (data.license_key,))
            conn.commit()
            conn.close()
            return {"valid": False, "reason": "EXPIRED", "grace_days": 0}
        elif days_left <= 30:
            conn.close()
            return {"valid": True, "warning": "EXPIRING_SOON", "days_left": days_left}
    
    # Update last check
    conn.execute("UPDATE licenses SET last_check_at=? WHERE license_key=?", 
                 (datetime.now().isoformat(), data.license_key))
    conn.execute("INSERT INTO license_checks (license_key, hardware_id, result) VALUES (?,?, 'OK')",
                 (data.license_key, data.hardware_id))
    conn.commit()
    conn.close()
    
    features = json.loads(lic["features_json"] or "[]")
    return {
        "valid": True,
        "features": features,
        "plan": lic["plan"],
        "expires_at": lic["expires_at"],
        "status": lic["status"]
    }

# ─── FEATURE CHECK ───────────────────────────
@app.post("/license/feature")
def check_feature(data: FeatureRequest, hardware_id: str = Header(None)):
    """Check if a specific feature is enabled for this license"""
    conn = get_db()
    lic = conn.execute("""
        SELECT l.* FROM licenses l
        WHERE l.license_key=? AND l.hardware_id=?
    """, (data.license_key, hardware_id)).fetchone()
    conn.close()
    
    if not lic:
        raise HTTPException(status_code=401, detail="Invalid license or hardware")
    
    lic = dict(lic)
    features = json.loads(lic["features_json"] or "[]")
    
    return {
        "feature_name": data.feature_name,
        "enabled": data.feature_name in features,
        "all_features": features
    }

# ─── DEACTIVATION ────────────────────────────
@app.post("/admin/license/deactivate")
def deactivate_license(key: str, reason: str = "", admin_key: str = Header(None)):
    verify_admin(admin_key)
    
    conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE license_key=?", (key,)).fetchone()
    if not lic:
        conn.close()
        raise HTTPException(status_code=404, detail="License not found")
    
    grace = (datetime.now() + timedelta(days=7)).isoformat()
    conn.execute("""
        UPDATE licenses SET
            status='revoked',
            deactivated_at=?,
            deactivated_by='admin',
            deactivation_reason=?,
            grace_mode_until=?
        WHERE license_key=?
    """, (datetime.now().isoformat(), reason, grace, key))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "message": f"License {key} deactivated. Grace period until {grace}",
        "customer_will_be_locked_in": "7 days"
    }

# ─── RENEWAL ─────────────────────────────────
@app.post("/admin/license/renew")
def renew_license(key: str, months: int = 12, admin_key: str = Header(None)):
    verify_admin(admin_key)
    
    conn = get_db()
    lic = conn.execute("SELECT * FROM licenses WHERE license_key=?", (key,)).fetchone()
    if not lic:
        conn.close()
        raise HTTPException(status_code=404, detail="License not found")
    
    lic = dict(lic)
    current_exp = datetime.fromisoformat(lic["expires_at"]).date() if lic["expires_at"] else datetime.now().date()
    new_exp = (current_exp + timedelta(days=30*months)).isoformat()
    
    conn.execute("""
        UPDATE licenses SET
            status='active',
            expires_at=?,
            grace_mode_until=NULL
        WHERE license_key=?
    """, (new_exp, key))
    conn.commit()
    conn.close()
    
    return {
        "success": True,
        "license_key": key,
        "new_expires_at": new_exp,
        "months_added": months
    }

# ─── STATS ──────────────────────────────────
@app.get("/admin/stats")
def admin_stats(admin_key: str = Header(None)):
    verify_admin(admin_key)
    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0],
        "active": conn.execute("SELECT COUNT(*) FROM licenses WHERE status='active'").fetchone()[0],
        "unused": conn.execute("SELECT COUNT(*) FROM licenses WHERE status='unused'").fetchone()[0],
        "revoked": conn.execute("SELECT COUNT(*) FROM licenses WHERE status='revoked'").fetchone()[0],
        "expired": conn.execute("SELECT COUNT(*) FROM licenses WHERE status='expired'").fetchone()[0],
        "expiring_soon": conn.execute(
            "SELECT COUNT(*) FROM licenses WHERE status='active' AND expires_at < ?",
            ((datetime.now() + timedelta(days=30)).date().isoformat(),)
        ).fetchone()[0],
        "plans": {}
    }
    for plan in PLANS:
        count = conn.execute(
            "SELECT COUNT(*) FROM licenses WHERE plan=? AND status='active'", (plan,)
        ).fetchone()[0]
        stats["plans"][plan] = count
    conn.close()
    return stats

# ─── TRIAL LICENSE ──────────────────────────
@app.post("/admin/license/trial")
def generate_trial(admin_key: str = Header(None)):
    verify_admin(admin_key)
    
    key = generate_key("trial")
    expires = (datetime.now() + timedelta(days=7)).date().isoformat()
    
    conn = get_db()
    conn.execute("""
        INSERT INTO licenses (license_key, plan, features_json, status, expires_at)
        VALUES (?, 'trial', ?, 'unused', ?)
    """, (key, plan_features("trial"), expires))
    conn.commit()
    conn.close()
    
    return {
        "license_key": key,
        "plan": "trial",
        "expires_at": expires,
        "note": "7 day trial, 2 cameras max"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5053)
