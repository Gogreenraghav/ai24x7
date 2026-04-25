"""
AI24x7 Multi-Language TTS Module
Supports Hindi, Tamil, Telugu, Kannada, Bengali, Marathi via gTTS (Google Translate TTS)
Also supports Coqui XTTS v2 for higher quality local TTS

Languages supported:
- hi: Hindi
- ta: Tamil
- te: Telugu
- kn: Kannada
- bn: Bengali
- mr: Marathi
- gu: Gujarati
- pa: Punjabi
- ml: Malayalam
- en: English
"""
import os, io, tempfile
import requests
from pathlib import Path
from datetime import datetime

# ─── gTTS (Online - Google Translate TTS) ───
def gtts_speak(text, lang="hi", output_path=None):
    """
    Text-to-speech using Google Translate (gTTS).
    Requires internet. Free, no API key needed.
    """
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang, slow=False)
        
        if output_path:
            tts.save(output_path)
            return {"success": True, "file": output_path, "engine": "gtts"}
        else:
            # Return as bytes
            mp3_buffer = io.BytesIO()
            tts.write_to_fp(mp3_buffer)
            mp3_buffer.seek(0)
            return {"success": True, "audio": mp3_buffer.read(), "engine": "gtts", "lang": lang}
    except ImportError:
        return {"success": False, "error": "gTTS not installed. Run: pip install gtts"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Coqui XTTS v2 (Local - Higher Quality) ───
def xtts_speak(text, lang="hi", speaker_wav=None, output_path=None):
    """
    Text-to-speech using Coqui XTTS v2.
    Local, no internet needed, higher quality voice.
    
    Args:
        text: Text to speak
        lang: Language code (hi, ta, te, kn, en, etc.)
        speaker_wav: Reference audio file for voice cloning (optional)
        output_path: Where to save MP3
    
    Returns:
        dict with success/audio/error
    """
    try:
        from TTS.api import TTS
    except ImportError:
        return {"success": False, "error": "TTS not installed. Run: pip install TTS"}
    
    try:
        # Initialize XTTS
        tts = TTS(model_name="xtts_v2", gpu=True if os.environ.get("CUDA_VISIBLE_DEVICES") else False)
        
        if output_path:
            tts.tts_to_file(text=text, speaker_wav=speaker_wav, file_path=output_path, language=lang)
            return {"success": True, "file": output_path, "engine": "xtts_v2", "lang": lang}
        else:
            # Return audio bytes
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name
            try:
                tts.tts_to_file(text=text, speaker_wav=speaker_wav, file_path=temp_path, language=lang)
                with open(temp_path, "rb") as f:
                    audio_bytes = f.read()
                return {"success": True, "audio": audio_bytes, "engine": "xtts_v2", "lang": lang}
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Edge TTS (Microsoft - High Quality Online) ───
def edge_tts_speak(text, voice="hi-IN-MadhurNeural", output_path=None):
    """
    Text-to-speech using Microsoft Edge TTS.
    High quality, free, requires internet.
    
    Indian voices available:
    - hi-IN-MadhurNeural (Hindi - Female)
    - hi-IN-AmitNeural (Hindi - Male)
    - ta-IN-PallaviNeural (Tamil - Female)
    - te-IN-ShrutiNeural (Telugu - Female)
    - kn-IN-SapnaNeural (Kannada - Female)
    - bn-IN-TanishkaNeural (Bengali - Female)
    - mr-IN-AarohiNeural (Marathi - Female)
    - en-IN-NeerjaExpressive (English - Female)
    """
    try:
        import asyncio
        from edge_tts import EdgeTTS
    except ImportError:
        return {"success": False, "error": "edge-tts not installed. Run: pip install edge-tts"}
    
    try:
        async def _tts():
            tts = EdgeTTS()
            if output_path:
                await tts.tts(text=text, voice=voice, output=output_path)
                return {"success": True, "file": output_path, "engine": "edge_tts", "voice": voice}
            else:
                buffer = io.BytesIO()
                await tts.tts(text=text, voice=voice, output=buffer)
                buffer.seek(0)
                return {"success": True, "audio": buffer.read(), "engine": "edge_tts", "voice": voice}
        
        return asyncio.run(_tts())
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Multi-Language TTS Manager ────────────
LANG_CODES = {
    "hindi": "hi",
    "tamil": "ta", 
    "telugu": "te",
    "kannada": "kn",
    "bengali": "bn",
    "marathi": "mr",
    "gujarati": "gu",
    "punjabi": "pa",
    "malayalam": "ml",
    "english": "en",
    "en": "en",
    "hi": "hi",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "bn": "bn",
    "mr": "mr",
    "gu": "gu",
    "pa": "pa",
    "ml": "ml",
}

EDGE_VOICES = {
    "hi-IN-MadhurNeural": "Hindi (Female)",
    "hi-IN-AmitNeural": "Hindi (Male)",
    "ta-IN-PallaviNeural": "Tamil (Female)",
    "te-IN-ShrutiNeural": "Telugu (Female)",
    "kn-IN-SapnaNeural": "Kannada (Female)",
    "bn-IN-TanishkaNeural": "Bengali (Female)",
    "mr-IN-AarohiNeural": "Marathi (Female)",
    "en-IN-NeerjaExpressive": "English (Female)",
    "en-US-AriaNeural": "English US (Female)",
    "gu-IN-AshaNeural": "Gujarati (Female)",
    "pa-IN-GaganNeural": "Punjabi (Male)",
    "ml-IN-MidhunNeural": "Malayalam (Male)",
}

class TTSManager:
    """
    Central TTS manager - try engines in order of quality.
    1. Edge TTS (best online quality)
    2. XTTS v2 (best local quality)
    3. gTTS (fallback online)
    """
    def __init__(self, preferred_engine="edge"):
        self.preferred_engine = preferred_engine
        self.audio_dir = Path("/opt/ai24x7/tts_audio")
        self.audio_dir.mkdir(parents=True, exist_ok=True)
    
    def speak(self, text, lang="hi", engine=None, output_file=None):
        """
        Convert text to speech.
        
        Args:
            text: Text to convert
            lang: Language (hindi, tamil, telugu, etc.)
            engine: 'edge', 'xtts', 'gtts', or 'auto'
            output_file: Save to file path
        
        Returns:
            dict with success/audio/error
        """
        lang_code = LANG_CODES.get(lang.lower(), lang)
        engine = engine or self.preferred_engine
        
        # Auto-select engine based on availability
        if engine == "auto":
            # Try edge first (best quality online)
            result = edge_tts_speak(text, lang_code, output_file)
            if result.get("success"):
                return result
            
            # Try XTTS (best local)
            result = xtts_speak(text, lang_code, None, output_file)
            if result.get("success"):
                return result
            
            # Fallback to gTTS
            result = gtts_speak(text, lang_code, output_file)
            return result
        
        elif engine == "edge":
            # Map lang to voice
            voice_map = {
                "hi": "hi-IN-MadhurNeural",
                "ta": "ta-IN-PallaviNeural",
                "te": "te-IN-ShrutiNeural",
                "kn": "kn-IN-SapnaNeural",
                "bn": "bn-IN-TanishkaNeural",
                "mr": "mr-IN-AarohiNeural",
                "gu": "gu-IN-AshaNeural",
                "pa": "pa-IN-GaganNeural",
                "ml": "ml-IN-MidhunNeural",
                "en": "en-US-AriaNeural",
            }
            voice = voice_map.get(lang_code, "hi-IN-MadhurNeural")
            return edge_tts_speak(text, voice, output_file)
        
        elif engine == "xtts":
            return xtts_speak(text, lang_code, None, output_file)
        
        elif engine == "gtts":
            return gtts_speak(text, lang_code, output_file)
        
        else:
            return {"success": False, "error": f"Unknown engine: {engine}"}
    
    def speak_to_file(self, text, lang="hi", engine="auto", filename=None):
        """Convert text to audio file"""
        if not filename:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            lang_code = LANG_CODES.get(lang.lower(), lang)
            filename = f"{lang_code}_{ts}.mp3"
        
        output_path = self.audio_dir / filename
        return self.speak(text, lang, engine, str(output_path))
    
    def list_voices(self):
        """List all available voices"""
        return EDGE_VOICES.copy()
    
    def get_supported_languages(self):
        """Get list of supported languages"""
        return {
            "hi": "Hindi (हिन्दी)",
            "ta": "Tamil (தமிழ்)",
            "te": "Telugu (తెలుగు)",
            "kn": "Kannada (ಕನ್ನಡ)",
            "bn": "Bengali (বাংলা)",
            "mr": "Marathi (मराठी)",
            "gu": "Gujarati (ગુજરાતી)",
            "pa": "Punjabi (ਪੰਜਾਬੀ)",
            "ml": "Malayalam (മലയാളം)",
            "en": "English",
        }


# ─── Alert Voice Message Generator ──────────
class AlertVoiceMessage:
    """Generate voice alerts for suspicious activity"""
    
    TEMPLATES = {
        "suspicious_activity": {
            "hi": "Mere aapka CCTV system ne suspicious activity detect ki hai. Camera {camera} mein. Jaldi se check karo.",
            "ta": "Enga CCTV system-la suspicious activity detect aagittu. Camera {camera}. Velaya check pannunga.",
            "te": "Eppudu CCTV system lo suspicious activity detect ayyindi. Camera {camera}. Ki ivvandi.",
            "kn": "Naavu CCTV system-alli suspicious activity nodidda. Camera {camera}-alli. Kelavu time-check madivi.",
            "bn": "Amar CCTV system suspicious activity detect korchhe. Camera {camera}-te. Quick check korun.",
            "en": "Your AI24x7 CCTV system has detected suspicious activity at camera {camera}. Please check immediately.",
        },
        "unknown_person": {
            "hi": "Camera {camera} mein ek unknown person detect hua hai. Please check karein.",
            "ta": "Camera {camera}-la oru unknown person detect aagittu. Check pannungal.",
            "te": "Camera {camera}-ni okati unknown person detect ayyindi. Check cheyyandi.",
            "kn": "Camera {camera}-alli oru unknown person nodidda. Check madiri.",
            "bn": "Camera {camera}-te ekta unknown person detect hochhe. Check korun.",
            "en": "An unknown person was detected at camera {camera}. Please check.",
        },
        "night_movement": {
            "hi": "Camera {camera} mein raat ke 11 baje ke baad movement detect hua hai. Please check karein.",
            "en": "Movement was detected at camera {camera} after 11 PM. Please check.",
        },
        "camera_offline": {
            "hi": "Camera {camera} offline ho gaya hai. Jaldi se check karein.",
            "en": "Camera {camera} has gone offline. Please check.",
        }
    }
    
    def __init__(self, lang="hi", engine="auto"):
        self.lang = lang
        self.tts = TTSManager()
        self.engine = engine
    
    def generate_alert(self, alert_type, camera_name, lang=None):
        """Generate voice alert for an alert type"""
        lang = lang or self.lang
        lang_code = LANG_CODES.get(lang.lower(), lang)
        
        template = self.TEMPLATES.get(alert_type, self.TEMPLATES["suspicious_activity"])
        text = template.get(lang_code, template["en"]).format(camera=camera_name)
        
        return self.tts.speak(text, lang_code, self.engine)
    
    def generate_custom(self, text, lang=None):
        """Generate voice from custom text"""
        lang = lang or self.lang
        lang_code = LANG_CODES.get(lang.lower(), lang)
        return self.tts.speak(text, lang_code, self.engine)


# ─── CLI ─────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI24x7 Multi-Language TTS")
    parser.add_argument("--speak", nargs=2, metavar=("TEXT", "LANG"), help="Speak text")
    parser.add_argument("--langs", action="store_true", help="List supported languages")
    parser.add_argument("--voices", action="store_true", help="List Edge TTS voices")
    parser.add_argument("--engine", choices=["edge","xtts","gtts","auto"], default="auto", help="TTS engine")
    
    args = parser.parse_args()
    tts_manager = TTSManager()
    
    if args.langs:
        langs = tts_manager.get_supported_languages()
        print("\n🌐 Supported Languages:")
        for code, name in langs.items():
            print(f"  {code}: {name}")
    
    elif args.voices:
        voices = tts_manager.list_voices()
        print("\n🎤 Edge TTS Indian Voices:")
        for voice, name in voices.items():
            print(f"  {voice}: {name}")
    
    elif args.speak:
        text, lang = args.speak
        result = tts_manager.speak(text, lang, args.engine)
        if result.get("success"):
            print(f"✅ TTS generated using {result.get('engine')}")
            if result.get("file"):
                print(f"   Saved: {result.get('file')}")
        else:
            print(f"❌ TTS failed: {result.get('error')}")
    
    else:
        print("✅ AI24x7 Multi-Language TTS Ready!")
        print("   Supported: Hindi, Tamil, Telugu, Kannada, Bengali, Marathi + more")
        print()
        print("Usage:")
        print("  python3 multi_tts.py --speak 'Namaste, CCTV system alert' hi")
        print("  python3 multi_tts.py --langs")
        print("  python3 multi_tts.py --voices")
