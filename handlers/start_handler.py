from aiogram import Router, types
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ContentType,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils import send_main_menu, USER_CITIES
from bot_instance import bot

start_router = Router()

class RegistrationState(StatesGroup):
    choosing_city = State()
    sharing_contact = State()

INSTRUCTION_TEXT = """
👋 <b>Добро пожаловать!</b>

🔹 <b>Как пользоваться ботом?</b>
- 🛍 <b>"Продукты"</b> — посмотреть ассортимент товаров.
- 👤 <b>"Личный кабинет"</b> — информация о ваших заказах.
- 👨‍💻 <b>"Техническая поддержка"</b> — связаться с администратором при возникновении вопросов.
"""

async def send_city_selection(chat_id, is_new_user=True):
    """Отправляет пользователю меню выбора города."""
    buttons = [
        [InlineKeyboardButton(text="🏔️ Алматы", callback_data="city:almaty")],
        [InlineKeyboardButton(text="🏙️ Астана", callback_data="city:astana")],
        [InlineKeyboardButton(text="☀️ Шымкент", callback_data="city:shymkent")],
    ]

    if not is_new_user:
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cancel_city_change")])

    builder = InlineKeyboardMarkup(inline_keyboard=buttons)

    text = "🌍 Выберите ваш город:" if is_new_user else "🌍 Выберите новый город:"
    await bot.send_message(chat_id, text, reply_markup=builder)

@start_router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    """Обрабатывает команду /start, сначала спрашивает город, затем телефон."""
    await state.set_state(RegistrationState.choosing_city)
    await send_city_selection(message.chat.id, is_new_user=True)

@start_router.callback_query(lambda c: c.data.startswith("city:"), RegistrationState.choosing_city)
async def city_callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    """Сохраняет город и запрашивает номер телефона только при первом выборе."""
    city_code = callback_query.data.split(":")[1]
    
    USER_CITIES[callback_query.from_user.id] = city_code
    await state.update_data(city=city_code)

    await callback_query.message.answer(
        f"🌍 Ваш город: {city_code.capitalize()} выбран!\n\n📲 Теперь поделитесь своим контактом для продолжения."
    )

    share_button = KeyboardButton(text="📲 Поделиться контактом", request_contact=True)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[[share_button]], resize_keyboard=True, one_time_keyboard=True
    )

    await state.set_state(RegistrationState.sharing_contact)
    await callback_query.message.answer("👤 Нажмите кнопку ниже, чтобы поделиться контактом:", reply_markup=keyboard)
    await callback_query.answer()

@start_router.callback_query(lambda c: c.data.startswith("city:"))
async def change_city_callback_handler(callback_query: types.CallbackQuery):
    """Изменяет город и возвращает главное меню."""
    city_code = callback_query.data.split(":")[1]
    
    USER_CITIES[callback_query.from_user.id] = city_code
    await callback_query.message.answer(f"🌍 Ваш город изменён на: {city_code.capitalize()}!")

    await callback_query.message.answer(INSTRUCTION_TEXT, parse_mode="HTML")

    await send_main_menu(callback_query.message)

    await callback_query.answer()

@start_router.callback_query(lambda c: c.data == "cancel_city_change")
async def cancel_city_change_handler(callback_query: types.CallbackQuery):
    """Позволяет оставить текущий город без изменений."""
    await callback_query.message.answer("✅ Город не изменён.")

    await callback_query.message.answer(INSTRUCTION_TEXT, parse_mode="HTML")

    await send_main_menu(callback_query.message)

    await callback_query.answer()

@start_router.message(RegistrationState.sharing_contact, lambda message: message.content_type == ContentType.CONTACT)
async def contact_handler(message: types.Message, state: FSMContext):
    """Сохраняет контакт и завершает регистрацию."""
    await message.answer("✅ Спасибо за регистрацию! Вы можете изменить город в любое время с помощью команды /city.")

    await message.answer(INSTRUCTION_TEXT, parse_mode="HTML")

    await state.clear()
    await send_main_menu(message)

@start_router.message(Command("city"))
async def city_handler(message: types.Message, state: FSMContext):
    """Позволяет пользователю изменить город без запроса контакта."""
    await send_city_selection(message.chat.id, is_new_user=False)
    await message.answer("🌍 Выберите новый город или оставьте текущий.")
