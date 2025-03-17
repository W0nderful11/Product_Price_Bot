import html
from aiogram import Router, types
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import create_pool
from states import SearchState
from utils import PRODUCTS_PER_PAGE

from parsers.arbuz_parser import parse_arbuz
from parsers.clever_parser import parse_clevermarket
from parsers.kaspi_parser import parse_kaspi

search_router = Router()

@search_router.message(Command("search"))
async def search_command_handler(message: types.Message, state: FSMContext):
    """Обрабатывает команду /search и предлагает выбрать магазин."""
    await state.clear()
    await message.answer("🏪 Выберите магазин:", reply_markup=get_store_selection_keyboard())

@search_router.callback_query(lambda c: c.data == "select_store")
async def select_store_callback_handler(callback_query: types.CallbackQuery):
    """Показывает выбор магазина перед поиском товаров."""
    await callback_query.message.answer("🏪 Выберите магазин:", reply_markup=get_store_selection_keyboard())
    await callback_query.answer()

def get_store_selection_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍉 Арбуз", callback_data="store:arbuz")],
        [InlineKeyboardButton(text="🍀 Клевер", callback_data="store:klever")],
        [InlineKeyboardButton(text="🌊 Каспи", callback_data="store:kaspi")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

@search_router.callback_query(lambda c: c.data.startswith("store:"))
async def store_selection_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Показывает кнопки 'Поиск товара' и 'Сравнение цен' после выбора магазина."""
    store = callback_query.data.split(":")[1]
    await state.update_data(search_store=store)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Поиск товара", callback_data="search_product")],
        [InlineKeyboardButton(text="📊 Сравнение цен", callback_data="search_compare")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="select_store")]
    ])

    await callback_query.message.answer(f"🏪 Выбран магазин: <b>{store.capitalize()}</b>\nВыберите действие:", parse_mode="HTML", reply_markup=keyboard)
    await callback_query.answer()

@search_router.callback_query(lambda c: c.data == "search_product")
async def search_mode_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя название товара для поиска."""
    await callback_query.message.answer("🔍 Введите название товара для поиска:")
    await state.set_state(SearchState.waiting_for_query)
    await callback_query.answer()

@search_router.message(SearchState.waiting_for_query)
async def search_query_handler(message: types.Message, state: FSMContext):
    """Выполняет поиск товаров в выбранном магазине."""
    data = await state.get_data()
    store = data.get("search_store", "arbuz").capitalize()
    query = f"%{message.text.lower()}%"

    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, price, source, link, image FROM products "
            "WHERE source = $1 AND LOWER(name) LIKE $2 ORDER BY price ASC LIMIT 10",
            store, query
        )
    await pool.close()

    if not rows:
        await message.answer(f"❌ В {store} нет товаров по запросу '{message.text}'.")
        return

    texts = [
        f"📌 <b>{html.escape(row['name'])}</b>\n"
        f"💰 Цена: {html.escape(row['price'])}₸\n"
        f"🏪 Магазин: {html.escape(row['source'])}\n"
        f"🔗 <a href=\"{row['link']}\">Ссылка</a>"
        for row in rows
    ]

    result_text = "\n\n".join(texts)
    photo_url = next((row["image"] for row in rows if row.get("image")), None)

    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="store:"+store.lower())
    builder.button(text="🏠 Главное меню", callback_data="back_to_main")
    keyboard = builder.as_markup()

    if photo_url:
        try:
            await message.answer_photo(photo_url, caption=result_text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await message.answer(result_text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message.answer(result_text, parse_mode="HTML", reply_markup=keyboard)

    await state.clear()

async def compare_prices(query):
    """Сравнивает цены на товар во всех магазинах."""
    results = []

    for parser, name in [
        (parse_arbuz, "Арбуз"),
        (parse_clevermarket, "Клевер"),
        (parse_kaspi, "Каспи")
    ]:
        result = await parser(query)
        results.append(f"{name}: {result}")

    return f"📊 <b>Сравнение цен по '{query}':</b>\n\n" + "\n\n".join(results)

@search_router.callback_query(lambda c: c.data == "search_compare")
async def search_compare_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя название товара для сравнения цен."""
    await callback_query.message.answer("🔍 Введите название товара для сравнения во всех магазинах:")
    await state.set_state(SearchState.waiting_for_query)
    await callback_query.answer()
