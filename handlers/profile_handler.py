import html
from aiogram import Router, types, Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from db import create_pool
from utils import parse_price, ORDER_HISTORY

profile_router = Router()

async def cabinet_handler(user: types.User, chat_id: int, bot: Bot):
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
        [InlineKeyboardButton(text="📦 История заказов", callback_data="cabinet_history")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])
    await bot.send_message(chat_id, cabinet_text, parse_mode="HTML", reply_markup=keyboard)

@profile_router.callback_query(lambda c: c.data == "cabinet_history" or c.data == "history")
async def cabinet_history_handler(callback_query: types.CallbackQuery):
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
        [InlineKeyboardButton(text="Назад", callback_data="back_to_main")]
    ])

    await callback_query.message.answer(history_text, parse_mode="HTML", reply_markup=keyboard)
    await callback_query.answer()

@profile_router.callback_query(lambda c: c.data == "my_cabinet")
async def cabinet_callback_handler(callback_query: types.CallbackQuery):
    """Вызывает отображение личного кабинета."""
    await cabinet_handler(callback_query.from_user, callback_query.message.chat.id, callback_query.bot)
    await callback_query.answer()
