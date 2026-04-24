# AI24x7 Vision - CCTV AI Analysis

## Quick Install (One Command)
```bash
curl -sL https://raw.githubusercontent.com/Gogreenraghav/ai24x7/main/cctv-ai/install.sh | bash
```

## Requirements (₹42-50K Machine)
- Ubuntu 20.04/22.04 LTS
- 32GB RAM
- 500GB SSD
- No GPU needed (cloud inference)

## Architecture
```
Customer CCTV → Agent (₹42K machine) → Cloud GPU API → Telegram Alerts
```

## Cloud GPU Server
- API: http://43.242.224.231:5050/analyze
- Model: Qwen3VL-8B v10 fine-tuned
- Format: GGUF Q5_K_M

## API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/analyze` | POST | Upload image for analysis |

## Pricing
- Starter: ₹999/month
- Business: ₹2,999/month
- Enterprise: ₹9,999/month

## Support
- Telegram: @ai24x7_vision_bot
