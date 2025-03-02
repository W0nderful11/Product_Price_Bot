from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
from datetime import datetime
import time
from utils import get_subcategory  # Импорт универсальной функции

chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(options=chrome_options)

BASE_URL_CLEVER = "https://clevermarket.kz"

CATEGORY_LINKS_CLEVER = [
    {"category": "Хлеб", "url": "https://clevermarket.kz/supermarket/catalog/Khleb/1151"},
    {"category": "Овощи, фрукты, зелень", "url": "https://clevermarket.kz/supermarket/catalog/Ovoshchi-zelen-gribi-solenya/1089"},
    {"category": "Молоко, сыр и яйца", "url": "https://clevermarket.kz/supermarket/catalog/Molochnie-produkti-yaitso/1118"},
    {"category": "Сыры", "url": "https://clevermarket.kz/supermarket/catalog/Siri/1135"},
    {"category": "Выпечка", "url": "https://clevermarket.kz/supermarket/catalog/Pasta-makaroni-lapsha/2225"},
    {"category": "Колбасы и деликатесы", "url": "https://clevermarket.kz/supermarket/catalog/Kolbasi/1186"},
    {"category": "Фрукты, ягоды", "url": "https://clevermarket.kz/supermarket/catalog/Frukti-yagodi/1090"},
    {"category": "Мясо, птица и рыба", "url": "https://clevermarket.kz/supermarket/catalog/Myaso-ptitsa/1162"},
    {"category": "Рыба, морепродукты, икра", "url": "https://clevermarket.kz/supermarket/catalog/Riba-moreprodukti-ikra/1173"},
    {"category": "Полуфабрикаты", "url": "https://clevermarket.kz/supermarket/catalog/Polufabrikati/1202"},
    {"category": "Чай", "url": "https://clevermarket.kz/supermarket/catalog/Chai/2329"}
]

def parse_clevermarket():
    products = []
    for cat in CATEGORY_LINKS_CLEVER:
        main_category = cat["category"]
        url = cat["url"]
        print(f"Парсинг категории: {main_category} - {url}")
        try:
            driver.get(url)
            time.sleep(3)
            page_source = driver.page_source
        except Exception as e:
            print(f"Ошибка при загрузке страницы для категории {main_category}: {e}")
            continue

        soup = BeautifulSoup(page_source, 'html.parser')
        container = soup.select_one("#layout-main > div.product-card-wrapper")
        if container:
            product_cards = container.select("div.product-card.product-card-item")
        else:
            product_cards = soup.find_all("div", class_="product-card product-card-item")
            if not product_cards:
                print(f"Контейнер товаров не найден для категории {main_category}")
                continue

        for card in product_cards:
            try:
                a_tag = card.find("a", href=True)
                if not a_tag:
                    continue
                product_url = a_tag["href"]
                if product_url and not product_url.startswith("http"):
                    product_url = BASE_URL_CLEVER + product_url

                title_tag = a_tag.find("div", class_="product-card-title")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)

                price_tag = card.find("div", class_="text-sm font-semibold flex-grow")
                if not price_tag:
                    continue
                price = price_tag.get_text(strip=True)

                img_tag = a_tag.find("img")
                image = None
                if img_tag:
                    image = img_tag.get("src") or img_tag.get("data-src")
                    if image and "image-placeholder" in image:
                        time.sleep(1)
                        image = img_tag.get("src") or img_tag.get("data-src")
                        if image and "image-placeholder" in image:
                            image = None

                code = product_url.split('/')[-1]
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
                    "source": "CleverMarket",
                    "image": image,
                    "link": product_url
                })
            except Exception as e:
                print(f"Ошибка парсинга товара в категории {main_category} (CleverMarket): {e}")
    return products

if __name__ == "__main__":
    data = parse_clevermarket()
    for product in data:
        print(product)
    driver.quit()
