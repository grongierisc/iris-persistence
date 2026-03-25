"""
iris_orm — IRIS-native Python ORM
==================================

Public API::

    from iris_orm import IRISModel

    class Post(IRISModel):
        _iris_classname = "Demo.Post"

    # Query
    for post in Post.objects.filter(Author="alice"):
        print(post.Title)

    # Create & save
    p = Post.create(Title="Hello", Author="alice")
    p.save()

    # Open by ID
    p = Post.get("1")

    # Delete
    p.delete()

Stub generation::

    python -m iris_orm.stubs Demo.Post ./src/python/
"""
from __future__ import annotations

from .metaclass import IRISMeta, IRISModel
from .query import IRISQuerySet
from .types import iris_type_to_python, iris_type_to_annotation, IRIS_TO_PYTHON

__all__ = [
    "IRISModel",
    "IRISMeta",
    "IRISQuerySet",
    "iris_type_to_python",
    "iris_type_to_annotation",
    "IRIS_TO_PYTHON",
]

__version__ = "0.1.0"
