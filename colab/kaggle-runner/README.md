# KAE Kaggle Runner

Артефакты, которые `KaggleKernelBackend` пушит на Kaggle через `kaggle kernels push`.

## Один раз — создать ноутбук в аккаунте

```bash
# 1. Настрой креды: ~/.kaggle/kaggle.json (или KAGGLE_USERNAME/KAGGLE_KEY).
# 2. Пропиши свой owner в kernel-metadata.json (замени REPLACE_WITH на свой username).
# 3. Добавь Secrets в аккаунте Kaggle (Settings → Add-ons → Secrets):
#      KAE_MANAGER_URL   = https://<твой-manager>
#      KAE_RUNNER_TOKEN  = <shared bearer>
# 4. Первый пуш создаст приватный notebook.
kaggle kernels push -p colab/kaggle-runner
```

## Дальше — через Manager

Manager с `KAE_MANAGER_BACKEND=kaggle`, `KAE_KAGGLE_KERNEL=<owner>/kae-runner`,
`KAE_KAGGLE_KERNEL_DIR=colab/kaggle-runner` — при первом `/infer` от KAE
Manager вызовет `KaggleKernelBackend.start()` → `kaggle kernels push` → Kaggle
поставит kernel в очередь, ноутбук поднимет Runner и cloudflared, Runner
пошлёт `POST /runner/announce` на Manager. Manager дождётся `/ready` и
проксирует `/infer`.

По простою `KAE_RUNNER_IDLE_TIMEOUT` (default 900с) Runner завершается сам
(`os._exit(0)`) — Kaggle kernel завершается, GPU-квота перестаёт тикать
(RFC 0022 §5.4 + §9.4).

## Смена модели

Пока `runner.ipynb` использует `EchoLoader` (Stage 2 — заглушка). Реальные
loaders (`Qwen2.5-VL`, `GOT-OCR2.0`) добавляются в `src/agents/runner/loaders/`
и раскомментируются в ячейке 3 ноутбука.
