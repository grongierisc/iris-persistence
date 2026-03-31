"""
03_relationships.py — Relationship declarations with the explicit session runtime.
"""
from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from iris_orm import IRISModel, Registry, field, relationship

from examples._common import bind_session, sync_registry


class Blog(IRISModel):
    _iris_classname = "Demo.Blog"

    Name: str = field(required=True, maxlen=200)
    Posts = relationship("Demo.Post", inverse="Blog", cardinality="children")


class Post(IRISModel):
    _iris_classname = "Demo.Post"

    Title: str = field(required=True, maxlen=500)
    Blog = relationship("Demo.Blog", inverse="Posts", cardinality="parent")


def main() -> None:
    registry = Registry()
    registry.register(Blog)
    registry.register(Post)

    adapter = sync_registry(registry)
    _adapter, _binder, session = bind_session(registry, adapter=adapter)

    blog = Blog(Name="Explicit runtime")
    post = Post(Title="Relationship example")
    post.Blog = blog

    session.add(blog)
    session.add(post)
    session.commit()

    fetched = session.query(Post).filter_eq(Title="Relationship example").first()
    print("Post:", fetched.Title)
    print("Blog:", fetched.Blog.Name if fetched.Blog is not None else None)


if __name__ == "__main__":
    main()
