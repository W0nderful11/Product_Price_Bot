import aiohttp
import os
from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from states import SupportState
from utils import send_main_menu
from states import AiState
from aiogram.filters import Command
from dotenv import load_dotenv

misc_router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID"))
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@misc_router.callback_query(lambda c: c.data == "support")
async def support_callback_handler(callback_query: types.CallbackQuery):
    """Отображает меню поддержки с кнопками."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")],
        [InlineKeyboardButton(text="✉ Написать сообщение", callback_data="support_write")],
        [InlineKeyboardButton(text="🤖 Ответ от ИИ", callback_data="ai")]
    ])

    await callback_query.message.answer(
        "📩 При возникновении ошибок обращайтесь к @mikoto699", reply_markup=keyboard
    )
    await callback_query.answer()

@misc_router.callback_query(lambda c: c.data == "support_write")
async def support_write_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Устанавливает состояние для ввода сообщения в поддержку."""
    await state.set_state(SupportState.waiting_for_message)
    await callback_query.message.answer("📝 Напишите ваше письмо – администратор свяжется с вами.")
    await callback_query.answer()

@misc_router.message(SupportState.waiting_for_message)
async def process_support_message(message: types.Message, state: FSMContext):
    """Пересылает сообщение пользователя администратору."""
    user_info = f"📩 Сообщение от {message.from_user.username and ('@' + message.from_user.username) or message.from_user.full_name} (ID: {message.from_user.id}):"
    await message.bot.send_message(ADMIN_ID, f"{user_info}\n\n{message.text}")

    await message.answer("✅ Ваше сообщение отправлено. Администратор свяжется с вами.")
    await state.clear()
    await send_main_menu(message)

@misc_router.callback_query(lambda c: c.data == "back_to_main")
async def back_to_main_handler(callback_query: types.CallbackQuery):
    """Возвращает пользователя в главное меню."""
    await send_main_menu(callback_query.message)
    await callback_query.answer()

@misc_router.message(Command("ai"))
async def ai_command_handler(message: types.Message, state: FSMContext):
    """Переводит пользователя в режим ожидания запроса к AI."""
    await state.set_state(AiState.waiting_for_query)
    context_text = (
        "🤖 Я помощник Stratton по покупке еды.\n"
        "📌 Доступные функции:\n"
        "- 🛍 Продукты\n"
        "- 👤 Личный кабинет\n"
        "- 🔎 Поиск\n\n"
        "- - 📩 Остальное\n"
        "✏ Введите ваш запрос для AI:"
    )
    await message.answer(context_text)

@misc_router.callback_query(lambda c: c.data == "ai")
async def ai_callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Переводит пользователя в режим ожидания запроса к AI через кнопку."""
    await state.set_state(AiState.waiting_for_query)
    context_text = (
        "🤖 Я помощник Stratton по покупке еды.\n"
        "📌 Доступные функции:\n"
        "- 🛍 Продукты\n"
        "- 👤 Личный кабинет\n"
        "- 🔎 Поиск\n\n"
        "- - 📩 Остальное\n"
        "✏ Введите ваш запрос для AI:"
    )
    await callback_query.message.answer(context_text)
    await callback_query.answer("🚀 Функция AI запущена.", show_alert=True)

@misc_router.message(AiState.waiting_for_query)
async def process_ai_request(message: types.Message, state: FSMContext):
    """Обрабатывает запрос пользователя к AI через API Gemini."""
    user_prompt = message.text.strip()
    prompt = "Ты помощник Stratton по покупке еды. " + user_prompt

    if not GEMINI_API_KEY:
        await message.answer("❌ AI-ключ не найден в .env")
        await state.clear()
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    headers = {"Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=10) as resp:
                if resp.status != 200:
                    await message.answer(f"❌ Ошибка AI: {resp.status}")
                    await state.clear()
                    return
                result = await resp.json()
        ai_response = (result.get("candidates", [{}])[0]
                       .get("content", {})
                       .get("parts", [{}])[0]
                       .get("text", "Не удалось получить ответ от AI."))
    except Exception:
        ai_response = "❌ Не удалось получить ответ от AI."

    await message.answer(f"🤖 <b>Ответ AI:</b>\n{ai_response}", parse_mode="HTML")
    await state.clear()
    await send_main_menu(message)

@misc_router.callback_query(lambda c: c.data == "other_menu")
async def support_callback_handler(callback_query: types.CallbackQuery):
    """Выводит информацию о технической поддержке с кнопкой назад."""
    context_text = (
        "🛠 <b>Техническая поддержка</b>\n\n"
        "Если у вас возникли вопросы, ошибки или проблемы с ботом, "
        "вы можете обратиться за помощью.\n\n"
        "📩 <b>Напишите администратору:</b> @mikoto699"
    )

    await callback_query.message.answer(
        context_text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
    )
    await callback_query.answer()
    
