#!/bin/bash
cd /opt/cctv-finetune/scripts
nohup python3 cctv_api.py > /opt/cctv-finetune/api.log 2>&1 &
echo "API started on port 5050"
sleep 2
curl -s http://localhost:5050/health
