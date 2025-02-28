import html
from aiogram import types
from aiogram.dispatcher.router import Router
from db import create_pool
from dotenv import load_dotenv
import os
import databases

load_dotenv()

DATABASE_URL = (
    f"postgresql://{os.getenv('DATABASE_USER')}:"
    f"{os.getenv('DATABASE_PASSWORD')}@"
    f"{os.getenv('DATABASE_HOST')}:{os.getenv('DATABASE_PORT')}/"
    f"{os.getenv('DATABASE_NAME')}"
)

database = databases.Database(DATABASE_URL)

inline_router = Router()


@inline_router.inline_query()
async def inline_query_handler(query: types.InlineQuery):
    search_text = query.query.strip()
    if not search_text:
        await query.answer([], switch_pm_text="Введите запрос", switch_pm_parameter="start")
        return

    sql = """
        SELECT id, name, price, link, image
        FROM products
        WHERE name ILIKE :pattern OR CAST(id AS TEXT) ILIKE :pattern
        ORDER BY timestamp DESC
        LIMIT 10
    """
    values = {"pattern": f"%{search_text}%"}
    if not database.is_connected:
        await database.connect()
    rows = await database.fetch_all(query=sql, values=values)

    results = []
    for row in rows:
        thumb = row["image"] if row["image"] and "image-placeholder" not in row["image"] else None
        # Включаем ID в сообщение
        message_text = html.escape(f"ID: {row['id']}\n{row['name']} — {row['price']}\nСсылка: {row['link']}")
        results.append(
            types.InlineQueryResultArticle(
                id=str(row["id"]),
                title=html.escape(f"ID: {row['id']} - {row['name']}"),
                input_message_content=types.InputTextMessageContent(message_text=message_text),
                thumb_url=thumb
            )
        )
    await query.answer(results, cache_time=1)
