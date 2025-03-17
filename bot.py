from aiogram import Bot, Dispatcher
from dotenv import load_dotenv
from handlers.start_handler import start_router
from handlers.product_handler import product_router
from handlers.cart_handler import cart_router
from handlers.misc_handler import misc_router
from handlers.search_handler import search_router
from handlers.profile_handler import profile_router
from handlers.admin_handler import admin_router
import asyncio
import logging
import os

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

dp.include_router(start_router)
dp.include_router(product_router)
dp.include_router(cart_router)
dp.include_router(misc_router)
dp.include_router(profile_router)
dp.include_router(admin_router)
dp.include_router(search_router)

if __name__ == "__main__":
    async def main():
        logging.basicConfig(level=logging.INFO)
        from utils import periodic_update
        asyncio.create_task(periodic_update())
        await dp.start_polling(bot)

    asyncio.run(main())
