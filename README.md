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

> Яндекс Диалоги ждут ответ навыка только **4,5 секунды**, поэтому в проекте стоит жёсткий таймаут модели 3,3 секунды и короткие голосовые ответы.

## Требования

Рекомендуется свежий VPS:

- Ubuntu 22.04/24.04 или актуальный Debian;
- публичный статический IPv4;
- входящие TCP-порты `80` и `443` доступны из интернета;
- SSH-доступ с `root`/`sudo`;
- Groq API key;
- аккаунт Яндекса для создания навыка Алисы.

Если на сервере уже работают сайты/Nginx, внимательно проверьте конфиги перед установкой: installer рассчитан прежде всего на отдельный VPS.

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

Installer спросит:

1. публичный IPv4 сервера;
2. email для Let's Encrypt;
3. Groq API key;
4. модель Groq (по умолчанию `qwen/qwen3.8-27b`).

После успешной установки он выведет:

```text
Health:  https://SERVER_IP/health
Webhook: https://SERVER_IP/webhook
```

### Важно про firewall и VPN

Installer **не включает UFW самостоятельно**. Если UFW уже активен, он только добавит `80/tcp` и `443/tcp`.

Это сделано специально: команда `ufw enable` на сервере с WireGuard/AmneziaWG может заблокировать UDP-порт VPN или forwarding. Если VPN уже настроен, сохраните его UDP-порт и route/NAT правила.

Если firewall настраивается у облачного провайдера, разрешите минимум:

```text
22/tcp   SSH
80/tcp   Let's Encrypt
443/tcp  webhook Алисы
```

Порты VPN добавляются отдельно согласно вашей конфигурации.

## Проверка сервера

### Локальный health check

```bash
curl http://127.0.0.1:8000/health
```

Ожидается:

```json
{"status":"ok"}
```

### HTTPS извне

Откройте с телефона через мобильный интернет:

```text
https://SERVER_IP/health
```

Должен вернуться тот же `{"status":"ok"}`.

Некоторые VPS не умеют обращаться к собственному публичному IP (hairpin/NAT loopback). Поэтому ошибка `curl https://SERVER_IP/...` **с самого VPS** не всегда означает, что адрес недоступен из интернета.

### Тест webhook

```bash
./scripts/test_webhook.sh
```

Или через публичный HTTPS:

```bash
./scripts/test_webhook.sh https://SERVER_IP/webhook "Сколько будет 17 умножить на 23?"
```

Пример результата:

```json
{"version":"1.0","response":{"text":"391.","end_session":false}}
```

## Создание навыка в Яндекс Диалогах

Откройте консоль:

https://dialogs.yandex.ru/developer/

Далее:

1. **Создать диалог** → **Навык в Алисе**.
2. Укажите название навыка.
3. В разделе **Backend** выберите `Webhook URL`.
4. Введите:

```text
https://SERVER_IP/webhook
```

5. Сохраните настройки.
6. На вкладке **Тестирование** задайте несколько вопросов.

В запросе Яндекса исходная фраза пользователя приходит как `request.original_utterance`. Приложение отправляет её в Groq и возвращает JSON в формате Яндекс Диалогов.

### Только для дома / без публичного каталога

Если навык нужен только вам:

- выберите **Тип доступа → Приватный**;
- для проверки в консоли публикация не нужна;
- для использования на телефоне/Станции убедитесь, что устройство авторизовано под тем же Яндекс-аккаунтом.

Приватный навык можно тестировать голосом до публикации. Не переключайте тип доступа на публичный, если не хотите размещать навык в общем каталоге.

## Логи

Логи приложения:

```bash
sudo journalctl -u alice-gpt -f -o cat
```

Логи Nginx:

```bash
sudo tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

Статус:

```bash
sudo systemctl status alice-gpt --no-pager
sudo systemctl status nginx --no-pager
```

### Подробное логирование запросов

По умолчанию:

```text
LOG_REQUESTS=false
```

Для отладки можно изменить `/etc/alice-gpt.env`:

```text
LOG_REQUESTS=true
```

и перезапустить:

```bash
sudo systemctl restart alice-gpt
```

Учтите: запросы Яндекса содержат идентификаторы пользователя/сессии. Не публикуйте такие логи без очистки.

## Настройка характера помощника

Редактируйте:

```bash
sudo nano /opt/alice-gpt/prompt.txt
sudo systemctl restart alice-gpt
```

Например можно изменить длину ответа, стиль речи или правила оформления. `prompt.txt` читается при запуске процесса, поэтому после изменения нужен restart.

## Настройка модели и таймаута

Файл:

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

Список актуальных моделей Groq:

https://console.groq.com/docs/models

`qwen/qwen3.8-27b` сейчас является preview-моделью, поэтому со временем идентификатор модели может измениться. Для проекта он вынесен в переменную окружения.

## HTTPS без домена

Проект использует сертификат Let's Encrypt непосредственно на IPv4.

Для IP-сертификатов нужен современный Certbot. Installer устанавливает свежий Certbot в `/opt/certbot` и использует профиль `shortlived`:

```bash
certbot certonly \
  --preferred-profile shortlived \
  --webroot \
  --webroot-path /var/www/letsencrypt \
  --ip-address SERVER_IP
```

IP-сертификаты короткоживущие, поэтому installer создаёт автоматический `certbot renew` каждые 6 часов и reload Nginx после успешного renewal.

Проверка:

```bash
sudo certbot certificates
sudo certbot renew --dry-run
```

## Ручная установка

Если не хотите запускать installer, основные шаги такие:

```text
1. Python venv + requirements.txt
2. app.py → /opt/alice-gpt/app.py
3. prompt.txt → /opt/alice-gpt/prompt.txt
4. GROQ_API_KEY → /etc/alice-gpt.env
5. systemd/alice-gpt.service → /etc/systemd/system/
6. Nginx проксирует 443 → 127.0.0.1:8000
7. Let's Encrypt сертификат на IP
8. Webhook URL в Яндекс Диалогах
```

Полезные команды:

```bash
sudo systemctl restart alice-gpt
sudo journalctl -u alice-gpt -f -o cat
curl http://127.0.0.1:8000/health
sudo nginx -t
sudo certbot renew --dry-run
```

## Где хранятся файлы после установки

```text
/opt/alice-gpt/app.py
/opt/alice-gpt/prompt.txt
/opt/alice-gpt/venv/
/etc/alice-gpt.env
/etc/systemd/system/alice-gpt.service
/etc/nginx/sites-available/alice-gpt
/etc/letsencrypt/
```

## Обновление проекта

После `git pull` скопируйте обновлённые файлы и перезапустите сервис:

```bash
sudo cp app.py prompt.txt requirements.txt /opt/alice-gpt/
sudo /opt/alice-gpt/venv/bin/pip install -r /opt/alice-gpt/requirements.txt
sudo chown -R alicegpt:alicegpt /opt/alice-gpt
sudo systemctl restart alice-gpt
```

## Удаление

```bash
sudo ./scripts/uninstall.sh
```

Скрипт намеренно не удаляет API key, сертификаты и `/opt/alice-gpt` автоматически, чтобы случайно не уничтожить данные. При необходимости удалите их вручную.

## Ограничения

- Яндекс ждёт ответ webhook примерно 4,5 секунды вместе с сетевой задержкой.
- История диалога хранится только в RAM и пропадает после рестарта сервиса.
- Один процесс подходит для личного использования; для большого публичного навыка понадобится внешнее хранилище сессий и более серьёзный deployment.
- Groq API, конкретные модели, тарифы и rate limits могут меняться — проверяйте актуальные условия у Groq.
- Для работы из конкретной страны учитывайте условия доступности выбранного API-провайдера.

## Полезные официальные ссылки

- Яндекс: размещение навыка на любом сервере — https://yandex.ru/dev/dialogs/alice/doc/ru/deploy-overview
- Яндекс: настройки Webhook URL — https://yandex.ru/dev/dialogs/alice/doc/ru/publish-settings
- Яндекс: тестирование навыка — https://yandex.ru/dev/dialogs/alice/doc/ru/test
- Яндекс: формат ответа — https://yandex.ru/dev/dialogs/alice/doc/ru/response
- Let's Encrypt: IP certificates + Certbot — https://letsencrypt.org/2026/03/11/shorter-certs-certbot/
- Groq: OpenAI-compatible API — https://console.groq.com/docs/openai
- Groq: список моделей — https://console.groq.com/docs/models

## License

MIT
