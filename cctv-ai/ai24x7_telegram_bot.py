#!/usr/bin/env python3
"""
AI24x7 CCTV Vision Bot v2 - Fixed unique filenames
"""
import os, json, base64, urllib.request, time, uuid
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = "8751634203:AAEtay1djJH_Do7i_ZkBaX7CGXW6SPmAXTY"
OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3-vl:8b"
API_URL = "http://43.242.224.231:5050"

CCTV_SYSTEM = """You are AI24x7 CCTV Vision Assistant. Analyze CCTV footage and give Hindi report:
- स्थान: [location type]
- लोग: [count + appearance]
- वाहन: [vehicle details ya "कोई वाहन नहीं"]
- संदिग्ध: [yes/no + details]
- अलर्ट: [urgent message if suspicious]

VERY IMPORTANT: Analyze this specific video/image and describe EXACTLY what you see. Do not repeat the same response for different videos. Give UNIQUE analysis based on the actual content."""

def query_vision(prompt, images=None):
    payload = json.dumps({
        "model": MODEL,
        "prompt": CCTV_SYSTEM + f"\n\nUser: {prompt}",
        "images": images or [],
        "stream": False,
        "options": {"temperature": 0.3, "top_p": 0.9}
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read()).get("response", "")

def analyze_image(image_b64):
    payload = json.dumps({
        "image_base64": image_b64,
        "question": "Full CCTV analysis in Hindi. स्थान, लोग, वाहन, संदिग्ध गतिविधि, अलर्ट संदेश दें।"
    }).encode()
    req = urllib.request.Request(API_URL + "/analyze", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read()).get("answer", "Error analyzing")

async def start_cmd(update, ctx):
    await update.message.reply_text(
        "🤖 *AI24x7 CCTV Vision Bot v2*\n\n"
        "📸 Image bhejo → Hindi analysis\n"
        "🎥 Video bhejo → Frame analysis\n"
        "🔗 YouTube link bhejo → Video analyze\n"
        "❓ Question karo → Jawab\n\n"
        "Har video/frame ka UNIQUE answer milega!",
        parse_mode="Markdown"
    )

async def analyze_cmd(update, ctx):
    await update.message.reply_text("📸 Image ya YouTube link bhejo!")

async def status_cmd(update, ctx):
    try:
        req = urllib.request.Request(API_URL + "/health")
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        await update.message.reply_text(
            f"✅ *System Status*\n\n"
            f"Model: {d.get('model')}\n"
            f"Mode: {d.get('mode')}\n"
            f"GPU: {d.get('gpu')}\n"
            f"Status: {d.get('status')}",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_photo(update, ctx):
    await update.message.reply_text("🔍 Analyzing... (10-20 sec)")
    try:
        photo = update.message.photo[-1]
        file = await photo.get_file()
        data = await file.download_as_bytearray()
        b64 = base64.b64encode(data).decode()
        result = analyze_image(b64)
        await update.message.reply_text(f"📸 *Analysis:*\n\n{result}", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def handle_video(update, ctx):
    await update.message.reply_text("🎥 Processing video... (30-60 sec)")
    try:
        uid = str(uuid.uuid4())[:8]
        vid_path = f"/tmp/bot_video_{uid}.mp4"
        frame_dir = f"/tmp/frames_{uid}"
        os.makedirs(frame_dir, exist_ok=True)
        
        video = update.message.video
        file = await video.get_file()
        data = await file.download_as_bytearray()
        with open(vid_path, "wb") as f:
            f.write(data)
        
        # Extract 5 unique frames
        os.system(f"ffmpeg -i {vid_path} -vf 'select=not(mod(n\\,150)),setpts=N/FRAME_RATE/TB' -vsync vfr -frames:v 5 {frame_dir}/frame_%03d.jpg -y 2>/dev/null")
        
        results = []
        frames = sorted([f for f in os.listdir(frame_dir) if f.endswith(".jpg")])
        for i, fr in enumerate(frames, 1):
            frame_path = f"{frame_dir}/{fr}"
            with open(frame_path, "rb") as f:
                img = base64.b64encode(f.read()).decode()
            r = query_vision(f"Frame {i}/{len(frames)}: CCTV analysis in Hindi. Short description of what you see in THIS frame.", images=[img])
            results.append(f"📹 *Frame {i}:* {r[:200]}")
        
        # Cleanup
        os.remove(vid_path)
        for f in frames:
            os.remove(f"{frame_dir}/{f}")
        os.rmdir(frame_dir)
        
        await update.message.reply_text("\n\n".join(results), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def handle_youtube(update, ctx):
    text = update.message.text.strip()
    if "youtube.com" not in text and "youtu.be" not in text:
        await update.message.reply_text("YouTube link bhejo!")
        return
    
    await update.message.reply_text("🔗 YouTube video download kar raha hoon...")
    try:
        uid = str(uuid.uuid4())[:8]
        vid_path = f"/tmp/yt_{uid}.mp4"
        frame_dir = f"/tmp/yt_frames_{uid}"
        os.makedirs(frame_dir, exist_ok=True)
        
        # Download with unique name
        res = os.system(f"yt-dlp -f 'best[height<=720]' -o '{vid_path}' '{text}' 2>/dev/null")
        
        if not os.path.exists(vid_path) or os.path.getsize(vid_path) < 1000:
            await update.message.reply_text("❌ Video download failed. Link check karo.")
            return
        
        # Extract 5 frames from different timestamps
        os.system(f"ffmpeg -i {vid_path} -vf 'select=not(mod(n\\,300)),setpts=N/FRAME_RATE/TB' -vsync vfr -frames:v 5 {frame_dir}/frame_%03d.jpg -y 2>/dev/null")
        
        results = []
        frames = sorted([f for f in os.listdir(frame_dir) if f.endswith(".jpg")])
        for i, fr in enumerate(frames, 1):
            frame_path = f"{frame_dir}/{fr}"
            with open(frame_path, "rb") as f:
                img = base64.b64encode(f.read()).decode()
            r = query_vision(f"Frame {i}/{len(frames)}: CCTV video frame. Describe EXACTLY what you see in THIS specific frame. Unique details only.", images=[img])
            results.append(f"📹 *Frame {i}:* {r[:250]}")
        
        # Cleanup
        os.remove(vid_path)
        for f in frames:
            os.remove(f"{frame_dir}/{f}")
        os.rmdir(frame_dir)
        
        await update.message.reply_text("🔍 *YouTube CCTV Analysis:*\n\n" + "\n\n".join(results), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def handle_text(update, ctx):
    text = update.message.text.strip()
    if "youtube.com" in text or "youtu.be" in text:
        await handle_youtube(update, ctx)
    elif text.startswith("/"):
        pass  # Unknown command
    else:
        await update.message.reply_text("📸 Image/Video/YouTube link bhejo.\n📋 /status - System check\n📖 /start - Help")

async def handle_document(update, ctx):
    doc = update.message.document
    if doc.mime_type and doc.mime_type.startswith("image"):
        await update.message.reply_text("🔍 Analyzing...")
        try:
            file = await doc.get_file()
            data = await file.download_as_bytearray()
            b64 = base64.b64encode(data).decode()
            result = analyze_image(b64)
            await update.message.reply_text(f"📸 *Analysis:*\n\n{result}", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")
    else:
        await update.message.reply_text("Image file bhejo ya YouTube link do.")

def main():
    print("🤖 AI24x7 CCTV Bot v2 starting...")
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("yt", handle_youtube))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.Document.IMAGE, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("✅ Bot running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()