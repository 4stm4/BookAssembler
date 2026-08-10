# Google Colab Setup: OpenAI-compatible API Server via LocalTunnel / ngrok
# Run in Google Colab (GPU T4 / L4 / A100 runtime)

import subprocess
import nest_asyncio
from pyngrok import ngrok

nest_asyncio.apply()

# 1. Токен ngrok (опционально)
NGROK_AUTHTOKEN = "" # Вставьте свой токен ngrok при необходимости
if NGROK_AUTHTOKEN:
    ngrok.set_auth_token(NGROK_AUTHTOKEN)

# 2. Запуск vLLM / Ollama с открытой моделью
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

print(f"🚀 Запуск сервера vLLM для модели: {MODEL_NAME}...")

cmd = f"python3 -m vllm.entrypoints.openai.api_server --model {MODEL_NAME} --port 8000 --max-model-len 4096 --gpu-memory-utilization 0.90"
process = subprocess.Popen(cmd, shell=True)

# 3. Проброс туннеля наружу
http_tunnel = ngrok.connect(8000)
print(f"\n=======================================================")
print(f"✅ ВАШ УДАЛЕННЫЙ KAE COLAB ENDPOINT:")
print(f"🔗 {http_tunnel.public_url}/v1")
print(f"Используйте этот URL в KAE .env файле:")
print(f"AI_BASE_URL={http_tunnel.public_url}/v1")
print(f"AI_MODEL={MODEL_NAME}")
print(f"=======================================================\n")
