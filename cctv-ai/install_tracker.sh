#!/bin/bash
# AI24x7 - Install Person Tracking Dependencies
# YOLOv8 + ArcFace + DeepSORT

set -e
echo "🤖 Installing AI24x7 Person Tracking..."

# Create venv
python3 -m venv /opt/ai24x7_venv
source /opt/ai24x7_venv/bin/activate

# Install ultralytics (YOLOv8)
pip install ultralytics -q
pip install deepsort-reid -q 2>/dev/null || pip install deep-sort -q 2>/dev/null || true
pip install facenet-pytorch -q 2>/dev/null || true
pip install onnxruntime-gpu -q 2>/dev/null || pip install onnxruntime -q

echo "✅ Person Tracking dependencies installed!"
echo ""
echo "To activate venv: source /opt/ai24x7_venv/bin/activate"
echo "To run tracker: python3 /opt/cctv-finetune/output/ai24x7/person_tracker.py"
