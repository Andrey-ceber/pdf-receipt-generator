# Генератор чеков PDF для Coolify

Веб-версия проекта `pdf-receipt-generator`, подготовленная для развертывания на VPS через Coolify. Пользователь заполняет форму и получает готовый PDF-чек.

## Локальный запуск

```bash
docker build -t pdf-receipt-web .
docker run --rm -p 5000:5000 pdf-receipt-web
```

Страница приложения: `http://localhost:5000`.

Проверка состояния: `http://localhost:5000/health`.

## Настройка в Coolify

- тип ресурса: Private Repository with Deploy Key;
- ветка: `main`;
- способ сборки: Dockerfile;
- внутренний порт: `5000`;
- health check: `/health`.

После первого успешного деплоя добавьте webhook из Coolify в GitHub и проверьте автодеплой тестовым коммитом.
