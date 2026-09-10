# Постоянный туннель на Manager (rpi5)

> **Статус: отложено (2026-09-05), не работает.** Шаги 1–3 пройдены,
> `cloudflared` держал живые edge-соединения, но `cloudflared tunnel info`
> устойчиво отвечал «does not have any active connection», и внешние запросы
> падали с `530`/`1033` больше часа. Похоже на застрявший account-level
> throttle после нескольких повторных `tunnel login` подряд — сам метод не
> отвергнут. Сертификат, credentials и DNS-запись остались на диске
> (`/home/alex/kae-manager/.cloudflared/`), повторный логин не понадобится.
> Вернулись на `pinggy` (see `docker-compose.manager.yml`, сервис `tunnel`).
> Прежде чем пробовать снова: не гонять `tunnel login` больше одного раза
> подряд — именно это спровоцировало throttle.

Заменяет истекающий раз в час `pinggy` quick tunnel на именованный
Cloudflare Tunnel со стабильным адресом. Требуется один раз: интерактивный
логин в браузере (Cloudflare выдаёт временную ссылку авторизации).

## 1. Логин (один раз, на самом rpi5)

```bash
docker run -d --name cloudflared-login -u 1000:1000 -w /home/cf \
  -e HOME=/home/cf \
  -v /home/alex/kae-manager/.cloudflared:/home/cf \
  cloudflare/cloudflared:latest tunnel login
docker logs -f cloudflared-login   # напечатает ссылку авторизации
```

Права монтирования критичны: без `-u 1000:1000` + `-w /home/cf` + `HOME=/home/cf`
образ (без shell, non-root по умолчанию) падает на `mkdir /.cloudflared:
permission denied` или на попытке писать временный `cloudflared_priv.pem` в
недоступный `cwd`.

После "Success" в браузере:

```bash
docker rm -f cloudflared-login
ls /home/alex/kae-manager/.cloudflared/cert.pem   # должен появиться
```

## 2. Создать именованный туннель

```bash
docker run --rm -u 1000:1000 -w /home/cf -e HOME=/home/cf \
  -v /home/alex/kae-manager/.cloudflared:/home/cf \
  cloudflare/cloudflared:latest tunnel create kae-manager
```

Выведет `<tunnel-id>` и создаст `/home/cf/.cloudflared/<tunnel-id>.json`.

## 3. Config + DNS-маршрут

```bash
cat > /home/alex/kae-manager/.cloudflared/config.yml <<YAML
tunnel: <tunnel-id>
credentials-file: /home/cf/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: kae-manager.<ваша-зона>
    service: http://manager:8080
  - service: http_status:404
YAML

docker run --rm -u 1000:1000 -w /home/cf -e HOME=/home/cf \
  -v /home/alex/kae-manager/.cloudflared:/home/cf \
  cloudflare/cloudflared:latest tunnel route dns kae-manager kae-manager.<ваша-зона>
```

## 4. Поднять постоянно

`docker-compose.manager.yml` уже содержит сервис `cloudflared` — после шагов
1–3 (config.yml на месте):

```bash
cd /home/alex/kae-manager
docker compose -f docker-compose.manager.yml up -d cloudflared
docker compose -f docker-compose.manager.yml stop tunnel   # старый pinggy — только после проверки
curl https://kae-manager.<ваша-зона>/health
```

Адрес `https://kae-manager.<ваша-зона>` стабилен, не истекает — Kaggle
Runner объявляется на него один раз и объявление не требует повтора при
рестарте туннеля.
