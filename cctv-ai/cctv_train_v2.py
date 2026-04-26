#!/usr/bin/env python3
"""
AI24x7 CCTV Vision Fine-tuning - Qwen3-VL-8B
"""
import os, sys, json, warnings, torch
warnings.filterwarnings("ignore")

from transformers import (
    AutoProcessor,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
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

# 4-bit Quantization
bnb_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

print("\nLoading model...")
from transformers import Qwen3VLForConditionalGeneration
model = Qwen3VLForConditionalGeneration.from_pretrained(
    MODEL_PATH,
    quantization_config=bnb_cfg,
    device_map="auto",
    torch_dtype=torch.bfloat16,
)
print("Model loaded!")

processor = AutoProcessor.from_pretrained(MODEL_PATH)
model = prepare_model_for_kbit_training(model)

lora_cfg = LoraConfig(
    r=16, lora_alpha=32,
    target_modules=["q_proj","k_proj","v_proj","o_proj"],
    lora_dropout=0.05, bias="none", task_type="CAUSAL_LM"  # CAUSAL_LM = 1
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

class CCTVDataset(Dataset):
    SYSTEM = "You are AI24x7 CCTV Vision Assistant. Analyze this CCTV image and give Hindi report: स्थान, लोग (count+description), वाहन (details ya कोई वाहन नहीं), संदिग्ध गतिविधि (yes/no+details), अलर्ट (urgent message if suspicious)."

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
        img = Image.open(img_path).convert("RGB")

        # Qwen3-VL format: list of content items
        messages = [
            {"role": "user", "content": [
                {"type": "image", "image": img},
                {"type": "text", "text": self.SYSTEM}
            ]}
        ]

        try:
            text = processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            inputs = processor(text=[text], images=[[img]], return_tensors="pt")
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

print("\n🚀 Starting training... (2-3 hours)")
trainer.train()
trainer.save_model(f"{OUTPUT_DIR}/final")
print(f"\n✅ Training complete! Saved to {OUTPUT_DIR}/final")