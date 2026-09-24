#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo ./install.sh" >&2
  exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR=/opt/alice-gpt
ENV_FILE=/etc/alice-gpt.env
SERVICE_FILE=/etc/systemd/system/alice-gpt.service
NGINX_SITE=/etc/nginx/sites-available/alice-gpt
LE_WEBROOT=/var/www/letsencrypt

SERVER_IP="${SERVER_IP:-$(curl -4 -fsS https://api.ipify.org || true)}"
if [[ -z "$SERVER_IP" ]]; then
  read -r -p "Public IPv4: " SERVER_IP
fi

read -r -p "Public IPv4 [$SERVER_IP]: " INPUT_IP
SERVER_IP="${INPUT_IP:-$SERVER_IP}"

read -r -p "Email for Let's Encrypt: " LE_EMAIL
if [[ -z "$LE_EMAIL" ]]; then
  echo "Email is required." >&2
  exit 1
fi

read -r -s -p "Groq API key (gsk_...): " GROQ_API_KEY
echo
if [[ -z "$GROQ_API_KEY" ]]; then
  echo "Groq API key is required." >&2
  exit 1
fi

read -r -p "Groq model [qwen/qwen3.8-27b]: " GROQ_MODEL
GROQ_MODEL="${GROQ_MODEL:-qwen/qwen3.8-27b}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-venv python3-pip nginx curl ca-certificates

# Deliberately do not enable UFW: that may break existing WireGuard/AmneziaWG.
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q '^Status: active'; then
  echo "UFW is active; allowing required web ports. Existing rules are preserved."
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
fi

if ! id alicegpt >/dev/null 2>&1; then
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin alicegpt
fi

mkdir -p "$APP_DIR"
cp "$REPO_DIR/app.py" "$APP_DIR/app.py"
cp "$REPO_DIR/prompt.txt" "$APP_DIR/prompt.txt"
cp "$REPO_DIR/requirements.txt" "$APP_DIR/requirements.txt"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
chown -R alicegpt:alicegpt "$APP_DIR"

cat > "$ENV_FILE" <<EOF
GROQ_API_KEY=$GROQ_API_KEY
GROQ_MODEL=$GROQ_MODEL
MODEL_TIMEOUT_SECONDS=3.3
MAX_OUTPUT_TOKENS=120
MAX_HISTORY_MESSAGES=10
LOG_REQUESTS=false
PROMPT_FILE=/opt/alice-gpt/prompt.txt
EOF
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

cp "$REPO_DIR/systemd/alice-gpt.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now alice-gpt

mkdir -p "$LE_WEBROOT/.well-known/acme-challenge"
chown -R www-data:www-data "$LE_WEBROOT"
rm -f /etc/nginx/sites-enabled/default
cp "$REPO_DIR/nginx/http.conf" "$NGINX_SITE"
ln -sfn "$NGINX_SITE" /etc/nginx/sites-enabled/alice-gpt
nginx -t
systemctl reload nginx

# Use a fresh Certbot so IP certificate support does not depend on old distro packages.
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install --upgrade pip certbot
ln -sfn /opt/certbot/bin/certbot /usr/local/bin/certbot

certbot --version

certbot certonly   --non-interactive   --agree-tos   --email "$LE_EMAIL"   --preferred-profile shortlived   --webroot   --webroot-path "$LE_WEBROOT"   --ip-address "$SERVER_IP"

sed "s/__SERVER_IP__/$SERVER_IP/g" "$REPO_DIR/nginx/https-ip.conf.template" > "$NGINX_SITE"
nginx -t
systemctl reload nginx

mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

cat > /etc/cron.d/certbot-renew <<'EOF'
17 */6 * * * root /usr/local/bin/certbot renew -q
EOF
chmod 644 /etc/cron.d/certbot-renew

echo
echo "========================================"
echo "Installed successfully."
echo "Health:  https://$SERVER_IP/health"
echo "Webhook: https://$SERVER_IP/webhook"
echo "Logs:    journalctl -u alice-gpt -f -o cat"
echo "========================================"
echo

curl --fail --silent --show-error --max-time 5 "https://$SERVER_IP/health" ||   echo "WARNING: this VPS could not reach its own public IP. Test HTTPS from another network/device."
