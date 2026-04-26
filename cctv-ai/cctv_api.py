#!/usr/bin/env python3
from flask import Flask, request, jsonify, send_file
from gtts import gTTS
import base64, json, os, time

app = Flask(__name__)

VISION_MODEL = 'qwen3-vl:8b'
OLLAMA_URL = 'http://localhost:11434'

def query_ollama(prompt, images=None):
    payload = json.dumps({'model': VISION_MODEL, 'prompt': prompt, 'images': images or [], 'stream': False}).encode()
    req = urllib.request.Request(OLLAMA_URL+'/api/generate', data=payload, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())

@app.route('/tts', methods=['POST'])
def text_to_speech():
    body = request.get_json()
    text = body.get('text', 'Hello')
    lang = body.get('lang', 'hi')  # hi=hindi, en=english
    try:
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save('/tmp/tts_output.mp3')
        return send_file('/tmp/tts_output.mp3', mimetype='audio/mp3')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cctv-full', methods=['POST'])
def cctv_full():
    body = request.get_json()
    image = body.get('image_base64', '')
    text = body.get('question', 'What do you see? Give short answer.')
    lang = body.get('lang', 'hi')
    
    # Step 1: Vision analysis
    r = query_ollama(f'You are CCTV AI. {text} Short answer only.')
    answer = r.get('response', '')
    
    # Step 2: TTS voice
    tts = gTTS(text=answer[:200], lang=lang, slow=False)
    tts.save('/tmp/tts_answer.mp3')
    
    return send_file('/tmp/tts_answer.mp3', mimetype='audio/mp3')

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'vision': VISION_MODEL, 'tts': 'gTTS-hindi', 'gpu': 'L4-24GB'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)
