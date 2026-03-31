from __future__ import annotations

from pathlib import Path

from iris_orm.lockfile import load_lockfile
from iris_orm.scaffold import scaffold_from_cls, scaffold_from_iris
from iris_orm.schema import SchemaCompiler

from .fake_runtime import FakeAdapter, preload_schema


def test_scaffold_from_iris_writes_model_and_lockfile(tmp_path: Path):
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclass": "%Persistent",
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 500, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    paths = scaffold_from_iris("Demo.*", tmp_path / "generated", conn=adapter)
    assert len(paths) == 1
    model_source = paths[0].read_text(encoding="utf-8")
    assert 'class Article(IRISModel):' in model_source
    assert 'Title: str = field(required=True, maxlen=500' in model_source

    lockfile = load_lockfile(paths[0].with_name("article.iris.lock.json"))
    assert lockfile.schema.get_class("Demo.Article") is not None


def test_scaffold_from_cls_preserves_schema_snapshot(tmp_path: Path):
    cls_root = tmp_path / "cls"
    cls_root.mkdir()
    cls_path = cls_root / "Article.cls"
    cls_path.write_text(
        """
Class Demo.Article Extends %Persistent
{
Property Title As %String (MAXLEN = 500) [ Required ];
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    paths = scaffold_from_cls(cls_root, tmp_path / "generated")
    assert len(paths) == 1

    lockfile = load_lockfile(paths[0].with_name("article.iris.lock.json"))
    cls_catalog = SchemaCompiler().catalog_from_cls_path(cls_root)
    assert lockfile.schema.to_dict() == cls_catalog.to_dict()
