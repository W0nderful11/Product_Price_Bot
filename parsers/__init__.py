from .arbuz_parser import parse_arbuz
from .clever_parser import parse_clevermarket
from .kaspi_parser import parse_kaspi

async def parse_all(city="almaty"):
    products = []
    products.extend(await parse_arbuz(city))
    products.extend(await parse_clevermarket())
    products.extend(await parse_kaspi())
    return products

if __name__ == "__main__":
    import asyncio
    asyncio.run(parse_all())
