#!/usr/bin/env python3
"""
CCTV Vision API v4 — Uses fine-tuned Qwen3-VL LoRA adapter
Endpoint: POST /analyze
"""
import os, sys, io, json, traceback, gc
sys.path.insert(0, '/opt/cctv-finetune/workspace')
os.environ['PYTORCH_DYNAMO_ENABLED'] = '0'
os.environ['TORCHINDUCTOR_ENABLED'] = '0'

from flask import Flask, request, jsonify
from PIL import Image
import torch
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration, BitsAndBytesConfig
from peft import PeftModel

app = Flask(__name__)

MODEL_PATH = '/opt/cctv-finetune/models/Qwen3-VL-8B/'
ADAPTER_PATH = '/opt/cctv-finetune/output/fine_tuned_cctv_v10/final_model'

print("Loading base model...")
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
base = Qwen3VLForConditionalGeneration.from_pretrained(
    MODEL_PATH, device_map="auto", torch_dtype=torch.float16,
    quantization_config=bnb, attn_implementation="eager")

print("Loading fine-tuned adapter...")
model = PeftModel.from_pretrained(base, ADAPTER_PATH)
model.eval()
print(f"Model + Adapter loaded! VRAM: {torch.cuda.memory_allocated()/1e9:.1f}GB")

proc = AutoProcessor.from_pretrained(MODEL_PATH)
print("Processor loaded!")

PROMPT = "इस image में क्या दिख रहा है? Objects, persons, vehicles, text, layout — सब कुछ बताइए।"

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "model": "Qwen3-VL-8B-v10-finetuned", "adapter": ADAPTER_PATH})

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        if 'image' not in request.files and 'image_url' not in request.form:
            return jsonify({"error": "No image provided"}), 400
        
        if 'image' in request.files:
            file = request.files['image']
            img = Image.open(file.stream).convert('RGB')
        else:
            import urllib.request
            url = request.form['image_url']
            with urllib.request.urlopen(url, timeout=10) as resp:
                img = Image.open(resp.read()).convert('RGB')
        
        text = (
            "<|im_start|>user\n"
            "<|vision_start|><|image_pad|><|vision_end|>\n"
            + PROMPT + "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )
        inputs = proc(text=[text], images=[img], return_tensors='pt',
                      padding=False, truncation=False)
        inputs = {k: v.cuda() for k, v in inputs.items()}
        
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=200,
                do_sample=False,
                pad_token_id=151645,
                eos_token_id=151645,
            )
        
        answer = proc.tokenizer.decode(out[0], skip_special_tokens=True)
        # Clean
        for tok in ["<|im_start|>", "<|im_end|>", "<|vision_start|>",
                    "<|vision_end|>", "<|vision_pad|>", "<|image_pad|>"]:
            answer = answer.replace(tok, "")
        answer = answer.strip()
        
        return jsonify({
            "analysis": answer,
            "model": "Qwen3-VL-8B-v10-finetuned",
            "status": "success"
        })
    
    except Exception as e:
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route('/', methods=['GET'])
def index():
    return jsonify({
        "service": "AI24x7 Vision CCTV API",
        "version": "v4-finetuned",
        "model": "Qwen3-VL-8B + LoRA adapter",
        "endpoints": ["/health", "/analyze"]
    })

if __name__ == '__main__':
    print("Starting CCTV API v4 on port 5050...")
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)