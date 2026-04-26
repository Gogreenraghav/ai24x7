#!/usr/bin/env python3
"""
CCTV Vision API v3 - Optimized with CCTV System Prompt
Uses Qwen3-VL 8B via Ollama with specialized CCTV prompt engineering
"""
import base64, json, urllib.request, os, time
from flask import Flask, request, jsonify, send_file
from gtts import gTTS

app = Flask(__name__)

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3-vl:8b"

# Specialized CCTV system prompt for AI24x7
CCTV_SYSTEM = """You are AI24x7 CCTV Vision Assistant — a professional AI trained for surveillance analysis.

YOUR TASK: Analyze CCTV footage and provide structured, accurate reports in HINDI.

ANALYSIS FRAMEWORK:
1. PEOPLE: Count persons, describe appearance (clothes color, accessories), behavior (normal/suspicious)
2. VEHICLES: Count and type (car/bike/truck/bus), color, position
3. ENVIRONMENT: Indoor/Outdoor, location type (office/shop/parking/street/airport)
4. SUSPICIOUS ACTIVITY: Flag anything unusual (weapon, theft, unauthorized entry, loitering)
5. ALERTS: Generate Hindi alert message if suspicious activity detected

RESPONSE FORMAT (always in Hindi):
- स्थान: [environment description]
- लोग: [count and description]
- वाहन: [vehicle details or "कोई वाहन नहीं"]
- संदिग्ध गतिविधि: [yes/no with details]
- अलर्ट संदेश: [if suspicious, give urgent Hindi alert]

BE SPECIFIC: Give exact counts, colors, positions. Don't say "several" — say "3 लोग".
ALWAYS respond in HINDI unless asked otherwise."""

# Store for conversation context
conversations = {}

def query_vision(prompt, images=None, system=CCTV_SYSTEM):
    full_prompt = f"{system}\n\nUser: {prompt}"
    payload = json.dumps({
        "model": MODEL,
        "prompt": full_prompt,
        "images": images or [],
        "stream": False,
        "options": {"temperature": 0.1, "top_p": 0.8}
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())

@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL,
        "mode": "CCTV-Optimized-v3",
        "gpu": "L4-24GB",
        "fine_tuned_prompt": True
    })

@app.route("/analyze", methods=["POST"])
def analyze():
    body = request.get_json()
    image_b64 = body.get("image_base64", "")
    question = body.get("question", "इस CCTV फुटेज का विश्लेषण करें। क्या दिखाई दे रहा है? संदिग्ध गतिविधि?")
    lang = body.get("lang", "hi")
    
    images = [image_b64] if image_b64 else []
    result = query_vision(question, images)
    answer = result.get("response", "")
    
    # Generate TTS if requested
    if body.get("voice", False):
        try:
            tts = gTTS(text=answer[:300], lang=lang, slow=False)
            tts.save("/tmp/tts_answer.mp3")
            return send_file("/tmp/tts_answer.mp3", mimetype="audio/mp3")
        except:
            pass
    
    return jsonify({
        "answer": answer,
        "question": question,
        "language": lang,
        "model": MODEL
    })

@app.route("/cctv-standard", methods=["POST"])
def cctv_standard():
    """Standard 4-way CCTV detection"""
    body = request.get_json()
    image_b64 = body.get("image_base64", "")
    
    result = query_vision(
        "Quick CCTV analysis: 1) Person detected? how many? 2) Vehicle? what type? 3) Weapon/threat? 4) Suspicious activity? Answer in Hindi, short sentences.",
        images=[image_b64] if image_b64 else []
    )
    
    response = result.get("response", "")
    
    # Parse structured response
    analysis = {
        "raw_response": response,
        "person_detected": "हाँ" in response or "व्यक्ति" in response or "लोग" in response,
        "vehicle_detected": "वाहन" in response or "गाड़ी" in response or "कार" in response or "बस" in response,
        "weapon_detected": "हथियार" in response or "बंदूक" in response or "पिस्तौल" in response,
        "suspicious": "संदिग्ध" in response or "असामान्य" in response,
        "full_report": response
    }
    return jsonify(analysis)

@app.route("/cctv-full", methods=["POST"])
def cctv_full():
    """Full analysis + voice output"""
    body = request.get_json()
    image_b64 = body.get("image_base64", "")
    lang = body.get("lang", "hi")
    
    result = query_vision(
        "Comprehensive CCTV analysis in Hindi. Cover: 1) Scene description, 2) People count + appearance, 3) Vehicle count + type, 4) Suspicious activity, 5) Alert recommendation.",
        images=[image_b64] if image_b64 else []
    )
    
    answer = result.get("response", "")
    
    # Generate audio
    tts = gTTS(text=answer[:300], lang=lang, slow=False)
    tts.save("/tmp/tts_full.mp3")
    
    return send_file("/tmp/tts_full.mp3", mimetype="audio/mp3")

@app.route("/video-analyze", methods=["POST"])
def video_analyze():
    """Analyze video from URL or base64 frames"""
    body = request.get_json()
    video_url = body.get("video_url", "")
    frame_count = body.get("frames", 5)
    
    # Download video frames using system calls
    import subprocess
    frames = []
    
    if video_url:
        # Download and extract frames
        subprocess.run([
            "yt-dlp", "-f", "best[height<=720]",
            "-o", "/tmp/video_analysis.mp4",
            video_url
        ], capture_output=True)
        
        # Extract frames
        subprocess.run([
            "ffmpeg", "-i", "/tmp/video_analysis.mp4",
            "-vf", f"select=not(mod(n\\,{max(1, 900//frame_count)})),setpts=N/FRAME_RATE/TB",
            "-vsync", "vfr",
            "-frames:v", str(frame_count),
            f"/tmp/vid_frame_%03d.jpg"
        ], capture_output=True, cwd="/tmp")
        
        # Analyze each frame
        results = []
        for i in range(1, frame_count + 1):
            frame_path = f"/tmp/vid_frame_{i:03d}.jpg"
            if os.path.exists(frame_path):
                with open(frame_path, "rb") as f:
                    img = base64.b64encode(f.read()).decode()
                r = query_vision(
                    "CCTV short analysis: People? Vehicle? Suspicious? Answer in Hindi, one line.",
                    images=[img]
                )
                results.append({
                    "frame": i,
                    "analysis": r.get("response", "")[:200]
                })
        
        return jsonify({"frame_count": len(results), "frames": results})
    
    return jsonify({"error": "No video URL provided"})

if __name__ == "__main__":
    print("=" * 50)
    print("AI24x7 CCTV Vision API v3")
    print("Optimized with CCTV System Prompt")
    print("GPU: NVIDIA L4 24GB")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
