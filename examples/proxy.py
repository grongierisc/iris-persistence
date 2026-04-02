from __future__ import annotations

from iris_orm import IRISModel


class Article(IRISModel):
    class Meta:
        classname = "Demo.Article"
        mode = "proxy"


def main() -> None:
    Article.bind()
    print("fields:", sorted(Article._iris_declared_fields))
    print("storage:", Article._iris_storage)


if __name__ == "__main__":
    main()
