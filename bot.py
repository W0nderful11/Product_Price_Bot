import asyncio
import logging
import html
import aiohttp
from datetime import datetime
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
from inline_handler import inline_router
from search_handlers import search_router

from parsers import parse_all  # Функция из parsers/__init__.py
from db import create_pool, init_db, save_products
from utils import nlp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = 784904211  # ID администратора

# Инициализация хранилища состояний и бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher(storage=storage)
dp.include_router(inline_router)
dp.include_router(search_router)

# Глобальные переменные
BASKETS = {}  # { user_id: { product_id: quantity, ... } }
USER_CITIES = {}  # { user_id: city_code }
ORDER_HISTORY = {}  # { user_id: [ {date, items, final}, ... ] }
CATEGORY_ID_MAP = {'Продукты': {}}
CATEGORY_NAME_MAP = {'Продукты': {}}
SUBCATEGORY_ID_MAP = {'Продукты': {}}
SUBCATEGORY_NAME_MAP = {'Продукты': {}}
MAPPINGS_LOADED = False
PRODUCTS_PER_PAGE = 5

# -------------------------------
# Функция для отправки меню выбора города
# -------------------------------
async def send_city_selection(chat_id):
    builder = InlineKeyboardBuilder()
    cities = {"Алматы": "almaty", "Астана": "astana", "Шымкент": "shymkent"}
    for name, code in cities.items():
        builder.button(text=name, callback_data=f"city:{code}")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.adjust(1)
    keyboard = builder.as_markup()
    await bot.send_message(chat_id, "Выберите город:", reply_markup=keyboard)

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
    # По умолчанию возвращаем "almaty", если город не выбран
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

# Универсальная функция для получения фото из списка товаров (логика не меняется)
def get_first_available_photo(rows):
    for row in rows:
        image = row.get("image")
        if image and image.strip():
            fixed_image = image.replace("%w", "600").replace("%h", "600")
            return fixed_image
    return "https://via.placeholder.com/150"

async def load_category_mappings():
    global MAPPINGS_LOADED
    pool = await create_pool()
    async with pool.acquire() as conn:
        prod_categories = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') ORDER BY category;"
        )
        CATEGORY_ID_MAP['Продукты'] = {row['category']: i for i, row in enumerate(prod_categories)}
        CATEGORY_NAME_MAP['Продукты'] = {i: row['category'] for i, row in enumerate(prod_categories)}
        prod_subcategories = await conn.fetch(
            "SELECT DISTINCT category, subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') GROUP BY category, subcategory;"
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

# -------------------------------
# FSM-состояния
# -------------------------------
class AiState(StatesGroup):
    waiting_for_query = State()

class AddProductState(StatesGroup):
    waiting_for_product_id = State()

class RemoveProductState(StatesGroup):
    waiting_for_remove_id = State()

class SupportState(StatesGroup):
    waiting_for_message = State()

class SearchState(StatesGroup):
    waiting_for_query = State()

# -------------------------------
# Функция "Мой кабинет"
# -------------------------------
async def cabinet_handler(user: types.User, chat_id: int):
    username = ("@" + user.username) if user.username else user.full_name or "Пользователь"
    user_id = user.id
    order_list = ORDER_HISTORY.get(user_id, [])
    total_spent = 0.0
    total_saved = 0.0
    pool = await create_pool()
    async with pool.acquire() as conn:
        for order in order_list:
            for prod_id, qty in order.get("items", {}).items():
                row = await conn.fetchrow("SELECT price FROM products WHERE id = $1;", prod_id)
                if row:
                    price = parse_price(row["price"])
                    total_spent += price * qty
                    total_saved += price * qty * 0.1
    await pool.close()
    cabinet_text = (f"<b>Мой кабинет</b>\n\n"
                    f"Пользователь: {html.escape(username)}\n"
                    f"Общая сумма потраченных средств: {total_spent:.2f} ₸\n"
                    f"Сэкономлено: {total_saved:.2f} ₸\n")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="История заказов", callback_data="cabinet_history")],
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main"),
         InlineKeyboardButton(text="Главное меню", callback_data="back_to_main")]
    ])
    await bot.send_message(chat_id, cabinet_text, parse_mode="HTML", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data == "cabinet_history" or c.data == "history")
async def cabinet_history_handler(callback_query: types.CallbackQuery):
    # Используем общую логику истории заказов для кабинета и корзины
    user_id = callback_query.from_user.id
    orders = ORDER_HISTORY.get(user_id, [])
    if not orders:
        await callback_query.answer("У вас нет заказов.", show_alert=True)
        return
    lines = []
    for order in orders:
        date_str = order["date"].strftime("%d.%m.%Y %H:%M")
        items_str = ", ".join(f"{k}(x{v})" for k, v in order["items"].items())
        status = "Завершён" if order.get("final", False) else "Незавершён"
        lines.append(f"Дата: {date_str}\nЗаказ: {items_str}\nСтатус: {status}")
    history_text = "<b>История заказов:</b>\n\n" + "\n\n".join(lines)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main"),
         InlineKeyboardButton(text="Главное меню", callback_data="back_to_main")]
    ])
    await bot.send_message(callback_query.message.chat.id, history_text, parse_mode="HTML", reply_markup=keyboard)
    await callback_query.answer()

# -------------------------------
# Главное меню (5 кнопок: 2+2+1)
# -------------------------------
async def send_main_menu(message: types.Message):
    user_id = message.from_user.id
    builder = InlineKeyboardBuilder()
    # Первая строка: "Продукты" и "Мой кабинет"
    builder.row(
        InlineKeyboardButton(text="Продукты", callback_data="main_cat:Продукты"),
        InlineKeyboardButton(text="Мой кабинет", callback_data="my_cabinet")
    )
    # Вторая строка: "Корзина" и "Связь с администратором"
    builder.row(
        InlineKeyboardButton(text="Корзина", callback_data="basket"),
        InlineKeyboardButton(text="Связь с администратором", callback_data="support")
    )
    # Третья строка: одна широкая кнопка "Поиск по названию товара"
    builder.row(
        InlineKeyboardButton(text="Поиск по названию товара", callback_data="search_menu")
    )
    # Всегда показываем кнопку "Выбрать город"
    builder.row(
        InlineKeyboardButton(text="Выбрать город", callback_data="city:change")
    )
    keyboard = builder.as_markup()
    await message.answer("Главное меню:", reply_markup=keyboard)

# -------------------------------
# Команды и автоматические действия
# -------------------------------
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    share_button = KeyboardButton(text="Поделиться контактом", request_contact=True)
    keyboard = ReplyKeyboardMarkup(keyboard=[[share_button]], resize_keyboard=True, one_time_keyboard=True)
    await message.answer("Привет! Для авторизации поделитесь, пожалуйста, своим контактом.", reply_markup=keyboard)

@dp.message(lambda message: message.content_type == ContentType.CONTACT)
async def contact_handler(message: types.Message):
    await message.answer("Спасибо за регистрацию!")
    await send_main_menu(message)

@dp.message(Command("update"))
async def update_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Разрешено только админам.")
        return
    await message.answer("Обновление данных... Это может занять некоторое время.")
    try:
        products = await update_all_regions()
    except Exception as e:
        error_text = f"Ошибка при обновлении данных: {e}"
        await bot.send_message(ADMIN_ID, error_text)
        await message.answer("При возникновении ошибок обращайтесь к @mikoto699")
        return
    pool = await create_pool()
    await init_db(pool)
    await save_products(pool, products)
    await load_category_mappings()
    await pool.close()
    await message.answer("Данные успешно обновлены!")
    await send_main_menu(message)

@dp.callback_query(lambda c: c.data == "support")
async def support_callback_handler(callback_query: types.CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main")],
        [InlineKeyboardButton(text="Написать сообщение", callback_data="support_write")],
        [InlineKeyboardButton(text="🤖 Ответ от ИИ", callback_data="ai")]
    ])
    builder = InlineKeyboardBuilder()
    for row in keyboard.inline_keyboard:
        builder.row(*row)
    builder.adjust(1)
    await bot.send_message(callback_query.message.chat.id,
                           "При возникновении ошибок обращайтесь к @mikoto699", reply_markup=builder.as_markup())
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "support_write")
async def support_write_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(SupportState.waiting_for_message)
    await bot.send_message(callback_query.message.chat.id,
                           "Напишите ваше письмо – администратор свяжется с вами.")
    await callback_query.answer()

@dp.message(SupportState.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext):
    user_info = f"Сообщение от {message.from_user.username and ('@' + message.from_user.username) or message.from_user.full_name} (ID: {message.from_user.id}):"
    await bot.send_message(ADMIN_ID, f"{user_info}\n\n{message.text}")
    await message.answer("Ваше сообщение отправлено. Администратор свяжется с вами.")
    await state.clear()
    await send_main_menu(message)

@dp.callback_query(lambda c: c.data == "my_cabinet")
async def cabinet_callback_handler(callback_query: types.CallbackQuery):
    await cabinet_handler(callback_query.from_user, callback_query.message.chat.id)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "search_menu")
async def search_menu_callback_handler(callback_query: types.CallbackQuery):
    builder = InlineKeyboardBuilder()
    # Кнопки поиска (2 в ряд)
    builder.row(
        InlineKeyboardButton(text="Арбуз", callback_data="search_mode:arbuz"),
        InlineKeyboardButton(text="Клевер", callback_data="search_mode:klever")
    )
    builder.row(
        InlineKeyboardButton(text="Каспи", callback_data="search_mode:kaspi"),
        InlineKeyboardButton(text="Сравнение", callback_data="search_mode:compare")
    )
    builder.row(
        InlineKeyboardButton(text="Главное меню", callback_data="back_to_main")
    )
    keyboard = builder.as_markup()
    await bot.send_message(callback_query.message.chat.id, "Выберите режим поиска:", reply_markup=keyboard)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback_query: types.CallbackQuery):
    await send_main_menu(callback_query.message)
    await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("city:"))
async def city_callback_handler(callback_query: types.CallbackQuery):
    data = callback_query.data.split("city:")
    city_code = data[1]
    if city_code == "change":
        await send_city_selection(callback_query.message.chat.id)
    else:
        USER_CITIES[callback_query.from_user.id] = city_code
        # Выводим сообщение с выбранным городом
        await bot.send_message(callback_query.message.chat.id, f"Ваш город выбран: {city_code.capitalize()}")
        await callback_query.answer()
        await send_main_menu(callback_query.message)

@dp.callback_query(lambda c: c.data and c.data.startswith("search_mode:"))
async def search_mode_handler(callback_query: types.CallbackQuery, state: FSMContext):
    mode = callback_query.data.split(":")[1]
    await state.update_data(search_mode=mode)
    await bot.send_message(callback_query.message.chat.id, "Введите название товара для поиска:")
    await state.set_state(SearchState.waiting_for_query)
    await callback_query.answer()

@dp.message(SearchState.waiting_for_query)
async def process_search_query(message: types.Message, state: FSMContext):
    data = await state.get_data()
    mode = data.get("search_mode", "compare")
    query = message.text.strip()
    # Выполняем поиск сначала по версии с первой заглавной буквой, затем с маленькой
    query_cap = query.capitalize()
    query_lower = query.lower()
    user_city = get_user_city(message.from_user.id)
    pool = await create_pool()
    async with pool.acquire() as conn:
        if mode == "compare":
            rows = await conn.fetch(
                "SELECT id, name, price, source, link, image FROM products WHERE (name ILIKE $1 OR name ILIKE $2) AND LOWER(link) LIKE $3 LIMIT 10",
                f"%{query_cap}%", f"%{query_lower}%", f"%{user_city.lower()}%"
            )
        else:
            source = "Арбуз" if mode == "arbuz" else "CleverMarket" if mode == "klever" else "Kaspi"
            rows = await conn.fetch(
                "SELECT id, name, price, source, link, image FROM products WHERE source = $1 AND (name ILIKE $2 OR name ILIKE $3) AND LOWER(link) LIKE $4 LIMIT 10",
                source, f"%{query_cap}%", f"%{query_lower}%", f"%{user_city.lower()}%"
            )
    await pool.close()
    results = list(rows)
    if not results:
        pool = await create_pool()
        async with pool.acquire() as conn:
            sub_rows = await conn.fetch(
                "SELECT DISTINCT subcategory FROM products WHERE subcategory ILIKE $1 LIMIT 5",
                f"%{query}%"
            )
        await pool.close()
        if sub_rows:
            builder = InlineKeyboardBuilder()
            for row in sub_rows:
                subcat = row["subcategory"]
                builder.button(text=html.escape(subcat), callback_data=f"search_subcat:{subcat}")
            builder.button(text="Главное меню", callback_data="back_to_main")
            builder.adjust(1)
            keyboard = builder.as_markup()
            await message.answer("По вашему запросу не найден товар. Возможно, вы имели в виду следующие подкатегории:", reply_markup=keyboard)
        else:
            await message.answer("По вашему запросу ничего не найдено.")
        await state.clear()
        return

    offset = 0
    page = results[offset:offset+PRODUCTS_PER_PAGE]
    texts = []
    for row in page:
        texts.append(
            f"ID: {row['id']}\nНазвание: {html.escape(row['name'])}\nЦена: {html.escape(row['price'])}\nИсточник: {html.escape(row['source'])}\nСсылка: {row['link']}"
        )
    result_text = "\n\n".join(texts)
    photo_url = None
    for row in page:
        if row.get("image"):
            photo_url = row["image"]
            break
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить", callback_data="add_product_from_search")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.button(text="Главное меню", callback_data="back_to_main")
    if len(results) > PRODUCTS_PER_PAGE:
        builder.button(text="Продолжить", callback_data=f"search_continue:1|{mode}|{query}")
    builder.adjust(1)
    keyboard = builder.as_markup()
    if photo_url:
        try:
            await bot.send_photo(message.chat.id, photo=photo_url, caption=result_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await message.answer(result_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(result_text, parse_mode="HTML", reply_markup=keyboard)
    await state.update_data(search_results=results, offset=PRODUCTS_PER_PAGE)
    await state.clear()
    await send_main_menu(message)

@dp.callback_query(lambda c: c.data and c.data.startswith("search_continue:"))
async def search_continue_handler(callback_query: types.CallbackQuery, state: FSMContext):
    data = callback_query.data.split(":", 1)[1]
    try:
        page_str, mode, query = data.split("|")
        page = int(page_str)
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    user_city = get_user_city(callback_query.from_user.id)
    pool = await create_pool()
    async with pool.acquire() as conn:
        if mode == "compare":
            rows = await conn.fetch(
                "SELECT id, name, price, source, link, image FROM products WHERE (name ILIKE $1 OR name ILIKE $2) AND LOWER(link) LIKE $3",
                f"%{query.capitalize()}%", f"%{query.lower()}%", f"%{user_city.lower()}%"
            )
        else:
            source = "Арбуз" if mode == "arbuz" else "CleverMarket" if mode == "klever" else "Kaspi"
            rows = await conn.fetch(
                "SELECT id, name, price, source, link, image FROM products WHERE source = $1 AND (name ILIKE $2 OR name ILIKE $3) AND LOWER(link) LIKE $4",
                source, f"%{query.capitalize()}%", f"%{query.lower()}%", f"%{user_city.lower()}%"
            )
    await pool.close()
    results = list(rows)
    offset = page * PRODUCTS_PER_PAGE
    page_items = results[offset:offset+PRODUCTS_PER_PAGE]
    if not page_items:
        await callback_query.answer("Больше результатов нет.", show_alert=True)
        return
    texts = []
    for row in page_items:
        texts.append(
            f"ID: {row['id']}\nНазвание: {html.escape(row['name'])}\nЦена: {html.escape(row['price'])}\nИсточник: {html.escape(row['source'])}\nСсылка: {row['link']}"
        )
    result_text = "\n\n".join(texts)
    photo_url = None
    for row in page_items:
        if row.get("image"):
            photo_url = row["image"]
            break
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить", callback_data="add_product_from_search")
    builder.button(text="Назад", callback_data="back_to_main")
    builder.button(text="Главное меню", callback_data="back_to_main")
    if len(results) > offset + PRODUCTS_PER_PAGE:
        builder.button(text="Продолжить", callback_data=f"search_continue:{page+1}|{mode}|{query}")
    builder.adjust(1)
    keyboard = builder.as_markup()
    try:
        await bot.edit_message_text(text=result_text,
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=keyboard,
                                    parse_mode="HTML")
    except Exception:
        if photo_url:
            await bot.send_photo(callback_query.message.chat.id, photo=photo_url, caption=result_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await bot.send_message(callback_query.message.chat.id, text=result_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "add_product_from_search")
async def add_product_from_search_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddProductState.waiting_for_product_id)
    await bot.send_message(callback_query.message.chat.id,
                           "Напишите ID товара для добавления в корзину (через пробел, можно указывать количество через тире, например: 379-2):")
    await callback_query.answer()

@dp.message(AddProductState.waiting_for_product_id)
async def process_add_product(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    entries = message.text.split()
    added_items = []
    if user_id not in BASKETS:
        BASKETS[user_id] = {}
    for entry in entries:
        if '-' in entry:
            parts = entry.split('-')
            try:
                prod_id = int(parts[0])
                qty = int(parts[1])
            except ValueError:
                continue
        else:
            try:
                prod_id = int(entry)
                qty = 1
            except ValueError:
                continue
        if prod_id in BASKETS[user_id]:
            BASKETS[user_id][prod_id] += qty
        else:
            BASKETS[user_id][prod_id] = qty
        added_items.append(f"{prod_id} (x{qty})")
    if user_id not in ORDER_HISTORY or not ORDER_HISTORY[user_id] or ORDER_HISTORY[user_id][-1].get("final", True):
        ORDER_HISTORY.setdefault(user_id, []).append({"date": datetime.now(), "items": BASKETS[user_id].copy(), "final": False})
    else:
        ORDER_HISTORY[user_id][-1]["date"] = datetime.now()
        ORDER_HISTORY[user_id][-1]["items"] = BASKETS[user_id].copy()
    await message.answer(f"Товары с ID {', '.join(added_items)} успешно добавлены в корзину!")
    await state.clear()
    await send_main_menu(message)

@dp.callback_query(lambda c: c.data == "basket")
async def basket_callback_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})
    if not basket:
        sent = await bot.send_message(callback_query.message.chat.id, "Ваша корзина пуста.")
        asyncio.create_task(delete_message_later(sent.chat.id, sent.message_id))
        await callback_query.answer()
        return
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id, qty in basket.items():
            row = await conn.fetchrow("SELECT id, name, price, source, timestamp, link, image FROM products WHERE id = $1;", prod_id)
            if row:
                items.append((row, qty))
    await pool.close()
    def parse_price_local(price_str):
        try:
            return float("".join(ch for ch in price_str if ch.isdigit() or ch == '.'))
        except (ValueError, TypeError):
            return float('inf')
    items.sort(key=lambda x: parse_price_local(x[0]["price"]))
    blocks = []
    for item, qty in items:
        block = (
            f"ID: {item['id']}\n"
            f"Название: {html.escape(item['name'])}\n"
            f"Цена: {html.escape(item['price'])}\n"
            f"Количество: {qty}\n"
            f"Источник: {html.escape(item['source'])}\n"
            f"Актуально: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{item['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    total_blocks = len(blocks)
    offset = 0
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = "<b>Ваша корзина:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="Удалить товар", callback_data="remove_item"))
    buttons.append(InlineKeyboardButton(text="Оплатить заказ", callback_data="pay_order"))
    buttons.append(InlineKeyboardButton(text="История заказов", callback_data="history"))
    buttons.append(InlineKeyboardButton(text="Добавить товар", callback_data="add_product_from_search"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    photo_url = get_first_available_photo([item for item, _ in items])
    try:
        sent = await bot.send_photo(callback_query.message.chat.id, photo=photo_url, caption=page_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        sent = await bot.send_message(callback_query.message.chat.id, page_text, parse_mode="HTML", reply_markup=keyboard)
    asyncio.create_task(delete_message_later(sent.chat.id, sent.message_id))
    await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("basket:"))
async def basket_pagination_handler(callback_query: types.CallbackQuery):
    try:
        offset = int(callback_query.data.split(":")[1])
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})
    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id, qty in basket.items():
            row = await conn.fetchrow("SELECT id, name, price, source, timestamp, link, image FROM products WHERE id = $1;", prod_id)
            if row:
                items.append((row, qty))
    await pool.close()
    def parse_price_local(price_str):
        try:
            return float("".join(ch for ch in price_str if ch.isdigit() or ch == '.'))
        except (ValueError, TypeError):
            return float('inf')
    items.sort(key=lambda x: parse_price_local(x[0]["price"]))
    total_items = len(items)
    page_items = items[offset:offset+PRODUCTS_PER_PAGE]
    blocks = []
    for item, qty in page_items:
        block = (
            f"ID: {item['id']}\n"
            f"Название: {html.escape(item['name'])}\n"
            f"Цена: {html.escape(item['price'])}\n"
            f"Количество: {qty}\n"
            f"Источник: {html.escape(item['source'])}\n"
            f"Актуально: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{item['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    page_text = "<b>Ваша корзина:</b>\n\n" + "\n\n".join(blocks)
    new_offset = offset + len(page_items)
    buttons = []
    if total_items > new_offset:
        buttons.append(InlineKeyboardButton(text="Продолжить", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="Главное меню", callback_data="back_to_main"))
    builder = InlineKeyboardBuilder()
    builder.row(*buttons)
    builder.adjust(1)
    keyboard = builder.as_markup()
    photo_url = get_first_available_photo([item for item, _ in items])
    try:
        await bot.edit_message_text(text=page_text,
                                    chat_id=callback_query.message.chat.id,
                                    message_id=callback_query.message.message_id,
                                    reply_markup=keyboard,
                                    parse_mode="HTML")
    except Exception:
        await bot.send_message(callback_query.message.chat.id, page_text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data == "remove_item")
async def remove_item_callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(RemoveProductState.waiting_for_remove_id)
    await bot.send_message(callback_query.message.chat.id,
                           "Введите ID товара для удаления из корзины (например: 379 или 379-2):")
    await callback_query.answer()

@dp.message(RemoveProductState.waiting_for_remove_id)
async def process_remove_item(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    basket = BASKETS.get(user_id, {})
    entries = message.text.split()
    removal_results = []
    for entry in entries:
        if '-' in entry:
            parts = entry.split('-')
            try:
                prod_id = int(parts[0])
                qty = int(parts[1])
            except ValueError:
                continue
        else:
            try:
                prod_id = int(entry)
                qty = basket.get(prod_id, 0)
            except ValueError:
                continue
        if prod_id in basket:
            if basket[prod_id] > qty:
                basket[prod_id] -= qty
                removal_results.append(f"{prod_id} (x{qty})")
            else:
                removal_results.append(f"{prod_id} (all)")
                del basket[prod_id]
        else:
            removal_results.append(f"{prod_id} (не найден)")
    BASKETS[user_id] = basket
    await message.answer(f"Обновленная корзина. Удалены: {', '.join(removal_results)}")
    await state.clear()
    await send_main_menu(message)

@dp.callback_query(lambda c: c.data == "pay_order")
async def pay_order_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})
    if not basket:
        await callback_query.answer("Ваша корзина пуста.", show_alert=True)
        return
    order_date = datetime.now()
    if user_id not in ORDER_HISTORY or not ORDER_HISTORY[user_id] or ORDER_HISTORY[user_id][-1].get("final", True):
        ORDER_HISTORY.setdefault(user_id, []).append({"date": order_date, "items": basket.copy(), "final": True})
    else:
        ORDER_HISTORY[user_id][-1]["date"] = order_date
        ORDER_HISTORY[user_id][-1]["items"] = basket.copy()
        ORDER_HISTORY[user_id][-1]["final"] = True
    BASKETS[user_id] = {}
    order_items = []
    pool = await create_pool()
    async with pool.acquire() as conn:
        for prod_id in basket:
            row = await conn.fetchrow("SELECT link FROM products WHERE id = $1;", prod_id)
            if row and row.get("link"):
                order_items.append(row["link"])
    await pool.close()
    order_url = "https://example.com/order?items=" + ",".join(order_items)
    await bot.send_message(callback_query.message.chat.id, f"Ваш заказ сформирован:\n<a href=\"{order_url}\">Оформить заказ</a>")
    await callback_query.answer()
    await send_main_menu(callback_query.message)

@dp.message(Command("city"))
async def city_handler(message: types.Message):
    """Команда /city – выбор города."""
    builder = InlineKeyboardBuilder()
    cities = {"Алматы": "almaty", "Астана": "astana", "Шымкент": "shymkent"}
    for name, code in cities.items():
        builder.button(text=name, callback_data=f"city:{code}")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await message.answer("Выберите город:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data and c.data.startswith("main_cat:"))
async def main_category_callback_handler(callback_query: types.CallbackQuery):
    if not MAPPINGS_LOADED:
        await load_category_mappings()
    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') ORDER BY category;"
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
            "SELECT DISTINCT subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') AND category = $1 ORDER BY subcategory;",
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

@dp.callback_query(lambda c: c.data and c.data.startswith("subcat:"))
async def subcategory_callback_handler(callback_query: types.CallbackQuery):
    try:
        _, main_cat, cat_id_str, subcat_id_str, offset_str = callback_query.data.split(":")
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    cat_id = int(cat_id_str)
    subcat_id = int(subcat_id_str)
    offset = int(offset_str)
    category = CATEGORY_NAME_MAP[main_cat][cat_id]
    subcategory = SUBCATEGORY_NAME_MAP[main_cat][category][subcat_id]
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
    prices = [parse_price(row['price']) for row in rows if row.get('price')]
    avg_price = sum(prices) / len(prices) if prices else 0.0
    blocks = []
    for row in rows:
        product_price = parse_price(row['price'])
        economy = avg_price - product_price
        economy_text = f"\nЭкономия: {economy:.2f} ₸" if economy > 0 else ""
        block = (
            f"ID: {row['id']}\n"
            f"Название: {html.escape(row['name'])}\n"
            f"Цена: {html.escape(row['price'])}{economy_text}\n"
            f"Источник: {html.escape(row['source'])}\n"
            f"Актуально: {row['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
            f"<a href=\"{row['link']}\">Ссылка</a>"
        )
        blocks.append(block)
    total_blocks = len(blocks)
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = f"<b>Товары подкатегории {html.escape(subcategory)}:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(
            text="Продолжить",
            callback_data=f"subcat:{main_cat}:{cat_id}:{subcat_id}:{new_offset}"
        ))
    buttons.append(InlineKeyboardButton(text="Добавить", callback_data="add_product_from_product"))
    buttons.append(InlineKeyboardButton(text="Назад", callback_data="main_cat:Продукты"))
    buttons.append(InlineKeyboardButton(text="Главное меню", callback_data="back_to_main"))
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    photo_url = get_first_available_photo(rows)
    try:
        if offset == 0 and photo_url:
            await bot.edit_message_media(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                media=types.InputMediaPhoto(media=photo_url, caption=page_text, parse_mode="HTML"),
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=callback_query.message.chat.id,
                text=page_text,
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

@dp.callback_query(lambda c: c.data == "add_product_from_search")
async def add_product_from_search_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(AddProductState.waiting_for_product_id)
    await bot.send_message(callback_query.message.chat.id,
                           "Напишите ID товара для добавления в корзину (через пробел, можно указывать количество через тире, например: 379-2):")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("similar_yes:"))
async def similar_yes_handler(callback_query: types.CallbackQuery):
    try:
        _, prod_id_str = callback_query.data.split(":")
        prod_id = int(prod_id_str)
    except Exception:
        await callback_query.answer("Некорректные данные.", show_alert=True)
        return
    pool = await create_pool()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("SELECT name, subcategory FROM products WHERE id = $1;", prod_id)
        if not product:
            await callback_query.answer("Товар не найден.", show_alert=True)
            await pool.close()
            return
        subcat = product["subcategory"]
        base_name = product["name"]
        similar_products = await conn.fetch("SELECT id, name, price, source, timestamp, link, image FROM products WHERE subcategory = $1;", subcat)
    await pool.close()
    similarities = []
    for prod in similar_products:
        sim = compute_similarity(base_name, prod["name"])
        similarities.append((prod, sim))
    similarities.sort(key=lambda x: x[1], reverse=True)
    top_similars = similarities[:5]
    if not top_similars:
        await callback_query.answer("Нет похожих товаров.", show_alert=True)
        return
    lines = []
    for prod, sim in top_similars:
        line = (
            f"ID: {prod['id']}\nНазвание: {html.escape(prod['name'])}\n"
            f"Цена: {html.escape(prod['price'])}\nСходство: {sim*100:.1f}%\n"
            f"Источник: {html.escape(prod['source'])}\n<a href=\"{prod['link']}\">Ссылка</a>"
        )
        lines.append(line)
    response_text = "<b>Похожие товары:</b>\n\n" + "\n\n".join(lines)
    photo_url = None
    for prod, _ in top_similars:
        if prod.get("image"):
            photo_url = prod["image"]
            break
    if photo_url:
        await bot.send_photo(callback_query.message.chat.id, photo=photo_url, caption=response_text, parse_mode="HTML")
    else:
        await bot.send_message(callback_query.message.chat.id, response_text, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query(lambda c: c.data and c.data.startswith("similar_no:"))
async def similar_no_handler(callback_query: types.CallbackQuery):
    await callback_query.answer("Вы выбрали, что сходства нет.", show_alert=True)

@dp.message(Command("ai"))
async def ai_command_handler(message: types.Message, state: FSMContext):
    await state.set_state(AiState.waiting_for_query)
    context_text = (
        "Я помощник Stratton по покупке еды. Доступны функции: продукты, мой кабинет, корзина, связь с админом, поиск.\n"
        "Введите запрос для AI:"
    )
    await message.answer(context_text)

@dp.callback_query(lambda c: c.data == "ai")
async def ai_callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    await state.set_state(AiState.waiting_for_query)
    context_text = (
        "Я помощник Stratton по покупке еды. Доступны функции: продукты, мой кабинет, корзина, связь с админом, поиск.\n"
        "Введите запрос для AI:"
    )
    await bot.send_message(callback_query.message.chat.id, context_text)
    await callback_query.answer("Функция AI запущена.", show_alert=True)

@dp.message(AiState.waiting_for_query)
async def process_ai_request(message: types.Message, state: FSMContext):
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
    await send_main_menu(message)

@dp.message(Command("city"))
async def city_handler(message: types.Message):
    """Команда /city – выбор города."""
    builder = InlineKeyboardBuilder()
    cities = {"Алматы": "almaty", "Астана": "astana", "Шымкент": "shymkent"}
    for name, code in cities.items():
        builder.button(text=name, callback_data=f"city:{code}")
    builder.adjust(2)
    keyboard = builder.as_markup()
    await message.answer("Выберите город:", reply_markup=keyboard)

if __name__ == "__main__":
    async def main():
        logging.basicConfig(level=logging.INFO)
        # Запускаем фоновое обновление каждые 3 дня
        asyncio.create_task(periodic_update())
        await dp.start_polling(bot)
    asyncio.run(main())
