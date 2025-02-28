from .arbuz_parser import parse_arbuz
from .clever_parser import parse_clevermarket
from .kaspi_parser import parse_kaspi

def parse_all(city="almaty"):
    products = []
    products.extend(parse_arbuz(city))
    products.extend(parse_clevermarket())
    products.extend(parse_kaspi())
    return products

if __name__ == "__main__":
    for product in parse_all():
        print(product)
