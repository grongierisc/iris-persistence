"""
Unit tests for iris_orm.

All tests use ``unittest.mock`` to stub out the ``iris`` module so that
no live IRIS connection is required.
"""
from __future__ import annotations

import datetime
import sys
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Build a minimal fake ``iris`` module so imports work without IRIS installed.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_iris(monkeypatch):
    """Inject a fake ``iris`` module for every test."""
    mock = MagicMock(name="iris")
    mock.sql = MagicMock()
    monkeypatch.setitem(sys.modules, "iris", mock)
    yield mock


# ---------------------------------------------------------------------------
# iris_orm.types
# ---------------------------------------------------------------------------

class TestTypes:
    def test_known_mappings(self):
        from iris_orm.types import iris_type_to_python

        assert iris_type_to_python("%String") is str
        assert iris_type_to_python("%Integer") is int
        assert iris_type_to_python("%Float") is float
        assert iris_type_to_python("%Boolean") is bool
        assert iris_type_to_python("%Date") is datetime.date
        assert iris_type_to_python("%TimeStamp") is datetime.datetime
        assert iris_type_to_python("%Time") is datetime.time
        assert iris_type_to_python("%List") is list

    def test_fallback_to_any(self):
        from typing import Any
        from iris_orm.types import iris_type_to_python

        assert iris_type_to_python("%CustomClass") is Any

    def test_annotation_builtin(self):
        from iris_orm.types import iris_type_to_annotation

        assert iris_type_to_annotation("%String") == "Optional[str]"
        assert iris_type_to_annotation("%Integer") == "Optional[int]"

    def test_annotation_datetime(self):
        from iris_orm.types import iris_type_to_annotation

        assert iris_type_to_annotation("%Date") == "Optional[datetime.date]"
        assert iris_type_to_annotation("%TimeStamp") == "Optional[datetime.datetime]"

    def test_annotation_unknown(self):
        from iris_orm.types import iris_type_to_annotation

        assert iris_type_to_annotation("%Unknown") == "Any"


# ---------------------------------------------------------------------------
# iris_orm.descriptors
# ---------------------------------------------------------------------------

class TestIRISDescriptor:
    def _make_model(self, iris_obj):
        from iris_orm.descriptors import IRISDescriptor

        class FakeModel:
            Name = IRISDescriptor("Name", str)

            def __init__(self, iris_obj):
                object.__setattr__(self, "_iris_obj", iris_obj)

        return FakeModel(iris_obj)

    def test_get_coerces_to_str(self):
        iris_obj = MagicMock()
        iris_obj.Name = 42
        assert self._make_model(iris_obj).Name == "42"

    def test_get_returns_none_for_empty_string(self):
        iris_obj = MagicMock()
        iris_obj.Name = ""
        assert self._make_model(iris_obj).Name is None

    def test_get_returns_none_for_none(self):
        iris_obj = MagicMock()
        iris_obj.Name = None
        assert self._make_model(iris_obj).Name is None

    def test_set_propagates_to_iris_obj(self):
        iris_obj = MagicMock()
        iris_obj.Name = ""
        m = self._make_model(iris_obj)
        m.Name = "Alice"
        assert iris_obj.Name == "Alice"

    def test_set_none_stores_empty_string(self):
        iris_obj = MagicMock()
        iris_obj.Name = "Alice"
        m = self._make_model(iris_obj)
        m.Name = None
        assert iris_obj.Name == ""

    def test_descriptor_on_class_returns_itself(self):
        from iris_orm.descriptors import IRISDescriptor

        class FakeModel:
            Name = IRISDescriptor("Name", str)

        assert isinstance(FakeModel.Name, IRISDescriptor)

    def test_serialize_date(self):
        from iris_orm.descriptors import IRISDescriptor

        d = IRISDescriptor("Foo", datetime.date)
        assert d._serialize(datetime.date(2024, 1, 15)) == "2024-01-15"

    def test_serialize_datetime(self):
        from iris_orm.descriptors import IRISDescriptor

        d = IRISDescriptor("Foo", datetime.datetime)
        assert d._serialize(datetime.datetime(2024, 1, 15, 10, 30, 0)) == "2024-01-15 10:30:00"

    def test_delete_sets_none(self):
        iris_obj = MagicMock()
        iris_obj.Name = "Bob"
        m = self._make_model(iris_obj)
        del m.Name
        assert iris_obj.Name == ""


# ---------------------------------------------------------------------------
# iris_orm.introspection
# ---------------------------------------------------------------------------

class TestIntrospection:
    def test_returns_property_list(self, fake_iris):
        fake_iris.sql.exec.return_value = [
            ("Title", "%String", 1, "", ""),
            ("Count", "%Integer", 0, "", "42"),
        ]
        from iris_orm.introspection import get_class_properties

        props = get_class_properties("Demo.Test")
        assert len(props) == 2
        assert props[0].name == "Title"
        assert props[0].python_type is str
        assert props[0].required is True
        assert props[1].name == "Count"
        assert props[1].python_type is int
        assert props[1].default == "42"

    def test_uses_correct_sql(self, fake_iris):
        fake_iris.sql.exec.return_value = []
        from iris_orm.introspection import get_class_properties

        get_class_properties("Demo.Foo")

        args = fake_iris.sql.exec.call_args[0]
        assert "%Dictionary.PropertyDefinition" in args[0]
        assert args[1] == ["Demo.Foo"]

    def test_fallback_type_for_unknown(self, fake_iris):
        from typing import Any
        fake_iris.sql.exec.return_value = [("Custom", "%Custom.Type", 0, "", "")]
        from iris_orm.introspection import get_class_properties

        props = get_class_properties("Demo.Test")
        assert props[0].python_type is Any


# ---------------------------------------------------------------------------
# iris_orm.query — IRISQuerySet
# ---------------------------------------------------------------------------

class TestIRISQuerySet:
    def _fake_model(self):
        class FakeModel:
            _iris_classname = "Demo.Post"

            @classmethod
            def _open(cls, obj_id):
                m = MagicMock()
                m.pk = obj_id
                return m

        return FakeModel

    def test_filter_returns_new_queryset(self, fake_iris):
        from iris_orm.query import IRISQuerySet

        qs = IRISQuerySet(self._fake_model())
        filtered = qs.filter(Author="alice")
        assert filtered is not qs
        assert filtered._where == [("Author", "=", "alice")]

    def test_all_returns_clone(self, fake_iris):
        from iris_orm.query import IRISQuerySet

        qs = IRISQuerySet(self._fake_model())
        assert qs.all() is not qs

    def test_count_uses_count_star(self, fake_iris):
        fake_iris.sql.exec.return_value = [(3,)]
        from iris_orm.query import IRISQuerySet

        assert IRISQuerySet(self._fake_model()).count() == 3
        sql = fake_iris.sql.exec.call_args[0][0]
        assert "COUNT(*)" in sql

    def test_filter_builds_where_clause(self, fake_iris):
        fake_iris.sql.exec.return_value = [(1,)]
        from iris_orm.query import IRISQuerySet

        IRISQuerySet(self._fake_model()).filter(Author="alice").count()
        args = fake_iris.sql.exec.call_args[0]
        assert "WHERE" in args[0]
        assert args[1] == ["alice"]

    def test_iter_opens_each_id(self, fake_iris):
        fake_iris.sql.exec.return_value = [("1",), ("2",)]
        from iris_orm.query import IRISQuerySet

        opened: list[str] = []

        class FakeModel:
            _iris_classname = "Demo.Post"

            @classmethod
            def _open(cls, obj_id):
                opened.append(obj_id)
                return MagicMock()

        list(IRISQuerySet(FakeModel))
        assert opened == ["1", "2"]

    def test_first_returns_none_when_empty(self, fake_iris):
        fake_iris.sql.exec.return_value = []
        from iris_orm.query import IRISQuerySet

        class FakeModel:
            _iris_classname = "Demo.Post"

            @classmethod
            def _open(cls, obj_id):
                return None

        assert IRISQuerySet(FakeModel).first() is None


# ---------------------------------------------------------------------------
# iris_orm.metaclass — IRISModel
# ---------------------------------------------------------------------------

class TestIRISModel:
    def _post_class(self, fake_iris):
        fake_iris.sql.exec.return_value = [
            ("Title", "%String", 0, "", ""),
            ("ViewCount", "%Integer", 0, "", ""),
        ]
        from iris_orm import IRISModel

        class Post(IRISModel):
            _iris_classname = "Demo.Post"

        return Post

    def test_descriptors_injected(self, fake_iris):
        from iris_orm.descriptors import IRISDescriptor

        Post = self._post_class(fake_iris)
        assert isinstance(Post.__dict__["Title"], IRISDescriptor)
        assert isinstance(Post.__dict__["ViewCount"], IRISDescriptor)

    def test_annotations_populated(self, fake_iris):
        Post = self._post_class(fake_iris)
        assert "Title" in Post.__annotations__
        assert "ViewCount" in Post.__annotations__

    def test_objects_is_queryset(self, fake_iris):
        from iris_orm.query import IRISQuerySet

        Post = self._post_class(fake_iris)
        assert isinstance(Post.objects, IRISQuerySet)

    def test_save_calls_iris_save(self, fake_iris):
        from iris_orm.metaclass import IRISModel

        Post = self._post_class(fake_iris)
        iris_obj = MagicMock()
        iris_obj._Save.return_value = True
        iris_obj._Id.return_value = "99"

        post = Post.__new__(Post)
        IRISModel.__init__(post)
        object.__setattr__(post, "_iris_obj", iris_obj)
        post.save()

        iris_obj._Save.assert_called_once()
        assert post.pk == "99"

    def test_save_raises_without_iris_obj(self, fake_iris):
        from iris_orm.metaclass import IRISModel

        Post = self._post_class(fake_iris)
        post = Post.__new__(Post)
        IRISModel.__init__(post)

        with pytest.raises(RuntimeError, match="no underlying IRIS object"):
            post.save()

    def test_create_sets_kwargs(self, fake_iris):
        Post = self._post_class(fake_iris)

        iris_obj = MagicMock()
        iris_obj.Title = ""
        fake_iris.cls.return_value._New.return_value = iris_obj

        Post.create(Title="Hello")
        assert iris_obj.Title == "Hello"

    def test_get_returns_none_for_missing(self, fake_iris):
        Post = self._post_class(fake_iris)
        fake_iris.cls.return_value._OpenId.return_value = None

        assert Post.get("999") is None

    def test_delete_calls_delete_id(self, fake_iris):
        from iris_orm.metaclass import IRISModel

        Post = self._post_class(fake_iris)
        post = Post.__new__(Post)
        IRISModel.__init__(post)
        object.__setattr__(post, "_iris_id", "5")
        object.__setattr__(post, "_iris_obj", MagicMock())

        post.delete()
        fake_iris.cls.return_value._DeleteId.assert_called_once_with("5")
        assert post.pk is None

    def test_delete_raises_without_id(self, fake_iris):
        from iris_orm.metaclass import IRISModel

        Post = self._post_class(fake_iris)
        post = Post.__new__(Post)
        IRISModel.__init__(post)

        with pytest.raises(RuntimeError, match="no ID"):
            post.delete()


# ---------------------------------------------------------------------------
# iris_orm.stubs
# ---------------------------------------------------------------------------

class TestStubGenerator:
    def test_generate_stub_contains_class(self, fake_iris):
        fake_iris.sql.exec.return_value = [("Title", "%String", 0, "", "")]
        from iris_orm.stubs import generate_stub

        stub = generate_stub("Demo.Test")
        assert "class Test(IRISModel):" in stub
        assert "def Title(self)" in stub
        assert "Optional[str]" in stub

    def test_generate_stub_includes_crud(self, fake_iris):
        fake_iris.sql.exec.return_value = []
        from iris_orm.stubs import generate_stub

        stub = generate_stub("Demo.Test")
        assert "def save(self) -> None" in stub
        assert "def delete(self) -> None" in stub
        assert "def get(cls" in stub
        assert "def create(cls" in stub

    def test_write_stub_creates_pyi_file(self, fake_iris, tmp_path):
        fake_iris.sql.exec.return_value = [("Title", "%String", 0, "", "")]
        from iris_orm.stubs import write_stub

        out_path = write_stub("Demo.Test", str(tmp_path))
        assert out_path.exists()
        assert out_path.suffix == ".pyi"
        assert out_path.name == "Test.pyi"
        assert out_path.parent.name == "Demo"

    def test_write_stub_no_py_files(self, fake_iris, tmp_path):
        fake_iris.sql.exec.return_value = []
        from iris_orm.stubs import write_stub

        write_stub("Demo.Test", str(tmp_path))
        assert list(tmp_path.rglob("*.py")) == []
