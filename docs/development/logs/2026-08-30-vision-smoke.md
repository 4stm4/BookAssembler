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

## Retry & JPEG Optimization (session 3)
- JPEG quality=30, max_dim=512px, DPI 72 → payload ~15KB (was ~200KB PNG)
- Retry: 3 attempts × 20s timeout on /infer only (skip /ocr on timeout)
- Bearer token auth added for Cloudflare-tunneled runners
- rpi5 upload bottleneck: ~1.3 KB/s to Cloudflare → systematic timeouts on some pages
- PDP-11 (34 pages): pages 1–3 classified OK, page 4 = 3/3 timeout (systematic), page 5 saved by retry
- llava:7b on orangepi removed — ARM CPU vision inference impractical (~minutes per image)

## Observations
- Timeout is not random — specific pages consistently fail (likely payload size or tunnel latency spike)
- Two concurrent jobs doubled tunnel load and worsened timeouts
- pyjobkit queue suggested as future improvement for async vision tasks

## Next Steps
- Queue-based approach via pyjobkit for reliable async vision inference
- Consider pre-uploading images to S3/object-store to avoid rpi5 upload bottleneck
