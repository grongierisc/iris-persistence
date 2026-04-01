from __future__ import annotations

from iris_orm import bind_existing


Article = bind_existing("Demo.Article")


def main() -> None:
    Article.bind()
    print("fields:", sorted(Article._iris_declared_fields))
    print("storage:", Article._iris_storage)


if __name__ == "__main__":
    main()
