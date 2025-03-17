import html
import asyncio
from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import create_pool
from datetime import datetime
from aiogram.fsm.context import FSMContext
from states import AddProductState
from utils import send_main_menu, BASKETS, ORDER_HISTORY
from utils import PRODUCTS_PER_PAGE, delete_message_later, get_first_available_photo
from states import RemoveProductState


cart_router = Router()

@cart_router.callback_query(lambda c: c.data == "add_product_from_search")
async def add_product_from_search_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Переводит пользователя в режим ожидания ввода ID товара для добавления в корзину."""
    await state.set_state(AddProductState.waiting_for_product_id)
    await callback_query.message.answer(
        "🛒 Напишите ID товара для добавления в корзину (через пробел, можно указывать количество через тире, например: 379-2):"
    )
    await callback_query.answer()

@cart_router.message(AddProductState.waiting_for_product_id)
async def process_add_product(message: types.Message, state: FSMContext):
    """Добавляет товар в корзину по введенному ID."""
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

    if (
        user_id not in ORDER_HISTORY
        or not ORDER_HISTORY[user_id]
        or ORDER_HISTORY[user_id][-1].get("final", True)
    ):
        ORDER_HISTORY.setdefault(user_id, []).append(
            {"date": datetime.now(), "items": BASKETS[user_id].copy(), "final": False}
        )
    else:
        ORDER_HISTORY[user_id][-1]["date"] = datetime.now()
        ORDER_HISTORY[user_id][-1]["items"] = BASKETS[user_id].copy()

    await message.answer(f"🛒 Товары с ID {', '.join(added_items)} успешно добавлены в корзину!")
    await state.clear()
    await send_main_menu(message)

@cart_router.callback_query(lambda c: c.data == "basket")
async def basket_callback_handler(callback_query: types.CallbackQuery):
    """Отображает содержимое корзины пользователя."""
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})

    if not basket:
        sent = await callback_query.message.answer("🛒 Ваша корзина пуста.")
        asyncio.create_task(delete_message_later(sent.chat.id, sent.message_id))
        await callback_query.answer()
        return

    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id, qty in basket.items():
            row = await conn.fetchrow(
                "SELECT id, name, price, source, timestamp, link, image FROM products WHERE id = $1;", prod_id
            )
            if row:
                items.append((row, qty))
    await pool.close()

    def parse_price_local(price_str):
        try:
            return float("".join(ch for ch in price_str if ch.isdigit() or ch == '.'))
        except (ValueError, TypeError):
            return float('inf')

    items.sort(key=lambda x: parse_price_local(x[0]["price"]))

    blocks = [
        f"🆔 ID: {item['id']}\n"
        f"📌 Название: {html.escape(item['name'])}\n"
        f"💰 Цена: {html.escape(item['price'])}₸\n"
        f"🔢 Количество: {qty}\n"
        f"🏪 Источник: {html.escape(item['source'])}\n"
        f"📅 Актуально: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
        f"🔗 <a href=\"{item['link']}\">Ссылка</a>"
        for item, qty in items
    ]

    total_blocks = len(blocks)
    offset = 0
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = "<b>🛒 Ваша корзина:</b>\n\n" + "\n\n".join(page_blocks)

    new_offset = offset + len(page_blocks)
    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(text="➡ Продолжить", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="❌ Удалить товар", callback_data="remove_item"))
    buttons.append(InlineKeyboardButton(text="💳 Оплатить заказ", callback_data="pay_order"))
    buttons.append(InlineKeyboardButton(text="📦 История заказов", callback_data="history"))
    buttons.append(InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product_from_search"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    photo_url = get_first_available_photo([item for item, _ in items])
    try:
        sent = await callback_query.message.answer_photo(photo=photo_url, caption=page_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        sent = await callback_query.message.answer(page_text, parse_mode="HTML", reply_markup=keyboard)

    asyncio.create_task(delete_message_later(sent.chat.id, sent.message_id))
    await callback_query.answer()

@cart_router.callback_query(lambda c: c.data and c.data.startswith("basket:"))
async def basket_pagination_handler(callback_query: types.CallbackQuery):
    """Обрабатывает кнопку 'Продолжить' для перелистывания товаров в корзине."""
    try:
        offset = int(callback_query.data.split(":")[1])
    except Exception:
        await callback_query.answer("❌ Некорректные данные.", show_alert=True)
        return

    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})

    pool = await create_pool()
    items = []
    async with pool.acquire() as conn:
        for prod_id, qty in basket.items():
            row = await conn.fetchrow(
                "SELECT id, name, price, source, timestamp, link, image FROM products WHERE id = $1;", prod_id
            )
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

    if not page_items:
        await callback_query.answer("🔍 Больше товаров в корзине нет.", show_alert=True)
        return

    blocks = [
        f"🆔 ID: {item['id']}\n"
        f"📌 Название: {html.escape(item['name'])}\n"
        f"💰 Цена: {html.escape(item['price'])}₸\n"
        f"🔢 Количество: {qty}\n"
        f"🏪 Источник: {html.escape(item['source'])}\n"
        f"📅 Актуально: {item['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
        f"🔗 <a href=\"{item['link']}\">Ссылка</a>"
        for item, qty in page_items
    ]

    page_text = "<b>🛒 Ваша корзина:</b>\n\n" + "\n\n".join(blocks)

    new_offset = offset + len(page_items)
    buttons = []
    if total_items > new_offset:
        buttons.append(InlineKeyboardButton(text="➡ Далее", callback_data=f"basket:{new_offset}"))
    buttons.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))

    builder = InlineKeyboardBuilder()
    builder.row(*buttons)
    builder.adjust(1)
    keyboard = builder.as_markup()

    photo_url = get_first_available_photo([item for item, _ in items])

    try:
        await callback_query.message.edit_text(text=page_text, parse_mode="HTML", reply_markup=keyboard)
    except Exception:
        if photo_url:
            await callback_query.message.answer_photo(photo=photo_url, caption=page_text, parse_mode="HTML", reply_markup=keyboard)
        else:
            await callback_query.message.answer(text=page_text, parse_mode="HTML", reply_markup=keyboard)

    await callback_query.answer()

@cart_router.callback_query(lambda c: c.data == "remove_item")
async def remove_item_callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Переводит пользователя в режим ожидания ввода ID товара для удаления из корзины."""
    await state.set_state(RemoveProductState.waiting_for_remove_id)
    await callback_query.message.answer(
        "🗑 Введите ID товара для удаления из корзины (например: 379 или 379-2):"
    )
    await callback_query.answer()

@cart_router.message(RemoveProductState.waiting_for_remove_id)
async def process_remove_item(message: types.Message, state: FSMContext):
    """Удаляет товар из корзины по введенному ID."""
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
    await message.answer(f"🗑 Обновленная корзина. Удалены: {', '.join(removal_results)}")
    await state.clear()
    await send_main_menu(message)

@cart_router.callback_query(lambda c: c.data == "pay_order")
async def pay_order_handler(callback_query: types.CallbackQuery):
    """Оформляет заказ, очищает корзину и отправляет ссылку на оплату."""
    user_id = callback_query.from_user.id
    basket = BASKETS.get(user_id, {})

    if not basket:
        await callback_query.answer("❌ Ваша корзина пуста.", show_alert=True)
        return

    order_date = datetime.now()
    if (
        user_id not in ORDER_HISTORY
        or not ORDER_HISTORY[user_id]
        or ORDER_HISTORY[user_id][-1].get("final", True)
    ):
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
    await callback_query.message.answer(f"✅ Ваш заказ сформирован!\n\n<a href=\"{order_url}\">💳 Оформить заказ</a>", parse_mode="HTML")
    
    await callback_query.answer()
    await send_main_menu(callback_query.message)

@cart_router.callback_query(lambda c: c.data == "add_product_from_search")
async def add_product_from_search_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Переводит пользователя в режим ожидания ввода ID товара для добавления в корзину."""
    await state.set_state(AddProductState.waiting_for_product_id)
    await callback_query.message.answer(
        "🛒 Напишите ID товара для добавления в корзину (через пробел, можно указывать количество через тире, например: 379-2):"
    )
    await callback_query.answer()