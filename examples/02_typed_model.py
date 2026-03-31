"""
02_typed_model.py — Declared model, explicit schema sync, and CRUD.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, Registry, field

from examples._common import bind_session, sync_registry


class Article(IRISModel):
    _iris_classname = "Demo.Article"

    Title: str = field(required=True, maxlen=500)
    Views: int = field(default=0)


def main() -> None:
    registry = Registry()
    registry.register(Article)

    adapter = sync_registry(registry)
    _adapter, _binder, session = bind_session(registry, adapter=adapter)

    article = Article(Title="Hello explicit runtime", Views=1)
    session.add(article)
    session.commit()

    loaded = session.get(Article, article.pk)
    print("Saved id:", article.pk)
    print("Loaded:", loaded.Title, loaded.Views)


if __name__ == "__main__":
    main()
