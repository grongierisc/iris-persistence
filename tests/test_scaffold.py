from __future__ import annotations

import importlib.util
from pathlib import Path

from iris_orm.scaffold import scaffold_from_cls, scaffold_from_iris
from iris_orm.schema import SchemaCompiler

from .fake_runtime import FakeAdapter, preload_schema


def _without_source(payload):
    payload = dict(payload)
    payload.pop("source", None)
    return payload


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scaffold_from_iris_defaults_to_typed_proxy(tmp_path: Path):
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclass": "Demo.BaseArticle",
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 500, "description": ""},
            },
            "relationships": {
                "Owner": {
                    "related_classname": "Demo.User",
                    "cardinality": "parent",
                    "inverse": "Articles",
                    "description": "",
                },
            },
            "indexes": {
                "TitleIdx": {"properties": "Title", "unique": True, "primary_key": False},
            },
            "triggers": {
                "AuditInsert": {"event": "INSERT", "time": "AFTER", "code": "set x=1"},
            },
            "parameters": {"DEFAULTGLOBAL": "^Demo.ArticleD"},
            "storage": {
                "name": "Default",
                "type": "%Storage.Persistent",
                "data_location": "^Demo.ArticleD",
                "default_data": "ArticleDefaultData",
                "data": [
                    {
                        "name": "ArticleDefaultData",
                        "structure": "listnode",
                        "values": [{"name": "1", "value": "Title"}],
                    }
                ],
            },
        },
    )

    paths = scaffold_from_iris("Demo.*", tmp_path / "generated", conn=adapter)
    assert len(paths) == 1
    assert not paths[0].with_name("article.iris.lock.json").exists()
    model_source = paths[0].read_text(encoding="utf-8")
    assert 'class Article(IRISModel):' in model_source
    assert '_iris_superclass = "Demo.BaseArticle"' in model_source
    assert '_iris_mode = "proxy"' in model_source
    assert "_iris_class_parameters" not in model_source
    assert "_iris_indexes" not in model_source
    assert "_iris_storage" not in model_source
    assert 'Title: str = field(required=True, maxlen=500' in model_source
    assert 'Owner = relationship("Demo.User", inverse="Articles", cardinality="parent")' in model_source

    module = _load_module(paths[0], "generated_article_proxy")
    assert module.Article._iris_mode == "proxy"


def test_scaffold_from_iris_supports_python_mode(tmp_path: Path):
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclass": "Demo.BaseArticle",
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "collection": "", "default": "", "maxlen": 500, "description": ""},
            },
            "relationships": {
                "Owner": {
                    "related_classname": "Demo.User",
                    "cardinality": "parent",
                    "inverse": "Articles",
                    "description": "",
                },
            },
            "indexes": {
                "TitleIdx": {"properties": "Title", "unique": True, "primary_key": False},
            },
            "triggers": {
                "AuditInsert": {"event": "INSERT", "time": "AFTER", "code": "set x=1"},
            },
            "parameters": {"DEFAULTGLOBAL": "^Demo.ArticleD"},
            "storage": {
                "name": "Default",
                "type": "%Storage.Persistent",
                "data_location": "^Demo.ArticleD",
                "default_data": "ArticleDefaultData",
                "data": [
                    {
                        "name": "ArticleDefaultData",
                        "structure": "listnode",
                        "values": [{"name": "1", "value": "Title"}],
                    }
                ],
            },
        },
    )

    paths = scaffold_from_iris("Demo.*", tmp_path / "generated", style="python", conn=adapter)
    model_source = paths[0].read_text(encoding="utf-8")
    assert '_iris_mode = "python"' in model_source
    assert "@parameter('DEFAULTGLOBAL', '^Demo.ArticleD')" in model_source
    assert '@index("TitleIdx", properties="Title", unique=True)' in model_source
    assert '@trigger("AuditInsert", event="INSERT", time="AFTER", code=\'set x=1\')' in model_source
    assert "_iris_class_parameters" not in model_source
    assert "_iris_indexes" not in model_source
    assert "_iris_triggers" not in model_source
    assert "_iris_storage" in model_source

    module = _load_module(paths[0], "generated_article_python")
    generated = SchemaCompiler().compile_model(module.Article)
    live = SchemaCompiler(adapter).class_from_iris("Demo.Article")
    assert _without_source(generated.to_dict()) == _without_source(live.to_dict())


def test_scaffold_from_cls_defaults_to_proxy(tmp_path: Path):
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
    assert not paths[0].with_name("article.iris.lock.json").exists()
    source = paths[0].read_text(encoding="utf-8")
    assert '_iris_mode = "proxy"' in source

    module = _load_module(paths[0], "generated_article_cls_proxy")
    assert module.Article._iris_mode == "proxy"


def test_scaffold_from_cls_supports_python_mode(tmp_path: Path):
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

    paths = scaffold_from_cls(cls_root, tmp_path / "generated", style="python")
    module = _load_module(paths[0], "generated_article_cls_python")
    cls_catalog = SchemaCompiler().catalog_from_cls_path(cls_root)
    generated = SchemaCompiler().compile_model(module.Article)
    assert _without_source(generated.to_dict()) == _without_source(cls_catalog.get_class("Demo.Article").to_dict())


def test_scaffold_renders_typed_python_defaults_from_iris_expressions(tmp_path: Path):
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "superclass": "%Persistent",
            "properties": {
                "Foo": {"iris_type": "%String", "required": False, "collection": "", "default": '"bar"', "maxlen": None, "description": ""},
                "InStock": {"iris_type": "%Boolean", "required": False, "collection": "", "default": "1", "maxlen": None, "description": ""},
                "Price": {"iris_type": "%Float", "required": False, "collection": "", "default": "0.0", "maxlen": None, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    paths = scaffold_from_iris("Demo.Product", tmp_path / "generated", conn=adapter)
    source = paths[0].read_text(encoding="utf-8")
    assert 'Foo: str = field(default=\'bar\'' in source
    assert "InStock: bool = field(default=True" in source
    assert "Price: float = field(default=0.0" in source


def test_scaffold_omits_default_for_iris_empty_string_sentinel(tmp_path: Path):
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Product",
            "superclass": "%Persistent",
            "properties": {
                "Name": {"iris_type": "%String", "required": True, "collection": "", "default": '""', "maxlen": 200, "description": ""},
            },
            "relationships": {},
            "indexes": {},
            "parameters": {},
            "storage": None,
        },
    )

    paths = scaffold_from_iris("Demo.Product", tmp_path / "generated", conn=adapter)
    source = paths[0].read_text(encoding="utf-8")
    assert 'Name: str = field(required=True, maxlen=200, iris_type="%String")' in source
    assert "default=" not in source
