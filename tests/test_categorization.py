from src.categorization.rules import categorize_rule
from src.categorization.classifier import categorize_operations
import pandas as pd


def test_rules_categorize_rent_and_uncertain_operation():
    rent = categorize_rule({"amount": -1000, "purpose": "Арендная плата", "counterparty": "БЦ"})
    unknown = categorize_rule({"amount": -1000, "purpose": "прочее", "counterparty": ""})
    assert rent["category"] == "Аренда"
    assert unknown["category"] == "Требует проверки"
    assert unknown["needs_review"]


def test_client_revenue_rule():
    result = categorize_rule({"amount": 500, "purpose": "Оплата от клиента за услуги"})
    assert result["category"] == "Выручка и поступления от клиентов"


def test_bank_phrases_are_categorized_and_vague_purpose_stays_for_review():
    assert categorize_rule({"amount": 500, "purpose": "Оплата по договору"})["category"] == "Выручка и поступления от клиентов"
    assert categorize_rule({"amount": -500, "purpose": "Перечисление по УПД за комплектующие"})["category"] == "Закупки и поставщики"
    assert categorize_rule({"amount": -500, "purpose": "Оплата поставки без НДС"})["category"] == "Закупки и поставщики"
    assert categorize_rule({"amount": 500, "purpose": "Выплата заработной платы"})["category"] == "Требует проверки"
    for purpose in ("", "прочее", "оплата", "перевод", "без НДС"):
        result = categorize_rule({"amount": -500, "purpose": purpose})
        assert result == {"category": "Требует проверки", "method": "правила", "confidence": 0.5, "needs_review": True}


def test_user_labeled_examples_enable_classifier_without_fabricated_labels():
    frame = pd.DataFrame([
        {"date": pd.Timestamp("2025-01-01") + pd.Timedelta(days=i), "amount": -100.0,
         "purpose": "commercial premises monthly contract", "counterparty": "property operator", "inn": "",
         "category": "Аренда", "category_source": "manual"}
        for i in range(4)
    ] + [
        {"date": pd.Timestamp("2025-02-01") + pd.Timedelta(days=i), "amount": -200.0,
         "purpose": "bulk materials supplier invoice", "counterparty": "wholesale supplier", "inn": "",
         "category": "Закупки и поставщики", "category_source": "manual"}
        for i in range(4)
    ] + [
        {"date": pd.Timestamp("2025-03-01"), "amount": -300.0,
         "purpose": "commercial premises monthly invoice", "counterparty": "property operator", "inn": "",
         "category": "", "category_source": ""}
    ])
    categorized = categorize_operations(frame)
    assert categorized.iloc[-1]["category"] == "Аренда"
    assert categorized.iloc[-1]["method"] == "ML"
