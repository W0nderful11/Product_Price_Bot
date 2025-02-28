import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_CONFIG = {
    "user": os.getenv("DATABASE_USER"),
    "password": os.getenv("DATABASE_PASSWORD"),
    "database": os.getenv("DATABASE_NAME"),
    "host": os.getenv("DATABASE_HOST"),
    "port": os.getenv("DATABASE_PORT"),
}

async def create_pool():
    return await asyncpg.create_pool(**DATABASE_CONFIG)

async def init_db(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
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
        await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops);")

async def insert_product(pool, product):
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO products (code, name, price, category, subcategory, timestamp, source, image, link)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (code, source) DO UPDATE 
            SET price = EXCLUDED.price,
                category = EXCLUDED.category,
                subcategory = EXCLUDED.subcategory,
                timestamp = EXCLUDED.timestamp,
                image = EXCLUDED.image,
                link = EXCLUDED.link;
        """, product.get("code"), product.get("name"), product.get("price"),
           product.get("category", "не определена"), product.get("subcategory", "не определена"),
           product.get("timestamp"), product.get("source"),
           product.get("image"), product.get("link"))

async def save_products(pool, products):
    for product in products:
        try:
            await insert_product(pool, product)
        except Exception as e:
            print(f"Ошибка сохранения товара {product.get('name')}: {e}")

if __name__ == "__main__":
    import asyncio
    from parsers import parse_all
    async def test():
        pool = await create_pool()
        await init_db(pool)
        products = parse_all()
        await save_products(pool, products)
        await pool.close()
    asyncio.run(test())
