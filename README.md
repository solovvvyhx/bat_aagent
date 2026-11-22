# 🦇 Bat — автономный Telegram-ассистент для edu.mes.ru

## Запуск 24/7 на Ubuntu/Debian VPS

1. Подключись к VPS по SSH и склонируй репозиторий:
   ```bash
   git clone https://github.com/solovvvyhx/bat_aagent.git
   cd bat_aagent
   ```
2. Создай `.env` из примера и заполни секреты (`BOT_TOKEN`, `MES_LOGIN`, `MES_PASSWORD`):
   ```bash
   cp .env.example .env
   nano .env
   ```
3. Запусти установку и контейнер (автоматически поставит Docker и поднимет бота 24/7):
   ```bash
   bash deploy/vps-setup.sh
   ```

## Полезные команды на VPS
- Логи в реальном времени: `docker compose logs -f`
- Обновить бота после `git push`: `git pull && docker compose up -d --build`
- Статус контейнера: `docker compose ps`
- Проверка здоровья: `curl http://127.0.0.1:8080/health`
