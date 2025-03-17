import asyncio
import logging
import spacy
from aiogram import types
from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import create_pool, init_db, save_products, load_category_mappings
from parsers import parse_all
from bot_instance import bot


BASKETS = {}
USER_CITIES = {}
ORDER_HISTORY = {}
CATEGORY_ID_MAP = {'Продукты': {}}
CATEGORY_NAME_MAP = {'Продукты': {}}
SUBCATEGORY_ID_MAP = {'Продукты': {}}
SUBCATEGORY_NAME_MAP = {'Продукты': {}}
MAPPINGS_LOADED = False
PRODUCTS_PER_PAGE = 5

# -------------------------------
# Фоновое обновление каждые 3 дня и обновление для всех регионов
# -------------------------------
async def update_all_regions():
    regions = ["almaty", "astana", "shymkent"]
    all_products = []
    for region in regions:
        # parse_all – асинхронная функция, вызывается напрямую
        products = await parse_all(city=region)
        all_products.extend(products)
    return all_products

async def periodic_update():
    # Ждем 3 дня (259200 секунд) между обновлениями
    while True:
        await asyncio.sleep(259200)
        try:
            products = await update_all_regions()
            pool = await create_pool()
            await init_db(pool)
            await save_products(pool, products)
            await load_category_mappings()
            await pool.close()
            logging.info("Автоматическое обновление выполнено успешно.")
        except Exception as e:
            logging.error(f"Ошибка автоматического обновления: {e}")

# -------------------------------
# Вспомогательные функции и утилиты
# -------------------------------
async def delete_message_later(chat_id, message_id, delay=120):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.error(f"Ошибка удаления сообщения {message_id} в чате {chat_id}: {e}")

def get_user_city(user_id):
    return USER_CITIES.get(user_id, "almaty")

def parse_price(price_str):
    try:
        return float("".join(ch for ch in price_str if ch.isdigit() or ch == '.'))
    except (ValueError, TypeError):
        return float('inf')

def compute_similarity(text1, text2):
    doc1 = nlp(text1)
    doc2 = nlp(text2)
    return doc1.similarity(doc2)

def get_first_available_photo(rows):
    for row in rows:
        image = row.get("image")
        if image and image.strip():
            fixed_image = image.replace("%w", "600").replace("%h", "600")
            return fixed_image
    return "https://via.placeholder.com/150"

async def send_main_menu(message: types.Message):
    user_id = message.from_user.id
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🛍 Продукты", callback_data="select_store"),
        InlineKeyboardButton(text="👤 Личный кабинет", callback_data="my_cabinet")
    )

    builder.row(
        InlineKeyboardButton(text="👨‍💻 Техническая поддержка", callback_data="other_menu")
    )
    
    keyboard = builder.as_markup()
    await message.answer(
        "📌 <b>Главное меню</b>\n"
        "Выберите нужный раздел:", reply_markup=keyboard, parse_mode="HTML"
    )

async def send_other_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    
    builder.row(
        InlineKeyboardButton(text="🛒 Корзина", callback_data="basket"),
        InlineKeyboardButton(text="📩 Связь с администратором", callback_data="support")
    )
    
    builder.row(
        InlineKeyboardButton(text="🌍 Изменить город", callback_data="city:change")
    )
    
    keyboard = builder.as_markup()
    await message.answer(
        "📦 Дополнительные функции:", reply_markup=keyboard
    )

nlp = spacy.load("ru_core_news_sm")