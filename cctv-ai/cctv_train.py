#!/usr/bin/env python3
"""
AI24x7 CCTV Vision Fine-tuning
Qwen3-VL-8B with QLoRA on L4 GPU
"""
import os, sys, json, warnings, torch
warnings.filterwarnings("ignore")
os.environ["HF_HOME"] = "/opt/cctv-finetune/hf_cache"
os.environ["TRANSFORMERS_CACHE"] = "/opt/cctv-finetune/hf_cache"

from transformers import (
    AutoProcessor,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from qwen_vl_utils import process_vision_info
from PIL import Image
from torch.utils.data import Dataset

MODEL_PATH = "/opt/cctv-finetune/models/Qwen3-VL-8B"
OUTPUT_DIR = "/opt/cctv-finetune/output/cctv-vision-v1"
DATA_DIR = "/opt/cctv-finetune/dataset/received"

print("=" * 60)
print("AI24x7 CCTV Vision Fine-tuning")
print(f"Model: {MODEL_PATH}")
print(f"Output: {OUTPUT_DIR}")
print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"VRAM: {torch.cuda.get_device_properties(0).total_memory/1e9:.1f}GB")
print("=" * 60)

# 4-bit Quantization (for L4 24GB)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

print("\nLoading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    quantization_config=bnb_config,
    device_map="auto",
    torch_dtype=torch.bfloat16,
    trust_remote_code=True,
)
print("Model loaded!")

processor = AutoProcessor.from_pretrained(MODEL_PATH, trust_remote_code=True)
model = prepare_model_for_kbit_training(model)

# LoRA Config
lora_cfg = LoraConfig(
    r=16, lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

class CCTVDataset(Dataset):
    def __init__(self, image_dir, max_samples=30):
        self.images = []
        for f in sorted(os.listdir(image_dir)):
            if f.endswith(".jpg") and not f.startswith("yt") and not f.startswith("v"):
                self.images.append(os.path.join(image_dir, f))
        self.images = self.images[:max_samples]
        print(f"Dataset: {len(self.images)} images")
    
    def __len__(self):
        return len(self.images)
    
    def __getitem__(self, idx):
        img_path = self.images[idx]
        conv = [{
            "role": "user",
            "content": [
                {"type": "image", "image": img_path},
                {"type": "text", "text": "You are AI24x7 CCTV Vision Assistant. Analyze this CCTV image and give Hindi report: स्थान, लोग (count+description), वाहन (details ya कोई वाहन नहीं), संदिग्ध गतिविधि (yes/no+details), अलर्ट (urgent message if suspicious)."}
            ]
        }]
        try:
            text = processor.apply_chat_template(conv, add_generation_prompt=True, tokenize=False)
            img_in, vid_in = process_vision_info(conv)
            inputs = processor(text=[text], images=img_in, padding=True, return_tensors="pt")
            inputs = {k: v.cuda() for k, v in inputs.items()}
            return inputs
        except Exception as e:
            print(f"Error {os.path.basename(img_path)}: {e}")
            return {"input_ids": torch.zeros(1,10), "attention_mask": torch.zeros(1,10)}

dataset = CCTVDataset(DATA_DIR, max_samples=30)
data_collator = DataCollatorForSeq2Seq(processor, model=model)

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    num_train_epochs=2,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    learning_rate=2e-4,
    warmup_ratio=0.1,
    lr_scheduler_type="cosine",
    bf16=True,
    logging_steps=5,
    save_strategy="epoch",
    save_total_limit=2,
    optim="paged_adamw_8bit",
    report_to="none",
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant": False},
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    data_collator=data_collator,
)

print("\n🚀 Starting training...")
trainer.train()
trainer.save_model(f"{OUTPUT_DIR}/final")
print(f"\n✅ Training complete! Saved to {OUTPUT_DIR}/final")