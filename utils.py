import spacy
from collections import Counter

# Загрузка модели spaCy для русского языка
nlp = spacy.load("ru_core_news_sm")

def get_subcategory(name):
    """
    Автоматически определяет подкатегорию продукта, анализируя название.
    Лемматизирует название, извлекает существительные и возвращает наиболее часто встречающееся.
    Если существительных не найдено, возвращает первое слово названия.
    """
    doc = nlp(name)
    nouns = [token.lemma_.lower() for token in doc if token.pos_ == "NOUN"]
    if not nouns:
        return name.split()[0].capitalize() if name.split() else "Не определена"
    most_common = Counter(nouns).most_common(1)[0][0]
    return most_common.capitalize()
