# Vision Smoke Test — 30 Aug 2026

## Architecture
- Primary: Kaggle GPU (Qwen2.5-VL-7B) via Cloudflare tunnel → agents.json
- Fallback: Ollama with llava:7b on orangepi (not yet pulled)
- Router: `src/agents/router.py` — `pick()` checks agents.json, probes `/health`

## AgentRouter (src/agents/manager/router.py)
- `discover_vision()`: agents.json → multimodel runners with "vision" role → `/health` probe
- `vision_generate()`: multimodel → POST `/infer`, ollama → POST `/api/generate`
- `route()` returns `{host, model, kind}` — kind is "ollama" or "multimodel"

## Vision API Endpoints
- Multimodel: `POST /infer` with `{image_b64, task: "vision", prompt}`
- Ollama: `POST /api/generate` with `{model, prompt, images: [b64], stream: false}`
- Response: multimodel returns `{text}`, ollama returns `{response}`

## Smoke Test Results
- Kaggle runner (Qwen2.5-VL-7B): registered in agents.json, health OK when running
- Runner idle timeout (900s) causes 502 — pipeline circuit breaker handles gracefully
- PageAgent: 3 consecutive failures → abort (no pipeline hang)
- VisionFallback: skips cleanly when no vision model found
- Pipeline completed without vision: 280 paragraphs, 7 diagrams, 4 tables

## TableDetector Fix (related)
- False positives on diagram labels eliminated
- Single-column short-text blocks without separators → not a table
- Before fix: dozens of false tables; after: 4 real tables in 568-page book

## Next Steps
- Increase KAE_RUNNER_IDLE_TIMEOUT to 3600s in Kaggle secrets
- Full E2E test with live Kaggle runner (requires user to restart notebook)
- Pull llava:7b on orangepi as local fallback when Kaggle is unavailable
