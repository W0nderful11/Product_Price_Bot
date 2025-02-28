import asyncpg
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

DATABASE_CONFIG = {
    "user": os.getenv("DATABASE_USER"),
    "password": os.getenv("DATABASE_PASSWORD"),
    "database": os.getenv("DATABASE_NAME"),
    "host": os.getenv("DATABASE_HOST"),
    "port": os.getenv("DATABASE_PORT"),
}

async def reset_db():
    pool = await asyncpg.create_pool(**DATABASE_CONFIG)
    async with pool.acquire() as conn:
        await conn.execute("DROP TABLE IF EXISTS products;")
        await conn.execute("""
            CREATE TABLE products (
                id SERIAL PRIMARY KEY,
                code TEXT,
                name TEXT,
                price TEXT,
                category TEXT,
                subcategory TEXT,
                timestamp TIMESTAMP,
                source TEXT,
                image TEXT,
                link TEXT,
                UNIQUE(code, source)
            );
        """)
        print("Таблица products успешно сброшена и создана заново.")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(reset_db())
