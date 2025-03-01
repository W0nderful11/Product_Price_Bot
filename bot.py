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
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
import os
from aiogram.client.bot import DefaultBotProperties

from parsers import parse_all  # Функция из parsers/__init__.py
from db import create_pool, init_db, save_products
from inline_handler import inline_router  # Inline-обработчик для инлайн-запросов

# Загружаем переменные окружения из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Используем MemoryStorage для FSM
storage = MemoryStorage()

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)
dp.include_router(inline_router)

# Глобальные переменные: корзина и выбранный город (по user_id)
BASKETS = {}  # {user_id: [id товара, ...]}
USER_CITIES = {}  # {user_id: "almaty", "astana", ...}

# Mappings для категорий и подкатегорий
CATEGORY_ID_MAP = {'Техника': {}, 'Продукты': {}}
CATEGORY_NAME_MAP = {'Техника': {}, 'Продукты': {}}
SUBCATEGORY_ID_MAP = {'Техника': {}, 'Продукты': {}}
SUBCATEGORY_NAME_MAP = {'Техника': {}, 'Продукты': {}}
MAPPINGS_LOADED = False


def get_user_city(user_id):
    """Получить город пользователя, по умолчанию 'almaty'."""
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
    """Обработчик команды /start."""
    share_button = KeyboardButton(text="Поделиться", request_contact=True)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[share_button]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Привет! Нажмите кнопку 'Поделиться' для авторизации.", reply_markup=keyboard)


@dp.message(lambda message: message.content_type == ContentType.CONTACT)
async def contact_handler(message: types.Message):
    """Обработчик получения контакта."""
    await message.answer("Спасибо за регистрацию!")


@dp.message(Command("support"))
async def support_handler(message: types.Message):
    """Обработчик команды /support."""
    await message.answer("При возникновении ошибок в коде обращайтесь к @mikoto699")


# --- Команда /city ---
@dp.message(Command("city"))
async def city_handler(message: types.Message):
    """Обработчик команды /city для выбора города."""
    cities = {"Алматы": "almaty", "Астана": "astana", "Шымкент": "shymkent"}
    builder = InlineKeyboardBuilder()
    for name, code in cities.items():
        builder.button(text=name, callback_data=f"city:{code}")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await message.answer("Выберите город:", reply_markup=keyboard)


@dp.callback_query(lambda c: c.data and c.data.startswith("city:"))
async def city_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора города."""
    city_code = callback_query.data.split("city:")[1]
    USER_CITIES[callback_query.from_user.id] = city_code
    await bot.edit_message_text(
        text=f"Город выбран: {html.escape(city_code)}",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id
    )
    await callback_query.answer()


# --- Команда /update (для админа с ID 784904211) ---
@dp.message(Command("update"))
async def update_handler(message: types.Message):
    """Обработчик команды /update для обновления данных (только для админа)."""
    if message.from_user.id != 784904211:
        await message.answer("Разрешено только админам.")
        return
    user_city = get_user_city(message.from_user.id)
    await message.answer("Обновление данных... Это может занять некоторое время.")
    products = parse_all(city=user_city)
    pool = await create_pool()
    await init_db(pool)
    await save_products(pool, products)
    await load_category_mappings()  # Обновляем маппинги после обновления данных
    await pool.close()
    await message.answer("Данные успешно обновлены!")


# --- Загрузка маппингов категорий и подкатегорий ---
async def load_category_mappings():
    """Загрузка маппингов категорий и подкатегорий из базы данных."""
    global MAPPINGS_LOADED
    pool = await create_pool()
    async with pool.acquire() as conn:
        # Загружаем категории для Техники
        tech_categories = await conn.fetch("SELECT DISTINCT category FROM products WHERE source = 'Kaspi';")
        CATEGORY_ID_MAP['Техника'] = {row['category']: i for i, row in enumerate(tech_categories)}
        CATEGORY_NAME_MAP['Техника'] = {i: row['category'] for i, row in enumerate(tech_categories)}

        # Загружаем категории для Продуктов
        prod_categories = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket');")
        CATEGORY_ID_MAP['Продукты'] = {row['category']: i for i, row in enumerate(prod_categories)}
        CATEGORY_NAME_MAP['Продукты'] = {i: row['category'] for i, row in enumerate(prod_categories)}

        # Загружаем подкатегории для Техники
        tech_subcategories = await conn.fetch(
            "SELECT category, subcategory FROM products WHERE source = 'Kaspi' GROUP BY category, subcategory;")
        SUBCATEGORY_ID_MAP['Техника'] = {}
        SUBCATEGORY_NAME_MAP['Техника'] = {}
        for row in tech_subcategories:
            cat = row['category']
            subcat = row['subcategory']
            if cat not in SUBCATEGORY_ID_MAP['Техника']:
                SUBCATEGORY_ID_MAP['Техника'][cat] = {}
                SUBCATEGORY_NAME_MAP['Техника'][cat] = {}
            subcat_id = len(SUBCATEGORY_ID_MAP['Техника'][cat])
            SUBCATEGORY_ID_MAP['Техника'][cat][subcat] = subcat_id
            SUBCATEGORY_NAME_MAP['Техника'][cat][subcat_id] = subcat

        # Загружаем подкатегории для Продуктов
        prod_subcategories = await conn.fetch(
            "SELECT category, subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket') GROUP BY category, subcategory;")
        SUBCATEGORY_ID_MAP['Продукты'] = {}
        SUBCATEGORY_NAME_MAP['Продукты'] = {}
        for row in prod_subcategories:
            cat = row['category']
            subcat = row['subcategory']
            if cat not in SUBCATEGORY_ID_MAP['Продукты']:
                SUBCATEGORY_ID_MAP['Продукты'][cat] = {}
                SUBCATEGORY_NAME_MAP['Продукты'][cat] = {}
            subcat_id = len(SUBCATEGORY_ID_MAP['Продукты'][cat])
            SUBCATEGORY_ID_MAP['Продукты'][cat][subcat] = subcat_id
            SUBCATEGORY_NAME_MAP['Продукты'][cat][subcat_id] = subcat
    await pool.close()
    MAPPINGS_LOADED = True


# --- Команда /menu ---
@dp.message(Command("menu"))
async def menu_handler(message: types.Message):
    """Обработчик команды /menu для отображения главного меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Техника", callback_data="main_cat:Техника")
    builder.button(text="Продукты", callback_data="main_cat:Продукты")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await message.answer("Выберите категорию:", reply_markup=keyboard)


# --- Обработка выбора основной категории (Техника/Продукты) ---
@dp.callback_query(lambda c: c.data and c.data.startswith("main_cat:"))
async def main_category_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора основной категории."""
    global MAPPINGS_LOADED
    if not MAPPINGS_LOADED:
        await load_category_mappings()
    main_cat = callback_query.data.split("main_cat:")[1]
    pool = await create_pool()
    async with pool.acquire() as conn:
        if main_cat == "Техника":
            rows = await conn.fetch("SELECT DISTINCT category FROM products WHERE source = 'Kaspi' ORDER BY category;")
        elif main_cat == "Продукты":
            rows = await conn.fetch(
                "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket') ORDER BY category;")
        else:
            rows = []
    await pool.close()

    if not rows:
        await callback_query.answer("Нет категорий в данной секции.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        category = row["category"]
        cat_id = CATEGORY_ID_MAP[main_cat][category]
        callback_data = f"category:{main_cat}:{cat_id}"
        builder.button(text=html.escape(category), callback_data=callback_data)
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(2)
    keyboard = builder.as_markup()

    await bot.edit_message_text(
        text=f"Выберите категорию в разделе {main_cat}:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Обработка выбора категории ---
@dp.callback_query(lambda c: c.data and c.data.startswith("category:"))
async def category_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора категории."""
    parts = callback_query.data.split(":", 2)
    if len(parts) < 3:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    main_cat, cat_id_str = parts[1], parts[2]
    cat_id = int(cat_id_str)
    category = CATEGORY_NAME_MAP[main_cat][cat_id]

    pool = await create_pool()
    async with pool.acquire() as conn:
        if main_cat == "Техника":
            rows = await conn.fetch(
                "SELECT DISTINCT subcategory FROM products WHERE source = 'Kaspi' AND category = $1 ORDER BY subcategory;",
                category)
        elif main_cat == "Продукты":
            rows = await conn.fetch(
                "SELECT DISTINCT subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket') AND category = $1 ORDER BY subcategory;",
                category)
        else:
            rows = []
    await pool.close()

    if not rows:
        await callback_query.answer("Нет подкатегорий в данной категории.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        subcat = row["subcategory"]
        subcat_id = SUBCATEGORY_ID_MAP[main_cat][category][subcat]
        callback_data = f"subcat:{main_cat}:{cat_id}:{subcat_id}"
        builder.button(text=html.escape(subcat), callback_data=callback_data)
    builder.button(text="Назад", callback_data=f"main_cat:{main_cat}")
    builder.adjust(2)
    keyboard = builder.as_markup()

    await bot.edit_message_text(
        text=f"Выберите подкатегорию в {html.escape(category)}:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Обработка выбора подкатегории ---
@dp.callback_query(lambda c: c.data and c.data.startswith("subcat:"))
async def subcategory_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора подкатегории."""
    parts = callback_query.data.split(":", 3)
    if len(parts) < 4:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    main_cat, cat_id_str, subcat_id_str = parts[1], parts[2], parts[3]
    cat_id = int(cat_id_str)
    subcat_id = int(subcat_id_str)
    category = CATEGORY_NAME_MAP[main_cat][cat_id]
    subcat = SUBCATEGORY_NAME_MAP[main_cat][category][subcat_id]
    await show_products_by_subcategory(callback_query, main_cat, category, subcat)


# --- Обработка кнопки "Назад" в главное меню ---
@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback_query: types.CallbackQuery):
    """Обработка возврата в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Техника", callback_data="main_cat:Техника")
    builder.button(text="Продукты", callback_data="main_cat:Продукты")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await bot.edit_message_text(
        text="Выберите категорию:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Функция отображения товаров ---
async def show_products_by_subcategory(callback_query: types.CallbackQuery, main_cat: str, category: str, subcat: str):
    """Отображение товаров по подкатегории."""
    pool = await create_pool()
    async with pool.acquire() as conn:
        if main_cat == "Техника":
            rows = await conn.fetch("""
                SELECT id, name, price, source, timestamp, link, image 
                FROM products 
                WHERE source = 'Kaspi' AND subcategory = $1 
                ORDER BY timestamp DESC 
                LIMIT 50;
            """, subcat)
        elif main_cat == "Продукты":
            rows = await conn.fetch("""
                SELECT id, name, price, source, timestamp, link, image 
                FROM products 
                WHERE source IN ('Арбуз', 'CleverMarket') AND subcategory = $1 
                ORDER BY timestamp DESC 
                LIMIT 50;
            """, subcat)
        else:
            rows = []
    await pool.close()

    if not rows:
        text = f"Нет товаров в подкатегории {html.escape(subcat)}."
    else:
        text = f"<b>Товары в подкатегории {html.escape(subcat)} ({html.escape(category)}):</b>\n\n"
        for row in rows:
            name = html.escape(row["name"])
            price = html.escape(row["price"])
            source = html.escape(row["source"])
            timestamp = row["timestamp"].strftime("%d.%m.%Y %H:%M")
            link = row["link"]
            img_text = f"\nФото: {html.escape(row['image'])}" if row.get("image") else ""
            order_link = f'<a href="{link}">Заказать</a>'
            text += (
                f"ID: {row['id']}\n• <b>{name}</b> — {price} (обновлено: {timestamp}) [Источник: {source}]{img_text}\n"
                f"Ссылка: {link}\n{order_link}\n\n")

    builder = InlineKeyboardBuilder()
    cat_id = CATEGORY_ID_MAP[main_cat][category]
    builder.button(text="Назад", callback_data=f"category:{main_cat}:{cat_id}")
    keyboard = builder.as_markup()
    await bot.edit_message_text(
        text=text,
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Команда /compare ---
@dp.message(Command("compare"))
async def compare_handler(message: types.Message):
    """Обработчик команды /compare для сравнения товаров."""
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT subcategory, array_agg(DISTINCT source) as sources
            FROM products
            WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi')
            GROUP BY subcategory
            HAVING COUNT(DISTINCT source) > 1
            ORDER BY subcategory;
        """)
    await pool.close()
    if not rows:
        await message.answer("Нет общих подкатегорий для сравнения.")
        return
    tech_subcats = []
    prod_subcats = []
    for row in rows:
        sources = row["sources"]
        subcat = row["subcategory"]
        if 'Kaspi' in sources:
            tech_subcats.append(subcat)
        else:
            prod_subcats.append(subcat)
    builder = InlineKeyboardBuilder()
    if tech_subcats:
        builder.button(text="Техника", callback_data="compare_main:Техника")
    if prod_subcats:
        builder.button(text="Продукты", callback_data="compare_main:Продукты")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await message.answer("Выберите основную категорию для сравнения:", reply_markup=keyboard)


# --- Обработка выбора основной категории в сравнении ---
@dp.callback_query(lambda c: c.data and c.data.startswith("compare_main:"))
async def compare_main_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора основной категории для сравнения."""
    main_cat = callback_query.data.split("compare_main:")[1]
    pool = await create_pool()
    async with pool.acquire() as conn:
        if main_cat == "Техника":
            rows = await conn.fetch("""
                SELECT subcategory, array_agg(DISTINCT source) as sources
                FROM products
                WHERE source IN ('Kaspi', 'Арбуз', 'CleverMarket')
                GROUP BY subcategory
                HAVING COUNT(DISTINCT source) > 1 AND bool_or(source = 'Kaspi')
                ORDER BY subcategory;
            """)
        elif main_cat == "Продукты":
            rows = await conn.fetch("""
                SELECT subcategory, array_agg(DISTINCT source) as sources
                FROM products
                WHERE source IN ('Арбуз', 'CleverMarket')
                GROUP BY subcategory
                HAVING COUNT(DISTINCT source) > 1
                ORDER BY subcategory;
            """)
        else:
            rows = []
    await pool.close()
    if not rows:
        await callback_query.answer("Нет общих подкатегорий для сравнения в выбранной категории.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for row in rows:
        subcat = row["subcategory"]
        callback_data = f"compare_subcat:{main_cat}:{subcat[:15]}"  # Обрезаем до 15 символов для безопасности
        builder.button(text=html.escape(subcat), callback_data=callback_data)
    builder.button(text="Назад", callback_data="compare_back:main")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await bot.edit_message_text(
        text="Выберите подкатегорию для сравнения:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Обработка выбора подкатегории для сравнения ---
@dp.callback_query(lambda c: c.data and c.data.startswith("compare_subcat:"))
async def compare_subcat_callback_handler(callback_query: types.CallbackQuery):
    """Обработка выбора подкатегории для сравнения."""
    parts = callback_query.data.split(":", 2)
    if len(parts) < 3:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    main_cat, subcat = parts[1], parts[2]
    pool = await create_pool()
    async with pool.acquire() as conn:
        arbuz_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory LIKE $1 || '%' AND source='Арбуз' ORDER BY timestamp DESC LIMIT 5;",
            subcat
        )
        clever_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory LIKE $1 || '%' AND source='CleverMarket' ORDER BY timestamp DESC LIMIT 5;",
            subcat
        )
        kaspi_rows = await conn.fetch(
            "SELECT id, name, price, timestamp, link, image FROM products WHERE subcategory LIKE $1 || '%' AND source='Kaspi' ORDER BY timestamp DESC LIMIT 5;",
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
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=f"compare_main:{main_cat}")
    keyboard = builder.as_markup()
    await bot.edit_message_text(
        text=text,
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Обработка кнопки "Назад" из главного меню сравнения ---
@dp.callback_query(lambda c: c.data and c.data.startswith("compare_back:main"))
async def compare_back_main_callback_handler(callback_query: types.CallbackQuery):
    """Обработка возврата в главное меню сравнения."""
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT subcategory, array_agg(DISTINCT source) as sources
            FROM products
            WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi')
            GROUP BY subcategory
            HAVING COUNT(DISTINCT source) > 1
            ORDER BY subcategory;
        """)
    await pool.close()
    if not rows:
        await callback_query.answer("Нет общих подкатегорий для сравнения.", show_alert=True)
        return
    tech_subcats = []
    prod_subcats = []
    for row in rows:
        sources = row["sources"]
        subcat = row["subcategory"]
        if 'Kaspi' in sources:
            tech_subcats.append(subcat)
        else:
            prod_subcats.append(subcat)
    builder = InlineKeyboardBuilder()
    if tech_subcats:
        builder.button(text="Техника", callback_data="compare_main:Техника")
    if prod_subcats:
        builder.button(text="Продукты", callback_data="compare_main:Продукты")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await bot.edit_message_text(
        text="Выберите основную категорию для сравнения:",
        chat_id=callback_query.message.chat.id,
        message_id=callback_query.message.message_id,
        reply_markup=keyboard
    )
    await callback_query.answer()


# --- Команда /basket ---
@dp.message(Command("basket"))
async def basket_handler(message: types.Message):
    """Обработчик команды /basket для просмотра корзины."""
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, [])
    if not basket:
        await message.answer("Ваша корзина пуста.")
        return
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow(
                "SELECT id, name, price, source, timestamp, link, image FROM products WHERE id=$1;", prod_id)
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
    """Обработчик команды /add для добавления товаров в корзину."""
    await state.set_state(AddProductState.waiting_for_product_id)
    await message.answer("Введите id товара(ов) для добавления в корзину (через пробел):")


@dp.message(AddProductState.waiting_for_product_id)
async def process_add_product(message: types.Message, state: FSMContext):
    """Обработка введенных ID товаров для добавления в корзину."""
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
    """Обработчик команды /order для формирования заказа."""
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
    """Обработка добавления товара в корзину через callback."""
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
    """Обработчик команды /ai для запроса к AI."""
    await state.set_state(AiState.waiting_for_query)
    context = (
        "Я помощник Stratton по покупке еды. Доступные команды: start, support, city, update, menu, compare, basket, order, add, ai.\n"
        "Введите запрос для AI:"
    )
    await message.answer(context)


@dp.message(AiState.waiting_for_query)
async def process_ai_request(message: types.Message, state: FSMContext):
    """Обработка запроса к AI."""
    user_prompt = message.text.strip()
    prompt = "Ты помощник Stratton по покупке еды. " + user_prompt
    if not GEMINI_API_KEY:
        await message.answer("AI ключ не найден в .env")
        await state.clear()
        return
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
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


# --- Главная функция для запуска бота ---
async def main():
    """Главная функция для запуска бота."""
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())