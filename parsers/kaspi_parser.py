from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from datetime import datetime
import time

BASE_URL_KASPI = "https://kaspi.kz"

CATEGORY_LINKS_KASPI = [
    {"category": "ТЕЛЕФОНЫ И ГАДЖЕТЫ", "url": "https://kaspi.kz/shop/c/smartphones%20and%20gadgets/"},
    {"category": "БЫТОВАЯ ТЕХНИКА", "url": "https://kaspi.kz/shop/c/home%20equipment/"},
    {"category": "ТВ, АУДИО", "url": "https://kaspi.kz/shop/c/tv_audio/"},
    {"category": "КОМПЬЮТЕРЫ", "url": "https://kaspi.kz/shop/c/computers/"},
    {"category": "МЕБЕЛЬ", "url": "https://kaspi.kz/shop/c/furniture/"},
    {"category": "КРАСОТА", "url": "https://kaspi.kz/shop/c/beauty%20care/"},
    {"category": "ДЕТСКИЕ ТОВАРЫ", "url": "https://kaspi.kz/shop/c/child%20goods/"},
    {"category": "АПТЕКА", "url": "https://kaspi.kz/shop/c/pharmacy/"}
]

def parse_kaspi_selenium():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    driver = webdriver.Chrome(options=chrome_options)

    products = []
    for cat in CATEGORY_LINKS_KASPI:
        print(f"Парсинг категории: {cat['category']}")
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
                subcategory = name.split()[0].capitalize() if name.split() else "Не определена"
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
