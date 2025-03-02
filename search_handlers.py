from aiogram import types, F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Импортируем парсеры
from parsers.arbuz_parser import parse_arbuz
from parsers.clever_parser import parse_clevermarket
from parsers.kaspi_parser import parse_kaspi

search_router = Router()


# Состояние для ожидания названия товара
class SearchStates(StatesGroup):
    waiting_for_search_query = State()


# Клавиатура функциональная (если надо продублировать тут)
def get_functional_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Меню продуктов", callback_data="menu")],
        [InlineKeyboardButton(text="Повторить предыдущий заказ", callback_data="repeat_order")],
        [InlineKeyboardButton(text="Корзина", callback_data="basket")],
        [InlineKeyboardButton(text="Связь с админом", callback_data="support")],
        [InlineKeyboardButton(text="Ответ от ИИ", callback_data="ai")],
        [InlineKeyboardButton(text="🔎 Поиск товара", callback_data="search")]
    ])


# Клавиатура выбора режима поиска
def get_search_mode_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Поиск по Арбузу", callback_data="search_arbuz")],
        [InlineKeyboardButton(text="🔎 Поиск по Клеверу", callback_data="search_klever")],
        [InlineKeyboardButton(text="🔎 Поиск по Каспи", callback_data="search_kaspi")],
        [InlineKeyboardButton(text="🔎 Сравнение цен по всем", callback_data="search_compare")]
    ])


# Обработка нажатия "Поиск товара"
@search_router.callback_query(F.data == "search")
async def search_callback_handler(callback: types.CallbackQuery):
    await callback.message.answer("Выберите режим поиска:", reply_markup=get_search_mode_keyboard())


# Обработка выбора магазина
@search_router.callback_query(F.data.startswith('search_'))
async def search_by_store(callback: types.CallbackQuery, state: FSMContext):
    store = callback.data.replace('search_', '')
    await state.update_data(search_store=store)

    if store == 'compare':
        await callback.message.answer("Введите название товара для сравнения во всех магазинах:")
    else:
        await callback.message.answer(f"Введите название товара для поиска в {store.capitalize()}:")

    await state.set_state(SearchStates.waiting_for_search_query)


# Обработка ввода товара и вызов нужного парсера
@search_router.message(F.text, SearchStates.waiting_for_search_query)
async def process_search_query(message: types.Message, state: FSMContext):
    data = await state.get_data()
    store = data.get('search_store')
    query = message.text.strip()

    if store == 'arbuz':
        result = await parse_arbuz(query)
    elif store == 'klever':
        result = await parse_clevermarket(query)
    elif store == 'kaspi':
        result = await parse_kaspi(query)
    elif store == 'compare':
        result = await compare_prices(query)
    else:
        result = "Неизвестный магазин."

    await message.answer(result)
    await state.clear()


# Функция для сравнения цен
async def compare_prices(query):
    results = []

    for parser, name in [
        (parse_arbuz, "Арбуз"),
        (parse_clevermarket, "Клевер"),
        (parse_kaspi, "Каспи")
    ]:
        result = await parser(query)
        results.append(f"{name}: {result}")

    return f"Сравнение цен по '{query}':\n\n" + "\n\n".join(results)
