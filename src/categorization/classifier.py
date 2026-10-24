"""Optional supervised text classifier; never fabricates training labels."""

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import pandas as pd

from src.categorization.rules import categorize_rule


def categorize_operations(frame, training_examples=None):
    """Apply user-provided labels, explainable rules, then optional supervised ML."""
    operations = frame.copy()
    manual = training_examples.copy() if training_examples is not None else operations.iloc[0:0].copy()
    if "category_source" not in operations:
        operations["category_source"] = ""
    else:
        operations["category_source"] = operations["category_source"].fillna("")
    for column, default in (("category", ""), ("method", ""), ("confidence", 0.0), ("needs_review", False)):
        if column not in operations:
            operations[column] = default
    if "category" in operations:
        imported = operations["category"].fillna("").astype(str).str.strip().ne("") & operations["category_source"].eq("")
        operations.loc[imported, "category_source"] = "import"
    labeled = pd.concat([manual, operations.loc[operations["category_source"].isin(["manual", "import"])]])
    labeled = labeled.drop_duplicates(subset=["date", "amount", "counterparty", "purpose"], keep="last")
    classifier = None
    if len(labeled) >= 8 and labeled["category"].nunique() >= 2:
        texts = (labeled["purpose"].fillna("") + " " + labeled["counterparty"].fillna("") + " " + labeled["inn"].fillna("")).tolist()
        try:
            classifier = TransactionClassifier().fit(texts, labeled["category"].astype(str).tolist())
        except ValueError:
            classifier = None
    for index, operation in operations.iterrows():
        if operation["category_source"] in {"manual", "import"}:
            operations.loc[index, ["method", "confidence", "needs_review"]] = ["ручная/импортированная разметка", 1.0, False]
            continue
        result = categorize_rule(operation)
        if result["needs_review"] and classifier is not None:
            text = " ".join(str(operation.get(key, "")) for key in ("purpose", "counterparty", "inn"))
            prediction = classifier.predict(text, minimum_confidence=0.6)
            if not prediction["needs_review"]:
                result = prediction
        for key, value in result.items():
            operations.loc[index, key] = value
        operations.loc[index, "category_source"] = "автоматически"
    return operations


class TransactionClassifier:
    """Train only on explicit user/demo labels and return calibrated proxy scores."""

    def __init__(self) -> None:
        self.pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, max_features=5000)),
            ("model", LogisticRegression(max_iter=500, random_state=42, class_weight="balanced")),
        ])
        self.is_fitted = False

    def fit(self, texts: list[str], labels: list[str], sample_weights: list[float] | None = None) -> "TransactionClassifier":
        if len(texts) < 8 or len(set(labels)) < 2:
            raise ValueError("Для обучения нужно не менее 8 размеченных операций и двух категорий.")
        fit_options = {"model__sample_weight": sample_weights} if sample_weights is not None else {}
        self.pipeline.fit(texts, labels, **fit_options)
        self.is_fitted = True
        return self

    def predict(self, text: str, minimum_confidence: float = 0.55) -> dict[str, object]:
        if not self.is_fitted:
            raise RuntimeError("Классификатор ещё не обучен.")
        probabilities = self.pipeline.predict_proba([text])[0]
        index = int(probabilities.argmax())
        confidence = float(probabilities[index])
        label = str(self.pipeline.classes_[index]) if confidence >= minimum_confidence else "Требует проверки"
        return {"category": label, "method": "ML", "confidence": confidence, "needs_review": label == "Требует проверки"}
