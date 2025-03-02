import requests
from bs4 import BeautifulSoup
from datetime import datetime
from utils import get_subcategory  # Импорт универсальной функции

def apply_city(url, city):
    if "arbuz.kz" in url and "almaty" in url:
        return url.replace("almaty", city)
    return url

BASE_URL_ARB = "https://arbuz.kz"

CATEGORY_LINKS_ARB = [
    {"category": "Скидки", "url": "https://arbuz.kz/ru/almaty/discount-catalog/225443-skidki#/"},
    {"category": "Овощи, фрукты, зелень", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225164-ovoshi_frukty_zelen#/"},
    {"category": "Молоко, сыр и яйца", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225161-moloko_syr_i_yaica#/"},
    {"category": "Мясо, птица и рыба", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225162-myaso_ptica_i_ryba#/"},
    {"category": "Фермерская лавка", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225268-fermerskaya_lavka#/"},
    {"category": "Замороженные продукты", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225183-zamorozhennye_produkty#/"},
    {"category": "Хлеб и выпечка", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225165-hleb_i_vypechka#/"},
    {"category": "Колбасы и деликатесы", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225167-kolbasy_i_delikatesy#/"},
    {"category": "Бакалея", "url": "https://arbuz.kz/ru/almaty/catalog/cat/225169-bakaleya#/"}
]

def parse_arbuz(city="almaty"):
    products = []
    for cat in CATEGORY_LINKS_ARB:
        main_category = cat["category"]
        url = apply_city(cat["url"], city)
        print(f"Арбуз. Парсинг категории: {main_category} - {url}")
        try:
            response = requests.get(url)
            response.raise_for_status()
        except Exception as e:
            print(f"Ошибка запроса для категории {main_category} (Арбуз): {e}")
            continue

        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.find_all("article", class_="product-item product-card")
        if not items:
            print(f"Товары не найдены для категории {main_category} (Арбуз)")
            continue

        for item in items:
            try:
                a_tag = item.find("a", class_="product-card__title")
                if not a_tag:
                    print(f"Арбуз ({main_category}): не найден элемент для названия")
                    continue
                title = a_tag.text.strip()

                price_elem = item.find("b")
                if not price_elem:
                    print(f"Арбуз ({main_category}): не найден элемент для цены")
                    continue
                price = price_elem.text.strip()

                img_tag = item.find("img", class_="image")
                image = None
                if img_tag:
                    image = img_tag.get("src")

                link = a_tag.get("href")
                if link and not link.startswith("http"):
                    link = BASE_URL_ARB + link

                code = item.get("data-code")
                timestamp = datetime.now()
                # Используем универсальную функцию для определения подкатегории
                subcategory = get_subcategory(title)

                products.append({
                    "code": code,
                    "name": title,
                    "price": price,
                    "category": main_category,
                    "subcategory": subcategory,
                    "timestamp": timestamp,
                    "source": "Арбуз",
                    "image": image,
                    "link": link
                })
            except Exception as e:
                print(f"Ошибка парсинга товара в категории {main_category} (Арбуз): {e}")
    return products

if __name__ == "__main__":
    for product in parse_arbuz():
        print(product)
