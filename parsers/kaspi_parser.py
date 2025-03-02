from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime
import time
from utils import get_subcategory

BASE_URL_KASPI = "https://kaspi.kz"

# Обновлённый список категорий для Kaspi – имена подобраны как в Arbuz,
# а ссылки – взяты из предоставленного списка.
CATEGORY_LINKS_KASPI = [
    {"category": "Скидки", "url": "https://kaspi.kz/shop/c/food/"},
    {"category": "Молоко, сыр и яйца", "url": "https://kaspi.kz/shop/c/dairy%20and%20eggs/?q=%3Acategory%3ADairy%20and%20eggs%3AavailableInZones%3AMagnum_ZONE1&sort=relevance&sc="},
    {"category": "Овощи, фрукты, зелень", "url": "https://kaspi.kz/shop/c/fruits%20and%20vegetables/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3AFruits%20and%20vegetables&sort=relevance&sc="},
    # Если требуется разбить выпечку на два запроса – можно использовать оба варианта под одним именем
    {"category": "Хлеб и выпечка", "url": "https://kaspi.kz/shop/c/pastry/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3APastry&sort=relevance&sc="},
    {"category": "Хлеб и выпечка", "url": "https://kaspi.kz/shop/c/bread%20and%20bakery/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3ABread%20and%20bakery&sort=relevance&sc="},
    {"category": "Колбасы и деликатесы", "url": "https://kaspi.kz/shop/c/sausages%20and%20meat%20delicacies/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3ASausages%20and%20meat%20delicacies&sort=relevance&sc="},
    # Для категорий «Мясо, птица и рыба» используем два запроса (например, для морепродуктов и для мяса)
    {"category": "Мясо, птица и рыба", "url": "https://kaspi.kz/shop/c/seafood/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3ASeafood&sort=relevance&sc="},
    {"category": "Мясо, птица и рыба", "url": "https://kaspi.kz/shop/c/meat%20and%20poultry/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3AMeat%20and%20poultry&sort=relevance&sc="},
    {"category": "Бакалея", "url": "https://kaspi.kz/shop/c/everything%20for%20baking/?q=%3AavailableInZones%3AMagnum_ZONE1%3Acategory%3AEverything%20for%20baking&sort=relevance&sc="}
]

def parse_kaspi_selenium():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)

    products = []
    for cat in CATEGORY_LINKS_KASPI:
        print(f"Парсинг категории: {cat['category']} - {cat['url']}")
        try:
            driver.get(cat["url"])
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div.item-card"))
            )
        except Exception as e:
            print(f"Не удалось загрузить карточки товаров для категории {cat['category']}: {e}")
            continue

        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        grid = soup.find("div", class_="item-cards-grid")
        if not grid:
            print(f"Контейнер с товарами не найден на Kaspi ({cat['category']})")
            continue

        cards_container = grid.find("div", class_="item-cards-grid__cards")
        if cards_container:
            cards = cards_container.find_all("div", class_="item-card ddl_product ddl_product_link undefined")
        else:
            cards = grid.find_all("div", class_="item-card ddl_product ddl_product_link undefined")

        if not cards:
            print(f"Товары не найдены для категории Kaspi ({cat['category']})")
            continue

        for card in cards:
            try:
                code = card.get("data-product-id")
                image_tag = card.find("a", class_="item-card__image-wrapper").find("img")
                image = None
                if image_tag:
                    image = image_tag.get("src") or image_tag.get("data-src")
                name_tag = card.find("a", class_="item-card__name-link")
                name = name_tag.text.strip() if name_tag else "Не определено"
                link = name_tag.get("href") if name_tag else ""
                if link and not link.startswith("http"):
                    link = BASE_URL_KASPI + link
                price_tag = card.find("span", class_="item-card__prices-price")
                price = price_tag.text.strip() if price_tag else "0"
                # Используем первое слово из названия для определения подкатегории
                subcategory = get_subcategory(name)
                timestamp = datetime.now()
                products.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "category": cat["category"],
                    "subcategory": subcategory,
                    "timestamp": timestamp,
                    "source": "Kaspi",
                    "image": image,
                    "link": link
                })
            except Exception as e:
                print(f"Ошибка парсинга товара в категории {cat['category']}: {e}")
    driver.quit()
    return products

parse_kaspi = parse_kaspi_selenium

if __name__ == "__main__":
    data = parse_kaspi()
    if data:
        for product in data:
            print(product)
    else:
        print("Данные не получены.")
