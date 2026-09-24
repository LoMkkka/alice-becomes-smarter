#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

systemctl disable --now alice-gpt 2>/dev/null || true
rm -f /etc/systemd/system/alice-gpt.service
systemctl daemon-reload

rm -f /etc/nginx/sites-enabled/alice-gpt /etc/nginx/sites-available/alice-gpt
nginx -t >/dev/null 2>&1 && systemctl reload nginx || true

echo "Service and nginx config removed."
echo "Not removed automatically: /opt/alice-gpt, /etc/alice-gpt.env, Let's Encrypt certificates."
echo "Remove them manually if you no longer need them."
