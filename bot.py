import asyncio
import logging
import html

import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    ContentType,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from dotenv import load_dotenv
import os
from aiogram.client.bot import DefaultBotProperties

from parsers import parse_all
from db import create_pool, init_db, save_products
from inline_handler import inline_router  # Импортируем inline‑роутер из отдельного файла

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # API-ключ для AI

# Используем MemoryStorage для FSM
storage = MemoryStorage()

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)

# Регистрируем inline‑роутер (без дублирования)
dp.include_router(inline_router)

# Глобальные переменные: корзина и выбранный город (по user_id)
BASKETS = {}       # {user_id: [id товара, ...]}
USER_CITIES = {}   # Пример: {user_id: "astana"}

def get_user_city(user_id):
    return USER_CITIES.get(user_id, "almaty")

# FSM для команды /ai
class AiState(StatesGroup):
    waiting_for_query = State()

# FSM для команды /add
class AddProductState(StatesGroup):
    waiting_for_product_id = State()

# --- Команды бота ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    share_button = KeyboardButton(text="Поделиться", request_contact=True)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[share_button]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Привет! Нажмите кнопку 'Поделиться' для авторизации.", reply_markup=keyboard)

@dp.message(lambda message: message.content_type == ContentType.CONTACT)
async def contact_handler(message: types.Message):
    await message.answer("Спасибо за регистрацию!")

@dp.message(Command("support"))
async def support_handler(message: types.Message):
    await message.answer("При возникновении ошибок в коде обращайтесь к @mikoto699")

# --- Команда /city ---
@dp.message(Command("city"))
async def city_handler(message: types.Message):
    cities = {
        "Алматы": "almaty",
        "Астана": "astana",
        "Шымкент": "shymkent"
    }
    keyboard = InlineKeyboardMarkup(inline_keyboard=[], row_width=2)
    for name, code in cities.items():
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=name, callback_data=f"city:{code}")])
    await message.answer("Выберите город:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("city:"))
async def city_callback_handler(callback_query: types.CallbackQuery):
    city_code = callback_query.data.split("city:")[1]
    USER_CITIES[callback_query.from_user.id] = city_code
    await callback_query.message.answer(f"Город выбран: {html.escape(city_code)}")
    await callback_query.answer()

# --- Команда /update (только для админа с ID 784904211) ---
@dp.message(Command("update"))
async def update_handler(message: types.Message):
    if message.from_user.id != 784904211:
        await message.answer("Разрешено только админам.")
        return
    user_city = get_user_city(message.from_user.id)
    await message.answer("Обновление данных... Это может занять некоторое время.")
    products = parse_all(city=user_city)
    pool = await create_pool()
    await init_db(pool)
    await save_products(pool, products)
    await pool.close()
    await message.answer("Данные успешно обновлены!")

# --- Команда /menu ---
@dp.message(Command("menu"))
async def menu_handler(message: types.Message):
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT category FROM products ORDER BY category;")
    await pool.close()
    if not rows:
        await message.answer("Нет данных по категориям. Сначала выполните /update.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[], row_width=2)
    for row in rows:
        cat = row["category"]
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=html.escape(cat), callback_data=f"cat:{cat}")])
    await message.answer("Меню категорий:", reply_markup=keyboard)

# --- Обработка выбора категории и подкатегории ---
@dp.callback_query(lambda c: c.data and c.data.startswith("cat:"))
async def category_callback_handler(callback_query: types.CallbackQuery):
    category = callback_query.data.split("cat:")[1]
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT subcategory FROM products WHERE category=$1 ORDER BY subcategory;", category)
    await pool.close()
    if not rows:
        await callback_query.answer("Нет данных по подкатегориям.")
        return
    if len(rows) == 1:
        subcat = rows[0]["subcategory"]
        await show_products_by_subcategory(callback_query, subcat)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[], row_width=2)
        for row in rows:
            subcat = row["subcategory"]
            keyboard.inline_keyboard.append([InlineKeyboardButton(text=html.escape(subcat), callback_data=f"subcat:{subcat}")])
        await callback_query.message.answer("Выберите подкатегорию:", reply_markup=keyboard)
        await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("subcat:"))
async def subcategory_callback_handler(callback_query: types.CallbackQuery):
    subcat = callback_query.data.split("subcat:")[1]
    await show_products_by_subcategory(callback_query, subcat)

async def show_products_by_subcategory(callback_query: types.CallbackQuery, subcat):
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, price, source, timestamp, link, image FROM products WHERE subcategory=$1 ORDER BY timestamp DESC LIMIT 50;",
            subcat
        )
    await pool.close()
    if not rows:
        text = f"Нет товаров в подкатегории {html.escape(subcat)}."
    else:
        text = f"<b>Товары в подкатегории {html.escape(subcat)}:</b>\n\n"
        for row in rows:
            name = html.escape(row["name"])
            price = html.escape(row["price"])
            source = html.escape(row["source"])
            timestamp = row["timestamp"].strftime("%d.%m.%Y %H:%M")
            link = row["link"]
            img_text = f"\nФото: {html.escape(row['image'])}" if row.get("image") else ""
            order_link = f'<a href="{link}">Заказать</a>'
            text += (f"ID: {row['id']}\n• <b>{name}</b> — {price} (обновлено: {timestamp}) [Источник: {source}]{img_text}\n"
                     f"Ссылка: {link}\n{order_link}\n\n")
    if len(text) > 4000:
        text = text[:4000] + "\n... (часть товаров не отображена)"
    await callback_query.message.answer(text)
    await callback_query.answer()

# --- Команда /compare ---
@dp.message(Command("compare"))
async def compare_handler(message: types.Message):
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT subcategory FROM products
            WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi')
            GROUP BY subcategory
            HAVING COUNT(DISTINCT source) > 1
            ORDER BY subcategory;
        """)
    await pool.close()
    if not rows:
        await message.answer("Нет общих подкатегорий для сравнения.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[], row_width=2)
    for row in rows:
        subcat = row["subcategory"]
        keyboard.inline_keyboard.append([InlineKeyboardButton(text=html.escape(subcat), callback_data=f"compare:{subcat}")])
    await message.answer("Общие подкатегории для сравнения:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("compare:"))
async def compare_callback_handler(callback_query: types.CallbackQuery):
    subcat = callback_query.data.split("compare:")[1]
    pool = await create_pool()
    async with pool.acquire() as conn:
        arbuz_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory=$1 AND source='Арбуз' ORDER BY timestamp DESC LIMIT 5;",
            subcat
        )
        clever_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory=$1 AND source='CleverMarket' ORDER BY timestamp DESC LIMIT 5;",
            subcat
        )
        kaspi_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory=$1 AND source='Kaspi' ORDER BY timestamp DESC LIMIT 5;",
            subcat
        )
    await pool.close()
    if not arbuz_rows and not clever_rows and not kaspi_rows:
        await callback_query.answer("По данной подкатегории товаров для сравнения не найдено.", show_alert=True)
        return
    text = f"<b>Сравнение товаров для подкатегории '{html.escape(subcat)}':</b>\n\n"
    if arbuz_rows:
        text += "<u>Арбуз:</u>\n"
        for row in arbuz_rows:
            name = html.escape(row["name"])
            price = html.escape(row["price"])
            timestamp = row["timestamp"].strftime("%d.%m.%Y %H:%M")
            link = row["link"]
            img_text = f" (Фото: {html.escape(row['image'])})" if row.get("image") else ""
            text += f"ID: {row['id']} – {name} — {price} (обновлено: {timestamp})\nСсылка: {link}{img_text}\n\n"
    if clever_rows:
        text += "<u>CleverMarket:</u>\n"
        for row in clever_rows:
            name = html.escape(row["name"])
            price = html.escape(row["price"])
            timestamp = row["timestamp"].strftime("%d.%m.%Y %H:%M")
            link = row["link"]
            img_text = f" (Фото: {html.escape(row['image'])})" if row.get("image") else ""
            text += f"ID: {row['id']} – {name} — {price} (обновлено: {timestamp})\nСсылка: {link}{img_text}\n\n"
    if kaspi_rows:
        text += "<u>Kaspi:</u>\n"
        for row in kaspi_rows:
            name = html.escape(row["name"])
            price = html.escape(row["price"])
            timestamp = row["timestamp"].strftime("%d.%m.%Y %H:%M")
            link = row["link"]
            img_text = f" (Фото: {html.escape(row['image'])})" if row.get("image") else ""
            text += f"ID: {row['id']} – {name} — {price} (обновлено: {timestamp})\nСсылка: {link}{img_text}\n\n"
    if len(text) > 4000:
        text = text[:4000] + "\n... (часть товаров не отображена)"
    await callback_query.message.answer(text)
    await callback_query.answer()

# --- Команда /basket ---
@dp.message(Command("basket"))
async def basket_handler(message: types.Message):
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, [])
    if not basket:
        await message.answer("Ваша корзина пуста.")
        return
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("SELECT id, name, price, source, timestamp, link, image FROM products WHERE id=$1;", prod_id)
            if row:
                items.append(row)
    await pool.close()
    text = "<b>Ваша корзина:</b>\n\n"
    for item in items:
        name = html.escape(item["name"])
        price = html.escape(item["price"])
        source = html.escape(item["source"])
        timestamp = item["timestamp"].strftime("%d.%m.%Y %H:%M")
        link = item["link"]
        img_text = f"\nФото: {html.escape(item['image'])}" if item.get("image") else ""
        order_link = f'<a href="{link}">Заказать</a>'
        text += (f"ID: {item['id']}\n• <b>{name}</b> ({source}) — {price} (обновлено: {timestamp})\n"
                 f"Ссылка: {link}\n{order_link}{img_text}\n\n")
    await message.answer(text)

# --- Команда /add ---
@dp.message(Command("add"))
async def add_command_handler(message: types.Message, state: FSMContext):
    await state.set_state(AddProductState.waiting_for_product_id)
    await message.answer("Введите id товара(ов) для добавления в корзину (через пробел):")

@dp.message(AddProductState.waiting_for_product_id)
async def process_add_product(message: types.Message, state: FSMContext):
    try:
        prod_ids = [int(x) for x in message.text.split()]
    except ValueError:
        await message.answer("Все ID должны быть числами. Попробуйте ещё раз.")
        return
    user_id = message.from_user.id
    if user_id not in BASKETS:
        BASKETS[user_id] = []
    BASKETS[user_id].extend(prod_ids)
    await message.answer(f"Товары с id {', '.join(map(str, prod_ids))} добавлены в корзину.")
    await state.clear()

# --- Команда /order ---
@dp.message(Command("order"))
async def order_handler(message: types.Message):
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, [])
    if not basket:
        await message.answer("Ваша корзина пуста.")
        return
    order_items = []
    pool = await create_pool()
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("SELECT link FROM products WHERE id=$1;", prod_id)
            if row and row.get("link"):
                order_items.append(row["link"])
    await pool.close()
    order_url = "https://example.com/order?items=" + ",".join(order_items)
    await message.answer(f"Ваш заказ сформирован:\n<a href='{order_url}'>Оформить заказ</a>")

@dp.callback_query(lambda c: c.data and c.data.startswith("add:"))
async def add_to_basket_handler(callback_query: types.CallbackQuery):
    try:
        prod_id = int(callback_query.data.split("add:")[1])
    except ValueError:
        await callback_query.answer("Некорректный ID")
        return
    user_id = callback_query.from_user.id
    if user_id not in BASKETS:
        BASKETS[user_id] = []
    BASKETS[user_id].append(prod_id)
    await callback_query.answer("Товар добавлен в корзину!")

# --- Команда /ai ---
@dp.message(Command("ai"))
async def ai_command_handler(message: types.Message, state: FSMContext):
    await state.set_state(AiState.waiting_for_query)
    context = (
        "Я помощник Stratton по покупке еды. Доступные команды: start, support, city, update, menu, compare, basket, order, add, ai.\n"
        "Введите запрос для AI:"
    )
    await message.answer(context)

@dp.message(AiState.waiting_for_query)
async def process_ai_request(message: types.Message, state: FSMContext):
    user_prompt = message.text.strip()
    prompt = "Ты помощник Stratton по покупке еды. " + user_prompt
    if not GEMINI_API_KEY:
        await message.answer("AI ключ не найден в .env")
        await state.clear()
        return
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }]
    }
    headers = {"Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    await message.answer(f"Ошибка AI: {resp.status}")
                    await state.clear()
                    return
                result = await resp.json()
        ai_response = (result.get("candidates", [{}])[0]
                           .get("content", {})
                           .get("parts", [{}])[0]
                           .get("text", "Не удалось получить ответ от AI."))
    except Exception as e:
        ai_response = "Не удалось получить ответ от AI."
    await message.answer(f"Ответ AI:\n{ai_response}")
    await state.clear()

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
