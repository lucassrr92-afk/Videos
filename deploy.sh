#!/usr/bin/env bash
# Instala o ClipForge num servidor Ubuntu/Debian novo (rode como root).
#   curl -fsSL https://raw.githubusercontent.com/<você>/Videos/claude/clipforge/deploy.sh | DOMAIN=cortes.seudominio.com bash
set -euo pipefail
: "${DOMAIN:?Defina DOMAIN, ex.: DOMAIN=cortes.seudominio.com}"
REPO="${REPO:-https://github.com/lucassrr92-afk/Videos.git}"
BRANCH="${BRANCH:-claude/clipforge}"

command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
[ -d /opt/clipforge ] || git clone -b "$BRANCH" "$REPO" /opt/clipforge
cd /opt/clipforge && git pull --ff-only
[ -f .env ] || { cp .env.example .env; sed -i "s/^APP_PASSWORD=.*/APP_PASSWORD=$(openssl rand -base64 12)/" .env; }
[ -f client_secret.json ] || echo '{}' > client_secret.json
mkdir -p data tokens
DOMAIN="$DOMAIN" docker compose up -d --build
echo
echo "Pronto: https://$DOMAIN"
grep '^APP_PASSWORD=' .env | sed 's/APP_PASSWORD=/Senha de acesso: /'
echo "Edite /opt/clipforge/.env (ANTHROPIC_API_KEY etc.) e rode: cd /opt/clipforge && DOMAIN=$DOMAIN docker compose up -d"
