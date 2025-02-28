# Product Price Bot

Product Price Bot – это Telegram-бот для сравнения цен на товары из нескольких онлайн-магазинов (Arbuz, CleverMarket, Kaspi). Бот собирает данные о товарах (название, цена, изображение, ссылка, ID и т.д.) и предоставляет пользователям возможность искать товары через inline‑режим прямо из любого чата.

## Функциональность

- **Парсинг данных:**
  - Arbuz: сбор данных с корректным парсингом изображений.
  - CleverMarket: сбор данных с актуальными ценами и изображениями.
  - Kaspi: парсинг с использованием Selenium для динамически загружаемых страниц.
- **Хранение данных:**  
  Данные сохраняются в базе PostgreSQL с использованием asyncpg.
- **Inline поиск:**  
  Inline‑режим позволяет пользователям искать товары прямо из любого чата Telegram.
- **Команды бота:**
  - `/start` – запуск бота и авторизация.
  - `/update` – обновление данных (только для администратора).
  - `/menu` – просмотр категорий товаров.
  - `/compare` – сравнение товаров по подкатегориям.
  - `/basket`, `/add`, `/order` – управление корзиной заказов.
  - `/ai` – получение ответа от AI (с интеграцией с Gemini API).

## Структура проекта

```
project/
├── .env
├── README.md
├── bot.py
├── db.py
├── reset_db.py
├── inline_handler.py
└── parsers/
    ├── __init__.py
    ├── arbuz_parser.py
    ├── clever_parser.py
    └── kaspi_parser.py
```

## Установка и запуск

1. **Клонирование репозитория:**

   ```bash
   git clone https://github.com/W0nderful11/product-price-bot.git
   cd product-price-bot
   ```

2. **Установка зависимостей:**

   Убедитесь, что у вас установлен Python 3, затем выполните:

   ```bash
   pip install -r requirements.txt
   ```

   Если файла `requirements.txt` нет, установите следующие библиотеки:

   ```bash
   pip install requests beautifulsoup4 lxml selenium aiogram asyncpg python-dotenv databases aiohttp
   ```

3. **Настройка переменных окружения:**

   Создайте файл `.env` в корневой директории со следующим содержимым (замените значения на свои):

   ```ini
   BOT_TOKEN=ваш_бот_токен
   GEMINI_API_KEY=ваш_API_ключ_для_Gemini
   DATABASE_USER=postgres
   DATABASE_PASSWORD= 
   DATABASE_NAME=product_price_bot
   DATABASE_HOST=localhost
   DATABASE_PORT=5432
   ```

4. **Сброс базы данных:**

   Выполните команду:

   ```bash
   python3 reset_db.py
   ```

5. **Проверка работы парсеров (при необходимости):**

   Например, для Arbuz:

   ```bash
   python3 parsers/arbuz_parser.py
   python3 parsers/clever_parser.py
   python3 parsers/kaspi_parser.py
   ```

6. **Запуск бота:**

   ```bash
   python3 bot.py
   ```

## Inline режим

Чтобы включить inline‑режим для бота, выполните следующие действия:

1. Отправьте команду `/setinline` через BotFather, выберите вашего бота и установите placeholder (например, "Найдите лучшие цены – введите название товара...").
2. Откройте любой чат в Telegram и введите `@ProductPriceCompareBot` и ваш запрос (например, "iPhone"). Бот должен вернуть inline‑результаты, в которых отображается ID товара, название, цена и ссылка.

## Git: Подключение к удалённому репозиторию

Чтобы связать локальный проект с репозиторием на GitHub (https://github.com/W0nderful11/product-price-bot.git), выполните следующие команды:

1. **Добавление удалённого репозитория:**

   ```bash
   git remote add origin https://github.com/W0nderful11/product-price-bot.git
   ```

2. **Проверка подключения:**

   ```bash
   git remote -v
   ```

3. **Зафиксируйте изменения и отправьте их:**

   ```bash
   git add .
   git commit -m "Обновление inline‑режима"
   git push origin master
   ```
   Если основная ветка называется `main`, используйте:
   ```bash
   git push origin main
   ```

## Примечания

- Если inline‑режим не возвращает результаты, убедитесь, что данные в базе заполнены (выполните команду `/update`).
- Если возникают ошибки подключения к базе, проверьте настройки в файле `.env` и корректность установки PostgreSQL.
- Для парсинга динамического контента используется Selenium – убедитесь, что chromedriver установлен и доступен в PATH.
- Inline‑хэндлер использует библиотеку databases для быстрого асинхронного доступа к базе данных.

