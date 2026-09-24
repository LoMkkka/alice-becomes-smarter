# Alice Becomes Smarter

Готовый bridge, который подключает пользовательский навык **Яндекс Алисы** к LLM через **Groq API**.

Работает на обычном Ubuntu/Debian VPS, **Yandex Cloud и домен не обязательны**: можно использовать публичный IPv4 с сертификатом Let's Encrypt непосредственно на IP.

```text
Яндекс Станция / Алиса
        ↓
Яндекс Диалоги
        ↓ HTTPS
https://SERVER_IP/webhook
        ↓
FastAPI + Nginx на вашем VPS
        ↓
Groq API → Qwen
        ↓
ответ возвращается Алисе и озвучивается
```

## Что умеет

- внешний HTTPS webhook для навыка Алисы;
- быстрые ответы через Groq;
- несколько реплик контекста внутри текущей сессии;
- запуск без домена — на публичном IPv4;
- Let's Encrypt IP certificate + автоматическое обновление;
- systemd + Nginx;
- редактируемый `prompt.txt`;
- `/health` для проверки состояния;
- безопасный fallback при таймауте/ошибке модели.

> Яндекс Диалоги ждут ответ навыка только **4,5 секунды**, поэтому в проекте стоит жёсткий таймаут модели 3,3 секунды. Поле `response.text` дополнительно ограничивается 1000 символами (лимит Яндекса — 1024).

## Требования

- Ubuntu 22.04/24.04 или актуальный Debian;
- публичный статический IPv4;
- входящие TCP-порты `80` и `443`;
- SSH-доступ с `root`/`sudo`;
- Groq API key;
- аккаунт Яндекса.

Если на сервере уже работают сайты/Nginx, внимательно проверьте конфиги: installer рассчитан прежде всего на отдельный VPS.

## Быстрая установка

### 1. Получите Groq API key

Создайте ключ в Groq Console:

https://console.groq.com/keys

Не публикуйте ключ в GitHub и не отправляйте его другим людям.

### 2. Склонируйте проект

```bash
git clone https://github.com/LoMkkka/alice-becomes-smarter.git
cd alice-becomes-smarter
```

### 3. Запустите installer

```bash
chmod +x install.sh
sudo ./install.sh
```

Installer спросит публичный IPv4, email для Let's Encrypt, Groq API key и модель Groq.

После установки:

```text
Health:  https://SERVER_IP/health
Webhook: https://SERVER_IP/webhook
```

## Firewall и VPN

Installer **не включает UFW самостоятельно**. Если UFW уже активен, он добавит только `80/tcp` и `443/tcp`.

Это сделано специально: `ufw enable` на сервере с WireGuard/AmneziaWG может заблокировать UDP-порт VPN или forwarding.

Минимально необходимы:

```text
22/tcp   SSH
80/tcp   Let's Encrypt
443/tcp  webhook Алисы
```

VPN-порты и route/NAT правила настраиваются отдельно.

## Проверка

Локальный health check:

```bash
curl http://127.0.0.1:8000/health
```

Ожидается:

```json
{"status":"ok"}
```

Проверка webhook:

```bash
./scripts/test_webhook.sh
```

Или через публичный HTTPS:

```bash
./scripts/test_webhook.sh https://SERVER_IP/webhook "Сколько будет 17 умножить на 23?"
```

Некоторые VPS не умеют обращаться к собственному публичному IP (hairpin/NAT loopback). Поэтому HTTPS лучше дополнительно проверить с телефона через мобильный интернет:

```text
https://SERVER_IP/health
```

## Создание навыка в Яндекс Диалогах

Откройте:

https://dialogs.yandex.ru/developer/

Далее:

1. **Создать диалог** → **Навык в Алисе**.
2. Укажите название.
3. В **Backend** выберите `Webhook URL`.
4. Укажите `https://SERVER_IP/webhook`.
5. Сохраните.
6. Проверьте навык во вкладке **Тестирование**.

Для домашнего использования выберите **Тип доступа → Приватный**. Не переключайте доступ на публичный, если не хотите размещать навык в каталоге.

## Логи

```bash
sudo journalctl -u alice-gpt -f -o cat
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

Подробное логирование запросов включается через:

```env
LOG_REQUESTS=true
```

в `/etc/alice-gpt.env`. После изменения:

```bash
sudo systemctl restart alice-gpt
```

Запросы Яндекса содержат идентификаторы пользователя и сессии — не публикуйте такие логи без очистки.

## Настройка характера

Редактируйте:

```bash
sudo nano /opt/alice-gpt/prompt.txt
sudo systemctl restart alice-gpt
```

## Модель и таймаут

```bash
sudo nano /etc/alice-gpt.env
```

Пример:

```env
GROQ_MODEL=qwen/qwen3.8-27b
MODEL_TIMEOUT_SECONDS=3.3
MAX_OUTPUT_TOKENS=120
MAX_HISTORY_MESSAGES=10
LOG_REQUESTS=false
```

После изменения:

```bash
sudo systemctl restart alice-gpt
```

Актуальные модели Groq:

https://console.groq.com/docs/models

## HTTPS без домена

Проект получает сертификат Let's Encrypt непосредственно на IPv4 с современным Certbot и профилем `shortlived`.

Проверка:

```bash
sudo certbot certificates
sudo certbot renew --dry-run
```

Installer создаёт автоматический `certbot renew` каждые 6 часов и reload Nginx после успешного обновления.

## Обновление

```bash
git pull
sudo cp app.py prompt.txt requirements.txt /opt/alice-gpt/
sudo /opt/alice-gpt/venv/bin/pip install -r /opt/alice-gpt/requirements.txt
sudo chown -R alicegpt:alicegpt /opt/alice-gpt
sudo systemctl restart alice-gpt
```

## Удаление

```bash
sudo ./scripts/uninstall.sh
```

Скрипт не удаляет API key, сертификаты и `/opt/alice-gpt` автоматически.

## Ограничения

- Яндекс ждёт полный ответ webhook не более 4,5 секунды.
- История хранится только в RAM и пропадает после рестарта.
- Для публичного высоконагруженного навыка понадобится внешнее хранилище сессий и более серьёзный deployment.
- Модели, тарифы и rate limits Groq могут меняться.

## Официальная документация

- Яндекс: https://yandex.ru/dev/dialogs/alice/doc/ru/deploy-overview
- Формат ответа Яндекса: https://yandex.ru/dev/dialogs/alice/doc/ru/response
- Тестирование навыка: https://yandex.ru/dev/dialogs/alice/doc/ru/test
- Let's Encrypt IP certificates: https://letsencrypt.org/2026/03/11/shorter-certs-certbot/
- Groq OpenAI-compatible API: https://console.groq.com/docs/openai
- Groq models: https://console.groq.com/docs/models

## License

MIT
