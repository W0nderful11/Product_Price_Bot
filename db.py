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

MAPPINGS_LOADED = False
CATEGORY_ID_MAP = {'Продукты': {}}
CATEGORY_NAME_MAP = {'Продукты': {}}
SUBCATEGORY_ID_MAP = {'Продукты': {}}
SUBCATEGORY_NAME_MAP = {'Продукты': {}}

async def load_category_mappings():
    """Загружает категории и подкатегории из базы данных."""
    global MAPPINGS_LOADED
    if MAPPINGS_LOADED:
        return

    pool = await create_pool()
    async with pool.acquire() as conn:
        prod_categories = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') ORDER BY category;"
        )
        CATEGORY_ID_MAP['Продукты'] = {row['category']: i for i, row in enumerate(prod_categories)}
        CATEGORY_NAME_MAP['Продукты'] = {i: row['category'] for i, row in enumerate(prod_categories)}

        prod_subcategories = await conn.fetch(
            "SELECT DISTINCT category, subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') GROUP BY category, subcategory;"
        )
        SUBCATEGORY_ID_MAP['Продукты'] = {}
        SUBCATEGORY_NAME_MAP['Продукты'] = {}
        for row in prod_subcategories:
            cat = row['category']
            subcat = row['subcategory']
            if cat not in SUBCATEGORY_ID_MAP['Продукты']:
                SUBCATEGORY_ID_MAP['Продукты'][cat] = {}
                SUBCATEGORY_NAME_MAP['Продукты'][cat] = {}
            subcat_id = len(SUBCATEGORY_ID_MAP['Продукты'][cat])
            SUBCATEGORY_ID_MAP['Продукты'][cat][subcat] = subcat_id
            SUBCATEGORY_NAME_MAP['Продукты'][cat][subcat_id] = subcat

    await pool.close()
    MAPPINGS_LOADED = True

async def create_pool():
    """Создаёт пул подключений к базе данных."""
    try:
        return await asyncpg.create_pool(**DATABASE_CONFIG)
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        return None

async def init_db(pool):
    """Инициализирует базу данных, создаёт таблицы, если их нет."""
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
    """Добавляет или обновляет товар в базе данных."""
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
    """Сохраняет список товаров в базе данных."""
    for product in products:
        try:
            await insert_product(pool, product)
        except Exception as e:
            print(f"Ошибка сохранения товара {product.get('name')}: {e}")

if __name__ == "__main__":
    import asyncio
    from parsers.arbuz_parser import parse_arbuz

    async def test():
        """Тестовое выполнение: инициализация БД, загрузка товаров."""
        pool = await create_pool()
        if pool is None:
            print("Не удалось создать подключение к БД.")
            return

        await init_db(pool)
        products = parse_arbuz()
        await save_products(pool, products)
        await pool.close()

    asyncio.run(test())
