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

# Инициализация хранилища состояний и бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)
dp.include_router(inline_router)

# Глобальные переменные
BASKETS = {}         # {user_id: [id товара, ...]}
USER_CITIES = {}     # {user_id: "almaty", "astana", "shymkent", ...}

# Маппинги для категорий и подкатегорий (работаем с разделом "Продукты")
CATEGORY_ID_MAP = {'Продукты': {}}
CATEGORY_NAME_MAP = {'Продукты': {}}
SUBCATEGORY_ID_MAP = {'Продукты': {}}
SUBCATEGORY_NAME_MAP = {'Продукты': {}}
MAPPINGS_LOADED = False

# Количество товарных блоков на страницу
PRODUCTS_PER_PAGE = 5

def get_user_city(user_id):
    """Возвращает выбранный город для пользователя, по умолчанию 'almaty'."""
    return USER_CITIES.get(user_id, "almaty")

# Если хотите использовать запасное изображение, измените функцию так:
def get_first_available_photo(rows):
    for row in rows:
        image = row.get("image")
        if image and image.strip():
            return image
    # Если ни у одного товара нет картинки, можно вернуть URL-запаски
    return "https://via.placeholder.com/150"  # Или вернуть None и обрабатывать это в хендлере

# Новый callback-обработчик для подкатегории
@dp.callback_query(lambda c: c.data and c.data.startswith("subcat:"))
async def subcategory_callback_handler(callback_query: types.CallbackQuery):
    """
    Обработка выбора подкатегории в меню "Продукты".
    Извлекает товары из базы по выбранной категории и подкатегории, выводит их с пагинацией,
    сортируя по цене от дешёвых к дорогим.
    Callback data имеет формат: subcat:{main_cat}:{cat_id}:{subcat_id}:{offset}
    """
    try:
        _, main_cat, cat_id_str, subcat_id_str, offset_str = callback_query.data.split(":")
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return

    cat_id = int(cat_id_str)
    subcat_id = int(subcat_id_str)
    offset = int(offset_str)

    # Получаем название категории и подкатегории из глобальных маппингов
    category = CATEGORY_NAME_MAP[main_cat][cat_id]
    subcategory = SUBCATEGORY_NAME_MAP[main_cat][category][subcat_id]

    # Извлекаем товары, сортируя по цене (от дешёвых к дорогим)
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, price, source, timestamp, link, image "
            "FROM products "
            "WHERE category = $1 AND subcategory = $2 "
            "ORDER BY (CASE WHEN regexp_replace(price, '[^0-9.]', '', 'g') ~ '^[0-9]+(\\.[0-9]+)?$' "
            "THEN CAST(regexp_replace(price, '[^0-9.]', '', 'g') AS numeric) ELSE 9999999 END) ASC "
            "LIMIT 100;",
            category, subcategory
        )
    await pool.close()

    if not rows:
        await callback_query.answer("Нет товаров в данной подкатегории.", show_alert=True)
        return

    # Формируем блоки с информацией по каждому товару
    blocks = []
    for row in rows:
        block = (
            f"ID: {row['id']}\n"
            f"Название: {html.escape(row['name'])}\n"
            f"Цена: {html.escape(row['price'])}\n"
            f"Источник: {html.escape(row['source'])}\n"
            f"Актуально на: {row['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{row['link']}\">Ссылка</a>"
        )
        blocks.append(block)

    total_blocks = len(blocks)
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = f"<b>Товары подкатегории {html.escape(subcategory)}:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)

    # Кнопки для пагинации и возврата
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(
            text="Продолжить",
            callback_data=f"subcat:{main_cat}:{cat_id}:{subcat_id}:{new_offset}"
        ))
    buttons.append(InlineKeyboardButton(text="Назад", callback_data="main_cat:Продукты"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    # Берём первую доступную картинку из списка товаров
    photo_url = get_first_available_photo(rows)

    try:
        if photo_url and offset == 0:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=types.InputMediaPhoto(media=photo_url, caption=page_text, parse_mode="HTML"),
                reply_markup=keyboard
            )
        else:
            await bot.edit_message_text(
                text=page_text,
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception:
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text=page_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    await callback_query.answer()


# FSM для команды /ai
class AiState(StatesGroup):
    waiting_for_query = State()

# FSM для команды /add
class AddProductState(StatesGroup):
    waiting_for_product_id = State()

# ---------------------------------------------------------
# Основные команды и навигация по разделам
# ---------------------------------------------------------

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Команда /start – приветствие и запрос контакта."""
    share_button = KeyboardButton(text="Поделиться", request_contact=True)
    keyboard = ReplyKeyboardMarkup(keyboard=[[share_button]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Привет! Нажмите кнопку 'Поделиться' для авторизации.", reply_markup=keyboard)

@dp.message(lambda message: message.content_type == ContentType.CONTACT)
async def contact_handler(message: types.Message):
    """Обработка контакта пользователя."""
    await message.answer("Спасибо за регистрацию!")

@dp.message(Command("support"))
async def support_handler(message: types.Message):
    """Команда /support – информация для связи при ошибках."""
    await message.answer("При возникновении ошибок в коде обращайтесь к @mikoto699")

@dp.message(Command("city"))
async def city_handler(message: types.Message):
    """Команда /city – выбор города."""
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
    try:
        await bot.edit_message_text(
            text=f"Город выбран: {html.escape(city_code)}",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id
        )
    except Exception:
        await bot.send_message(chat_id=callback_query.message.chat.id,
                               text=f"Город выбран: {html.escape(city_code)}")
    await callback_query.answer()

@dp.message(Command("update"))
async def update_handler(message: types.Message):
    """Команда /update – обновление данных (только для админа)."""
    if message.from_user.id != 784904211:
        await message.answer("Разрешено только админам.")
        return
    user_city = get_user_city(message.from_user.id)
    await message.answer("Обновление данных... Это может занять некоторое время.")
    products = parse_all(city=user_city)
    pool = await create_pool()
    await init_db(pool)
    await save_products(pool, products)
    await load_category_mappings()  # Обновляем маппинги
    await pool.close()
    await message.answer("Данные успешно обновлены!")

async def load_category_mappings():
    """
    Загружает маппинги категорий и подкатегорий для раздела "Продукты"
    и обновляет глобальные переменные.
    """
    global MAPPINGS_LOADED
    pool = await create_pool()
    async with pool.acquire() as conn:
        prod_categories = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket') ORDER BY category;"
        )
        CATEGORY_ID_MAP['Продукты'] = {row['category']: i for i, row in enumerate(prod_categories)}
        CATEGORY_NAME_MAP['Продукты'] = {i: row['category'] for i, row in enumerate(prod_categories)}
        prod_subcategories = await conn.fetch(
            "SELECT DISTINCT category, subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket') GROUP BY category, subcategory;"
        )
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

@dp.message(Command("menu"))
async def menu_handler(message: types.Message):
    """Команда /menu – вывод главного меню раздела 'Продукты'."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Продукты", callback_data="main_cat:Продукты")
    keyboard = builder.as_markup()
    await message.answer("Выберите категорию:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("main_cat:"))
async def main_category_callback_handler(callback_query: types.CallbackQuery):
    """
    Обработка выбора основной категории.
    Выводит список категорий для раздела 'Продукты'.
    """
    if not MAPPINGS_LOADED:
        await load_category_mappings()
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket') ORDER BY category;"
        )
    await pool.close()
    if not rows:
        await callback_query.answer("Нет категорий в данной секции.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for row in rows:
        category = row["category"]
        cat_id = CATEGORY_ID_MAP["Продукты"][category]
        callback_data = f"category:Продукты:{cat_id}"
        builder.button(text=html.escape(category), callback_data=callback_data)
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(1)
    keyboard = builder.as_markup()
    try:
        await bot.edit_message_text(
            text="Выберите категорию продуктов:",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard
        )
    except Exception:
        await bot.send_message(chat_id=callback_query.message.chat.id,
                               text="Выберите категорию продуктов:",
                               reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("category:"))
async def category_callback_handler(callback_query: types.CallbackQuery):
    """
    Обработка выбора конкретной категории.
    Выводит список подкатегорий для выбранной категории.
    """
    parts = callback_query.data.split(":", 2)
    if len(parts) < 3:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    main_cat, cat_id_str = parts[1], parts[2]
    cat_id = int(cat_id_str)
    category = CATEGORY_NAME_MAP[main_cat][cat_id]
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket') AND category = $1 ORDER BY subcategory;",
            category
        )
    await pool.close()
    if not rows:
        await callback_query.answer("Нет подкатегорий в данной категории.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for row in rows:
        subcat = row["subcategory"]
        subcat_id = SUBCATEGORY_ID_MAP[main_cat][category][subcat]
        # Передаем offset=0 для первой страницы
        callback_data = f"subcat:{main_cat}:{cat_id}:{subcat_id}:0"
        builder.button(text=html.escape(subcat), callback_data=callback_data)
    builder.button(text="Назад", callback_data="main_cat:Продукты")
    builder.adjust(2)
    keyboard = builder.as_markup()
    try:
        await bot.edit_message_text(
            text=f"Выберите подкатегорию в {html.escape(category)}:",
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard
        )
    except Exception:
        await bot.send_message(chat_id=callback_query.message.chat.id,
                               text=f"Выберите подкатегорию в {html.escape(category)}:",
                               reply_markup=keyboard)
    await callback_query.answer()
# --- Команда /compare – сравнение товаров ---
@dp.message(Command("compare"))
async def compare_handler(message: types.Message):
    """
    Обработчик команды /compare.
    Выводит список подкатегорий, где доступны товары из обоих источников (Арбуз и CleverMarket).
    """
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT subcategory, array_agg(DISTINCT source) AS sources
            FROM products
            WHERE source IN ('Арбуз', 'CleverMarket', 'Magnum')
            GROUP BY subcategory
            HAVING COUNT(DISTINCT source) > 1
            ORDER BY subcategory;
        """)
    await pool.close()
    if not rows:
        await message.answer("Нет подкатегорий для сравнения товаров.")
        return
    builder = InlineKeyboardBuilder()
    for row in rows:
        subcat = row["subcategory"]
        # Передаем offset=0 для первой страницы
        builder.button(text=html.escape(subcat), callback_data=f"compare_subcat:Продукты:{subcat}:0")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await message.answer("Выберите подкатегорию для сравнения товаров:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("compare_subcat:"))
async def compare_subcat_callback_handler(callback_query: types.CallbackQuery):
    """
    Обработка выбора подкатегории для сравнения товаров.
    Формирует сообщение с информацией о товарах, разбитой на блоки с пагинацией,
    сортируя товары по цене от дешёвых к дорогим.
    Формат callback_data: compare_subcat:Продукты:{subcat}:{offset}
    """
    try:
        _, main_cat, subcat, offset_str = callback_query.data.split(":", 3)
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    offset = int(offset_str)
    pool = await create_pool()
    async with pool.acquire() as conn:
        arbuz_rows = await conn.fetch("""
            SELECT id, name, price, source, timestamp, link, image
            FROM products
            WHERE subcategory = $1 AND source = 'Арбуз'
            ORDER BY (
                CASE 
                    WHEN regexp_replace(price, '[^0-9.]', '', 'g') ~ '^[0-9]+(\\.[0-9]+)?$' 
                    THEN CAST(regexp_replace(price, '[^0-9.]', '', 'g') AS numeric) 
                    ELSE 9999999 
                END
            ) ASC
            LIMIT 50;
        """, subcat)
        clever_rows = await conn.fetch("""
            SELECT id, name, price, source, timestamp, link, image
            FROM products
            WHERE subcategory = $1 AND source = 'CleverMarket'
            ORDER BY (
                CASE 
                    WHEN regexp_replace(price, '[^0-9.]', '', 'g') ~ '^[0-9]+(\\.[0-9]+)?$'
                    THEN CAST(regexp_replace(price, '[^0-9.]', '', 'g') AS numeric)
                    ELSE 9999999
                END
            ) ASC
            LIMIT 50;
        """, subcat)
    await pool.close()
    if not arbuz_rows and not clever_rows:
        await callback_query.answer("Нет товаров для сравнения в данной подкатегории.", show_alert=True)
        return
    # Формируем товарные блоки (каждый блок – один товар)
    blocks = []
    for row in arbuz_rows:
        block = (
            f"ID: {row['id']}\n"
            f"Название: {html.escape(row['name'])}\n"
            f"Цена: {html.escape(row['price'])}\n"
            f"Категория: {html.escape(subcat)}\n"
            f"Сайт: {html.escape(row['source'])}\n"
            f"Актуально на: {row['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{row['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    for row in clever_rows:
        block = (
            f"ID: {row['id']}\n"
            f"Название: {html.escape(row['name'])}\n"
            f"Цена: {html.escape(row['price'])}\n"
            f"Категория: {html.escape(subcat)}\n"
            f"Сайт: {html.escape(row['source'])}\n"
            f"Актуально на: {row['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{row['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    total_blocks = len(blocks)
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = "<b>Сравнение товаров для подкатегории " + html.escape(subcat) + ":</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data=f"compare_subcat:{main_cat}:{subcat}:{new_offset}"))
    # Кнопка "Назад" возвращает в меню сравнения (команда /compare)
    buttons.append(InlineKeyboardButton(text="Назад", callback_data="compare_back"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    # Используем универсальную функцию для получения фото
    photo_url = get_first_available_photo(arbuz_rows + clever_rows)
    try:
        if photo_url and offset == 0:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=types.InputMediaPhoto(media=photo_url, caption=page_text, parse_mode="HTML"),
                reply_markup=keyboard
            )
        else:
            await bot.edit_message_text(
                text=page_text,
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception:
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text=page_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    await callback_query.answer()


@dp.callback_query(lambda c: c.data == "compare_back")
async def compare_back_callback_handler(callback_query: types.CallbackQuery):
    """Обработка кнопки 'Назад' в сравнении товаров – возвращает в меню /compare."""
    await compare_handler(callback_query.message)
    await callback_query.answer()

# --- Команда /basket – просмотр корзины товаров ---
@dp.message(Command("basket"))
async def basket_handler(message: types.Message):
    """
    Обработчик команды /basket.
    Отображает содержимое корзины пользователя с пагинацией.
    """
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, [])
    if not basket:
        await message.answer("Ваша корзина пуста.")
        return
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("""
                SELECT id, name, price, source, timestamp, link, image
                FROM products
                WHERE id = $1;
            """, prod_id)
            if row:
                items.append(row)
    await pool.close()
    def parse_price(price_str):
        try:
            return float(price_str)
        except (ValueError, TypeError):
            return float('inf')
    items.sort(key=lambda x: parse_price(x["price"]))
    blocks = []
    for item in items:
        block = (
            f"ID: {item['id']}\n"
            f"Название: {html.escape(item['name'])}\n"
            f"Цена: {html.escape(item['price'])}\n"
            f"Категория: {html.escape(item['source'])}\n"
            f"Актуально на: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{item['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    total_blocks = len(blocks)
    # Начинаем с offset=0
    offset = 0
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = "<b>Ваша корзина:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="Назад", callback_data="basket_back"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    photo_url = get_first_available_photo(items)
    try:
        if photo_url:
            await message.answer_photo(photo=photo_url, caption=page_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await message.answer(page_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        await message.answer(page_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("basket:"))
async def basket_pagination_handler(callback_query: types.CallbackQuery):
    """
    Обработка кнопки 'Продолжить' для корзины.
    Выводит следующую страницу блоков товаров из корзины.
    """
    try:
        offset = int(callback_query.data.split(":")[1])
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, [])
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("""
                SELECT id, name, price, source, timestamp, link, image
                FROM products
                WHERE id = $1;
            """, prod_id)
            if row:
                items.append(row)
    await pool.close()
    def parse_price(price_str):
        try:
            return float(price_str)
        except (ValueError, TypeError):
            return float('inf')
    items.sort(key=lambda x: parse_price(x["price"]))
    blocks = []
    for item in items:
        block = (
            f"ID: {item['id']}\n"
            f"Название: {html.escape(item['name'])}\n"
            f"Цена: {html.escape(item['price'])}\n"
            f"Категория: {html.escape(item['source'])}\n"
            f"Актуально на: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{item['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    total_blocks = len(blocks)
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = "<b>Ваша корзина:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="Назад", callback_data="basket_back"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    try:
        await bot.edit_message_text(
            text=page_text,
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    except Exception:
        await bot.send_message(
            chat_id=callback_query.message.chat.id,
            text=page_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "basket_back")
async def basket_back_handler(callback_query: types.CallbackQuery):
    """Обработка кнопки 'Назад' для корзины – перезапуск команды /basket."""
    await basket_handler(callback_query.message)
    await callback_query.answer()

@dp.message(Command("add"))
async def add_command_handler(message: types.Message, state: FSMContext):
    """
    Обработчик команды /add.
    Запрашивает ввод ID товара(ов) для добавления в корзину.
    """
    await state.set_state(AddProductState.waiting_for_product_id)
    await message.answer("Введите ID товара(ов) для добавления в корзину (через пробел):")

@dp.message(AddProductState.waiting_for_product_id)
async def process_add_product(message: types.Message, state: FSMContext):
    """
    Обрабатывает ввод ID товара(ов) и добавляет их в корзину.
    """
    try:
        prod_ids = [int(x) for x in message.text.split()]
    except ValueError:
        await message.answer("Все ID должны быть числами. Попробуйте ещё раз.")
        return
    user_id = message.from_user.id
    if user_id not in BASKETS:
        BASKETS[user_id] = []
    BASKETS[user_id].extend(prod_ids)
    await message.answer(f"Товары с ID {', '.join(map(str, prod_ids))} добавлены в корзину.")
    await state.clear()

@dp.message(Command("order"))
async def order_handler(message: types.Message):
    """
    Обработчик команды /order.
    Формирует заказ на основе товаров в корзине и отправляет кликабельную ссылку для оформления.
    """
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, [])
    if not basket:
        await message.answer("Ваша корзина пуста.")
        return
    order_items = []
    pool = await create_pool()
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("SELECT link FROM products WHERE id = $1;", prod_id)
            if row and row.get("link"):
                order_items.append(row["link"])
    await pool.close()
    order_url = "https://example.com/order?items=" + ",".join(order_items)
    await message.answer(f"Ваш заказ сформирован:\n<a href=\"{order_url}\">Оформить заказ</a>")

@dp.message(Command("ai"))
async def ai_command_handler(message: types.Message, state: FSMContext):
    """
    Обработчик команды /ai.
    Запрашивает ввод запроса для AI.
    """
    await state.set_state(AiState.waiting_for_query)
    context_text = (
        "Я помощник Stratton по покупке еды. Доступные команды: start, support, city, update, menu, compare, basket, order, add, ai.\n"
        "Введите запрос для AI:"
    )
    await message.answer(context_text)

@dp.message(AiState.waiting_for_query)
async def process_ai_request(message: types.Message, state: FSMContext):
    """
    Обрабатывает запрос к AI.
    Отправляет запрос к внешнему API и возвращает ответ пользователю.
    """
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
    except Exception:
        ai_response = "Не удалось получить ответ от AI."
    await message.answer(f"Ответ AI:\n{ai_response}")
    await state.clear()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(dp.start_polling(bot))
