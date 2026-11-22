#!/usr/bin/env bash
set -euo pipefail

# Скрипт первичной настройки и запуска Bat на Ubuntu/Debian VPS

if ! command -v docker >/dev/null 2>&1; then
  echo ">>> Устанавливаю Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if ! docker compose version >/dev/null 2>&1; then
  echo ">>> Устанавливаю docker-compose-plugin..."
  apt-get update && apt-get install -y docker-compose-plugin
fi

mkdir -p data

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠️ Создан файл .env из .env.example."
  echo "Отредактируй .env (BOT_TOKEN, MES_LOGIN, MES_PASSWORD, ENCRYPTION_KEY) и запусти снова:"
  echo "  nano .env && docker compose up -d --build"
  exit 0
fi

echo ">>> Собираю и запускаю Bat (24/7)..."
docker compose up -d --build
docker compose ps
echo "✅ Bat запущен! Логи: docker compose logs -f"
