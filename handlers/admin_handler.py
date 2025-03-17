import logging
from aiogram import Router, types
from aiogram.filters import Command
from db import create_pool, init_db, save_products, load_category_mappings
from utils import send_main_menu, update_all_regions
import os

admin_router = Router()
ADMIN_ID = int(os.getenv("ADMIN_ID"))

@admin_router.message(Command("update"))
async def update_handler(message: types.Message):
    """Обновляет данные о товарах (только для администратора)."""
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Разрешено только админам.")
        return

    await message.answer("🔄 Обновление данных... Это может занять некоторое время.")

    try:
        products = await update_all_regions()
    except Exception as e:
        error_text = f"❌ Ошибка при обновлении данных: {e}"
        await message.answer("При возникновении ошибок обращайтесь к @mikoto699")
        logging.error(error_text)
        return

    pool = await create_pool()
    await init_db(pool)
    await save_products(pool, products)
    await load_category_mappings()
    await pool.close()

    await message.answer("✅ Данные успешно обновлены!")
    await send_main_menu(message)
