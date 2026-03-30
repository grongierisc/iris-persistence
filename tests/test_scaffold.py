"""
Targeted tests for scaffold + sidecar behavior.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def fake_iris(monkeypatch):
    from unittest.mock import MagicMock

    mock_iris = MagicMock()
    monkeypatch.setitem(sys.modules, "iris", mock_iris)
    yield mock_iris


class TestScaffoldFromIris:
    def test_scaffold_from_iris_writes_python_and_lockfile(self, tmp_path):
        from iris_orm.introspection import ClassDetails, IndexInfo, PropertyInfo, RelationshipInfo
        from iris_orm.scaffold import scaffold_from_iris

        details = [
            ClassDetails(
                classname="Demo.Address",
                super="%SerialObject",
                properties=[
                    PropertyInfo("City", "%String", str, False, "", "", None, ""),
                ],
                relationships=[],
                class_parameters={"DEFAULTGLOBAL": "^Demo.AddressD"},
                indexes=[],
                storage_definition="Storage Default { }",
                unsupported_features=[],
            ),
            ClassDetails(
                classname="Demo.Article",
                super="%Persistent",
                properties=[
                    PropertyInfo("Title", "%String", str, True, "", "", 200, ""),
                    PropertyInfo("Address", "Demo.Address", object, False, "", "", None, ""),
                ],
                relationships=[
                    RelationshipInfo("Author", "Demo.Author", "parent", "Articles", ""),
                ],
                class_parameters={"DEFAULTGLOBAL": "^Demo.ArticleD"},
                indexes=[IndexInfo("TitleIdx", "Title", unique=True, primary_key=False)],
                storage_definition="Storage Default { <Data name='Article'/> }",
                unsupported_features=[],
            ),
        ]

        with patch("iris_orm.scaffold.list_classes", return_value=["Demo.Address", "Demo.Article"]), \
             patch("iris_orm.scaffold.get_class_details", side_effect=details):
            paths = scaffold_from_iris(
                "Demo.*",
                tmp_path / "models",
                state_root=tmp_path / ".iris_orm" / "state",
            )

        assert len(paths) == 2
        article_path = tmp_path / "models" / "demo" / "article.py"
        lock_path = tmp_path / ".iris_orm" / "state" / "Demo.Article.json"
        assert article_path.exists()
        assert lock_path.exists()
        content = article_path.read_text()
        assert 'class Article(IRISModel):' in content
        assert '_iris_storage_mode = "preserve"' in content
        assert 'Title: str = field(required=True, maxlen=200)' in content
        assert 'Address: Address = field(iris_type="Demo.Address")' in content
        assert 'from .address import Address' in content
        assert 'Author = relationship("Demo.Author", inverse="Articles", cardinality="parent")' in content
        lock_content = lock_path.read_text()
        assert '"storage_definition": "Storage Default { <Data name' in lock_content
        assert '"indexes"' in lock_content

    def test_render_plan_a_style_is_minimal(self):
        from iris_orm.introspection import ClassDetails
        from iris_orm.scaffold import render_model

        rendered = render_model(
            ClassDetails(
                classname="Demo.Widget",
                super="%Persistent",
                properties=[],
                relationships=[],
                class_parameters={},
                indexes=[],
                storage_definition="",
                unsupported_features=[],
            ),
            style="plan-a",
        )
        assert "field(" not in rendered
        assert "relationship(" not in rendered
        assert "_iris_classname = \"Demo.Widget\"" in rendered


class TestScaffoldFromCls:
    def test_scaffold_from_cls_parses_source_and_refresh_preserves_manual_content(self, tmp_path):
        from iris_orm.scaffold import scaffold_from_cls

        cls_root = tmp_path / "cls"
        cls_root.mkdir()
        (cls_root / "Sample.cls").write_text(
            """
Class Demo.Sample Extends %Persistent
{
Property Title As %String (MAXLEN = 120) [ Required ];
Relationship Author As Demo.Author [ Cardinality = parent, Inverse = Samples ];
Parameter DEFAULTGLOBAL = "^Demo.SampleD";
Index TitleIdx On (Title) [ Unique = 1 ];
Storage Default
{
<Data name="DefaultData"/>
}
}
""".strip()
            + "\n",
            encoding="utf-8",
        )

        output_root = tmp_path / "models"
        state_root = tmp_path / ".iris_orm" / "state"
        scaffold_from_cls(cls_root, output_root, state_root=state_root)
        generated_path = output_root / "demo" / "sample.py"
        generated_path.write_text(
            generated_path.read_text(encoding="utf-8") + "\n\ndef helper() -> str:\n    return 'ok'\n",
            encoding="utf-8",
        )

        scaffold_from_cls(cls_root, output_root, state_root=state_root, refresh=True)
        content = generated_path.read_text(encoding="utf-8")
        assert "def helper() -> str:" in content
        assert 'Title: str = field(required=True, maxlen=120)' in content
        assert 'relationship("Demo.Author", inverse="Samples", cardinality="parent")' in content

    def test_refresh_rejects_generated_block_edits(self, tmp_path):
        from iris_orm.errors import LockfileDriftError
        from iris_orm.scaffold import scaffold_from_cls

        cls_root = tmp_path / "cls"
        cls_root.mkdir()
        (cls_root / "Sample.cls").write_text(
            "Class Demo.Sample Extends %Persistent\n{\nProperty Title As %String;\n}\n",
            encoding="utf-8",
        )
        output_root = tmp_path / "models"
        state_root = tmp_path / ".iris_orm" / "state"
        scaffold_from_cls(cls_root, output_root, state_root=state_root)

        generated_path = output_root / "demo" / "sample.py"
        content = generated_path.read_text(encoding="utf-8").replace(
            'Title: str = field()',
            'Title: int = field()',
        )
        generated_path.write_text(content, encoding="utf-8")

        with pytest.raises(LockfileDriftError, match="modified"):
            scaffold_from_cls(cls_root, output_root, state_root=state_root, refresh=True)


class TestSchemaSidecarDrift:
    def test_relative_lockfile_path_resolves_from_model_module(self, tmp_path, monkeypatch):
        from iris_orm.errors import StorageConflictError
        from iris_orm.introspection import ClassDetails
        from iris_orm.lockfile import IRISLockfile, compute_hash, write_lockfile
        from iris_orm.scaffold import scaffold_from_cls

        cls_root = tmp_path / "cls"
        cls_root.mkdir()
        (cls_root / "Product.cls").write_text(
            "Class Demo.Product Extends %Persistent\n{\nProperty Name As %String;\nStorage Default\n{\n<Data name=\"DefaultData\"/>\n}\n}\n",
            encoding="utf-8",
        )

        output_root = tmp_path / "models"
        state_root = tmp_path / ".iris_orm" / "state"
        scaffold_from_cls(cls_root, output_root, state_root=state_root)

        sys.path.insert(0, str(output_root.parent))
        try:
            spec = importlib.util.spec_from_file_location(
                "models.demo.product",
                output_root / "demo" / "product.py",
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            sys.modules["models.demo.product"] = module
            spec.loader.exec_module(module)
            Product = module.Product

            old_cwd = Path.cwd()
            os.chdir(tmp_path / "cls")
            try:
                with patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
                     patch("iris_orm.schema.get_class_details", return_value=ClassDetails(
                         classname="Demo.Product",
                         super="%Persistent",
                         properties=[],
                         relationships=[],
                         class_parameters={},
                         indexes=[],
                         storage_definition="Storage Default { changed }",
                         unsupported_features=[],
                     )), \
                     patch("iris_orm.schema.SchemaManager.fetch", return_value={}):
                    with pytest.raises(StorageConflictError):
                        Product.schema.push()
            finally:
                os.chdir(old_cwd)
        finally:
            sys.path.remove(str(output_root.parent))
            sys.modules.pop("models.demo.product", None)

    def test_status_reports_storage_conflict(self, tmp_path):
        from iris_orm import IRISModel, field
        from iris_orm.introspection import ClassDetails
        from iris_orm.lockfile import IRISLockfile, compute_hash, write_lockfile

        class Product(IRISModel):
            _iris_classname = "Demo.Product"
            _iris_lockfile_path = str(tmp_path / "Demo.Product.json")
            _iris_storage_mode = "preserve"
            Name: str = field()

        write_lockfile(
            Product._iris_lockfile_path,
            IRISLockfile(
                classname="Demo.Product",
                super="%Persistent",
                storage_mode="preserve",
                storage_definition="Storage Default { one }",
                storage_hash=compute_hash("Storage Default { one }"),
                class_parameters={},
                indexes=[],
                source={"kind": "iris", "origin": "Demo.*"},
                scaffold_style="plan-c",
                generated_at="2026-01-01T00:00:00Z",
            ),
        )

        with patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
             patch("iris_orm.schema.get_class_details", return_value=ClassDetails(
                 classname="Demo.Product",
                 super="%Persistent",
                 properties=[],
                 relationships=[],
                 class_parameters={},
                 indexes=[],
                 storage_definition="Storage Default { two }",
                 unsupported_features=[],
             )), \
             patch("iris_orm.schema.SchemaManager.fetch", return_value={}):
            diff = Product.schema.status()

        assert diff.storage_conflicts

    def test_push_raises_on_storage_conflict(self, tmp_path):
        from iris_orm import IRISModel, field
        from iris_orm.errors import StorageConflictError
        from iris_orm.introspection import ClassDetails
        from iris_orm.lockfile import IRISLockfile, compute_hash, write_lockfile

        class Product(IRISModel):
            _iris_classname = "Demo.ProductPush"
            _iris_lockfile_path = str(tmp_path / "Demo.ProductPush.json")
            _iris_storage_mode = "preserve"
            Name: str = field()

        write_lockfile(
            Product._iris_lockfile_path,
            IRISLockfile(
                classname="Demo.ProductPush",
                super="%Persistent",
                storage_mode="preserve",
                storage_definition="Storage Default { one }",
                storage_hash=compute_hash("Storage Default { one }"),
                class_parameters={},
                indexes=[],
                source={"kind": "iris", "origin": "Demo.*"},
                scaffold_style="plan-c",
                generated_at="2026-01-01T00:00:00Z",
            ),
        )

        with patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
             patch("iris_orm.schema.get_class_details", return_value=ClassDetails(
                 classname="Demo.ProductPush",
                 super="%Persistent",
                 properties=[],
                 relationships=[],
                 class_parameters={},
                 indexes=[],
                 storage_definition="Storage Default { two }",
                 unsupported_features=[],
             )), \
             patch("iris_orm.schema.SchemaManager.fetch", return_value={}):
            with pytest.raises(StorageConflictError):
                Product.schema.push()
