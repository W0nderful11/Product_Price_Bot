import html
from aiogram import Router, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from aiogram.utils.keyboard import InlineKeyboardBuilder
from db import create_pool, load_category_mappings
from utils import CATEGORY_ID_MAP, MAPPINGS_LOADED, CATEGORY_NAME_MAP, SUBCATEGORY_ID_MAP, SUBCATEGORY_NAME_MAP, parse_price, get_first_available_photo, PRODUCTS_PER_PAGE, compute_similarity

product_router = Router()

@product_router.callback_query(lambda c: c.data and c.data.startswith("main_cat:"))
async def main_category_callback_handler(callback_query: types.CallbackQuery):
    """Выводит список категорий товаров."""
    if not MAPPINGS_LOADED:
        await load_category_mappings()

    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT category FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') ORDER BY category;"
        )
    await pool.close()

    if not rows:
        await callback_query.answer("❌ Нет доступных категорий.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        category = row["category"]
        cat_id = CATEGORY_ID_MAP["Продукты"].get(category, None)
        if cat_id is not None:
            callback_data = f"category:Продукты:{cat_id}"
            builder.button(text=html.escape(category), callback_data=callback_data)

    builder.button(text="🔙 Назад", callback_data="back_to_main")
    builder.adjust(1)
    keyboard = builder.as_markup()

    try:
        await callback_query.message.edit_text(
            text="📦 Выберите категорию продуктов:", reply_markup=keyboard
        )
    except Exception:
        await callback_query.message.answer("📦 Выберите категорию продуктов:", reply_markup=keyboard)

    await callback_query.answer()

@product_router.callback_query(lambda c: c.data and c.data.startswith("category:"))
async def category_callback_handler(callback_query: types.CallbackQuery):
    """Выводит список подкатегорий для выбранной категории."""
    parts = callback_query.data.split(":", 2)
    if len(parts) < 3:
        await callback_query.answer("❌ Некорректные данные.", show_alert=True)
        return

    main_cat, cat_id_str = parts[1], parts[2]

    try:
        cat_id = int(cat_id_str)
        category = CATEGORY_NAME_MAP[main_cat][cat_id]
    except (ValueError, KeyError):
        await callback_query.answer("❌ Ошибка при получении категории.", show_alert=True)
        return

    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT DISTINCT subcategory FROM products WHERE source IN ('Арбуз', 'CleverMarket', 'Kaspi') AND category = $1 ORDER BY subcategory;",
            category
        )
    await pool.close()

    if not rows:
        await callback_query.answer("❌ Нет доступных подкатегорий.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for row in rows:
        subcat = row["subcategory"]
        subcat_id = SUBCATEGORY_ID_MAP[main_cat][category].get(subcat, None)
        if subcat_id is not None:
            callback_data = f"subcat:{main_cat}:{cat_id}:{subcat_id}:0"
            builder.button(text=html.escape(subcat), callback_data=callback_data)

    builder.button(text="🔙 Назад", callback_data="main_cat:Продукты")
    builder.adjust(2)
    keyboard = builder.as_markup()

    try:
        await callback_query.message.edit_text(
            text=f"📦 Выберите подкатегорию в <b>{html.escape(category)}</b>:",
            parse_mode="HTML",
            reply_markup=keyboard
        )
    except Exception:
        await callback_query.message.answer(
            f"📦 Выберите подкатегорию в <b>{html.escape(category)}</b>:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    await callback_query.answer()

@product_router.callback_query(lambda c: c.data and c.data.startswith("subcat:"))
async def subcategory_callback_handler(callback_query: types.CallbackQuery):
    """Выводит список товаров в выбранной подкатегории."""
    try:
        _, main_cat, cat_id_str, subcat_id_str, offset_str = callback_query.data.split(":")
        cat_id = int(cat_id_str)
        subcat_id = int(subcat_id_str)
        offset = int(offset_str)
        category = CATEGORY_NAME_MAP[main_cat][cat_id]
        subcategory = SUBCATEGORY_NAME_MAP[main_cat][category][subcat_id]
    except (ValueError, KeyError):
        await callback_query.answer("❌ Некорректные данные.", show_alert=True)
        return

    pool = await create_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, price, source, timestamp, link, image "
            "FROM products "
            "WHERE category = $1 AND subcategory = $2 "
            "ORDER BY (CASE WHEN regexp_replace(price, '[^0-9.]', '', 'g') ~ '^[0-9]+(\\.[0-9]+)?$' "
            "THEN CAST(regexp_replace(price, '[^0-9.]', '', 'g') AS numeric) ELSE 9999999 END) ASC "
            "LIMIT 100;",
            category, subcategory
        )
    await pool.close()

    if not rows:
        await callback_query.answer("❌ Нет товаров в данной подкатегории.", show_alert=True)
        return

    prices = [parse_price(row['price']) for row in rows if row.get('price')]
    avg_price = sum(prices) / len(prices) if prices else 0.0

    blocks = [
        f"🆔 ID: {row['id']}\n"
        f"📌 Название: {html.escape(row['name'])}\n"
        f"💰 Цена: {html.escape(row['price'])}₸\n"
        f"📉 Экономия: {avg_price - parse_price(row['price']):.2f} ₸" if avg_price > parse_price(row['price']) else ""
        f"🏪 Источник: {html.escape(row['source'])}\n"
        f"📅 Актуально: {row['timestamp'].strftime('%d.%m.%Y %H:%M')}\n"
        f"🔗 <a href=\"{row['link']}\">Ссылка</a>"
        for row in rows
    ]

    total_blocks = len(blocks)
    page_blocks = blocks[offset: offset + PRODUCTS_PER_PAGE]
    page_text = f"<b>📦 Товары в подкатегории {html.escape(subcategory)}:</b>\n\n" + "\n\n".join(page_blocks)
    new_offset = offset + len(page_blocks)

    buttons = []
    if new_offset < total_blocks:
        buttons.append(InlineKeyboardButton(
            text="➡ Далее",
            callback_data=f"subcat:{main_cat}:{cat_id}:{subcat_id}:{new_offset}"
        ))
    buttons.append(InlineKeyboardButton(text="➕ Добавить в корзину", callback_data="add_product_from_product"))
    buttons.append(InlineKeyboardButton(text="🔙 Назад", callback_data="main_cat:Продукты"))
    buttons.append(InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_to_main"))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    photo_url = get_first_available_photo(rows)

    try:
        if offset == 0 and photo_url:
            await callback_query.message.edit_media(
                media=InputMediaPhoto(media=photo_url, caption=page_text, parse_mode="HTML"),
                reply_markup=keyboard
            )
        else:
            await callback_query.message.answer(
                text=page_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
    except Exception:
        await callback_query.message.answer(
            text=page_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    await callback_query.answer()

@product_router.callback_query(lambda c: c.data and c.data.startswith("similar_yes:"))
async def similar_yes_handler(callback_query: types.CallbackQuery):
    """Находит и показывает похожие товары на основе подкатегории и названия."""
    try:
        _, prod_id_str = callback_query.data.split(":")
        prod_id = int(prod_id_str)
    except Exception:
        await callback_query.answer("❌ Некорректные данные.", show_alert=True)
        return

    pool = await create_pool()
    async with pool.acquire() as conn:
        product = await conn.fetchrow("SELECT name, subcategory FROM products WHERE id = $1;", prod_id)
        if not product:
            await callback_query.answer("❌ Товар не найден.", show_alert=True)
            await pool.close()
            return

        subcat = product["subcategory"]
        base_name = product["name"]
        similar_products = await conn.fetch(
            "SELECT id, name, price, source, timestamp, link, image FROM products WHERE subcategory = $1;",
            subcat
        )
    await pool.close()

    similarities = [(prod, compute_similarity(base_name, prod["name"])) for prod in similar_products]
    similarities.sort(key=lambda x: x[1], reverse=True)
    top_similars = similarities[:5]

    if not top_similars:
        await callback_query.answer("❌ Нет похожих товаров.", show_alert=True)
        return

    lines = [
        f"🆔 ID: {prod['id']}\n"
        f"📌 Название: {html.escape(prod['name'])}\n"
        f"💰 Цена: {html.escape(prod['price'])}₸\n"
        f"📊 Сходство: {sim*100:.1f}%\n"
        f"🏪 Источник: {html.escape(prod['source'])}\n"
        f"🔗 <a href=\"{prod['link']}\">Ссылка</a>"
        for prod, sim in top_similars
    ]

    response_text = "<b>🔍 Похожие товары:</b>\n\n" + "\n\n".join(lines)
    photo_url = next((prod["image"] for prod, _ in top_similars if prod.get("image")), None)

    if photo_url:
        await callback_query.message.answer_photo(photo=photo_url, caption=response_text, parse_mode="HTML")
    else:
        await callback_query.message.answer(response_text, parse_mode="HTML")

    await callback_query.answer()

@product_router.callback_query(lambda c: c.data and c.data.startswith("similar_no:"))
async def similar_no_handler(callback_query: types.CallbackQuery):
    """Закрывает уведомление о показе похожих товаров."""
    await callback_query.answer("❌ Вы выбрали, что сходства нет.", show_alert=True)