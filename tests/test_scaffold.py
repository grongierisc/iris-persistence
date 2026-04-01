from __future__ import annotations

import importlib.util
from pathlib import Path

from iris_orm.scaffold import scaffold_from_cls, scaffold_from_iris
from iris_orm.schema import SchemaCompiler, schema_equals

from .fake_runtime import FakeAdapter, preload_schema


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scaffold_from_iris_proxy_keeps_storage_metadata(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclasses": ["%Persistent", "Demo.Auditable"],
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "maxlen": 500},
            },
            "indexes": {"TitleIdx": {"properties": "Title", "unique": True}},
            "parameters": {"DEFAULTGLOBAL": "^Demo.ArticleD"},
            "storage": {
                "name": "Default",
                "type": "%Storage.Persistent",
                "data_location": "^Demo.ArticleD",
                "default_data": "ArticleDefaultData",
                "extent_size": "1",
                "properties": [
                    {
                        "name": "Title",
                        "average_field_size": "16",
                        "selectivity": "0.0001%",
                    }
                ],
                "sql_maps": [
                    {
                        "name": "IDKEY",
                        "block_count": "-4",
                    }
                ],
            },
        },
    )

    paths = scaffold_from_iris("Demo.*", tmp_path, conn=adapter)
    source = paths[0].read_text(encoding="utf-8")
    assert '_iris_mode = "proxy"' in source
    assert "_iris_storage =" in source
    assert "@parameter" not in source
    assert "@index" not in source
    assert '_iris_superclasses = [\'%Persistent\', \'Demo.Auditable\']' in source
    assert "'extent_size': '1'" in source
    assert "'properties': [{'average_field_size': '16'" in source
    assert "'sql_maps': [{'block_count': '-4', 'name': 'IDKEY'}]" in source

    module = _load_module(paths[0], "article_proxy")
    assert module.Article._iris_storage["data_location"] == "^Demo.ArticleD"
    assert module.Article._iris_storage["extent_size"] == "1"
    assert module.Article._iris_storage["properties"][0]["name"] == "Title"
    assert module.Article._iris_storage["sql_maps"][0]["name"] == "IDKEY"


def test_scaffold_from_iris_python_renders_decorators_and_storage(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    preload_schema(
        adapter,
        {
            "name": "Demo.Article",
            "superclasses": ["%Persistent", "Demo.Auditable"],
            "properties": {
                "Title": {"iris_type": "%String", "required": True, "maxlen": 500},
            },
            "indexes": {"TitleIdx": {"properties": "Title", "unique": True}},
            "parameters": {"DEFAULTGLOBAL": "^Demo.ArticleD"},
            "storage": {
                "name": "Default",
                "type": "%Storage.Persistent",
                "data_location": "^Demo.ArticleD",
                "extent_size": "1",
                "properties": [{"name": "Title", "average_field_size": "16"}],
                "sql_maps": [{"name": "IDKEY", "block_count": "-4"}],
            },
        },
    )

    paths = scaffold_from_iris("Demo.*", tmp_path, style="python", conn=adapter)
    source = paths[0].read_text(encoding="utf-8")
    assert "@parameter('DEFAULTGLOBAL', '^Demo.ArticleD')" in source
    assert '@index("TitleIdx", properties="Title", unique=True)' in source
    assert '_iris_superclasses = [\'%Persistent\', \'Demo.Auditable\']' in source
    assert "_iris_storage =" in source

    module = _load_module(paths[0], "article_python")
    generated = SchemaCompiler().compile_model(module.Article)
    live = SchemaCompiler(adapter).class_from_iris("Demo.Article")
    assert schema_equals(generated, live)


def test_scaffold_from_cls_parses_storage_and_python_mode(tmp_path: Path) -> None:
    cls_root = tmp_path / "cls"
    cls_root.mkdir()
    (cls_root / "Product.cls").write_text(
        """
Class Demo.Product Extends %Persistent
{
Parameter DEFAULTGLOBAL = "^Demo.ProductD";

Property Name As %String(MAXLEN = 200) [ Required ];

Index NameIdx On (Name) [ Unique ];

Storage Default
{
<DataLocation>^Demo.ProductD</DataLocation>
<DefaultData>ProductDefaultData</DefaultData>
<ExtentSize>2</ExtentSize>
<Property name="Name">
<AverageFieldSize>8</AverageFieldSize>
</Property>
<SQLMap name="IDKEY">
<BlockCount>-4</BlockCount>
</SQLMap>
<Type>%Storage.Persistent</Type>
}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    paths = scaffold_from_cls(cls_root, tmp_path / "generated", style="python")
    source = paths[0].read_text(encoding="utf-8")
    assert "@parameter('DEFAULTGLOBAL', '^Demo.ProductD')" in source
    assert '@index("NameIdx", properties="Name", unique=True)' in source
    assert "_iris_storage =" in source
    assert "'extent_size': '2'" in source
    assert "'properties': [{'average_field_size': '8', 'name': 'Name'}]" in source
    assert "'sql_maps': [{'block_count': '-4', 'name': 'IDKEY'}]" in source
