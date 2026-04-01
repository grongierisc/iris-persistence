"""
02_typed_model.py — Declared python-owned model with direct save/get sugar.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, field


class Article(IRISModel):
    _iris_classname = "Demo.TypedModelArticle"
    _iris_mode = "python"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


def main() -> None:
    article = Article(Title="Hello explicit runtime", Views=1)
    article.save()

    loaded = Article.get(article.pk)
    print("Saved id:", article.pk)
    print("Loaded:", loaded.Title, loaded.Views)


if __name__ == "__main__":
    main()
