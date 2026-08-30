# Vision Smoke Test — 30 Aug 2026

## Architecture
- First tier: Ollama with llava:7b on orangepi (192.168.88.199:11434)
- Second tier: Kaggle GPU (opt-in, KAE_MANAGER_BACKEND=kaggle)

## AgentRouter
- Probes /api/tags on each configured host
- Matches model names against VISION_MODELS set (llava variants)
- Routes "vision" role to first host with a vision model

## Vision API
- `vision_generate(host, model, prompt, image_b64)` → POST /api/generate
- `formula_vision_fallback(host, model, image_bytes)` → LaTeX extraction prompt

## Smoke Status
- Router unit tests: 10/10 pass (mocked urllib)
- Live test requires `ssh orangepi 'ollama pull llava:7b'` (~4.5GB download)
- Formula fallback prompt tested via mock — real inference pending model pull

## Next Steps
- Pull llava:7b on orangepi when bandwidth is available
- Wire formula_vision_fallback into FormulaDetector for needs_vision_ocr blocks
- E2E test with PDP-11 manual pages containing schematics
