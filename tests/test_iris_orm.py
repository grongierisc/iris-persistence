"""
Comprehensive unit tests for iris_orm.

All tests use a fake_iris autouse fixture so no live IRIS connection is needed.
Compatible with Python 3.11+.
"""
from __future__ import annotations

import datetime
import sys
from typing import Any, Optional
from unittest.mock import MagicMock, call, patch
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fake IRIS fixture — monkeypatches sys.modules["iris"] before any import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_iris(monkeypatch):
    """Replace the `iris` module with a MagicMock for every test."""
    mock_iris = MagicMock()
    monkeypatch.setitem(sys.modules, "iris", mock_iris)
    yield mock_iris


# ---------------------------------------------------------------------------
# Helpers imported after fixture is in place
# ---------------------------------------------------------------------------

from iris_orm.types import (  # noqa: E402
    IRIS_TO_PYTHON,
    PYTHON_TO_IRIS,
    iris_type_to_annotation,
    iris_type_to_python,
    python_type_to_iris,
    unwrap_optional,
)
from iris_orm.fields import (  # noqa: E402
    FieldDefinition,
    RelationshipDefinition,
    field,
    relationship,
)
from iris_orm.introspection import get_class_properties, PropertyInfo  # noqa: E402
from iris_orm.descriptors import (  # noqa: E402
    IRISDescriptor,
    IRISRelationshipDescriptor,
    IRISRelationshipManager,
    _wrap_iris_obj,
)
from iris_orm.query import IRISQuerySet  # noqa: E402


# ===========================================================================
# TestTypes
# ===========================================================================

class TestTypes:
    def test_known_string_type(self):
        assert iris_type_to_python("%String") is str
        assert iris_type_to_python("%Library.String") is str

    def test_known_integer_type(self):
        assert iris_type_to_python("%Integer") is int
        assert iris_type_to_python("%Library.Integer") is int

    def test_known_float_types(self):
        assert iris_type_to_python("%Float") is float
        assert iris_type_to_python("%Numeric") is float
        assert iris_type_to_python("%Double") is float

    def test_known_boolean_type(self):
        assert iris_type_to_python("%Boolean") is bool

    def test_known_date_type(self):
        assert iris_type_to_python("%Date") is datetime.date
        assert iris_type_to_python("%Library.Date") is datetime.date

    def test_known_time_type(self):
        assert iris_type_to_python("%Time") is datetime.time

    def test_known_timestamp_types(self):
        assert iris_type_to_python("%TimeStamp") is datetime.datetime
        assert iris_type_to_python("%Library.TimeStamp") is datetime.datetime
        assert iris_type_to_python("%PosixTime") is datetime.datetime

    def test_known_list_type(self):
        assert iris_type_to_python("%List") is list

    def test_known_stream_types(self):
        assert iris_type_to_python("%Stream.GlobalCharacter") is str
        assert iris_type_to_python("%Stream.GlobalBinary") is bytes

    def test_unknown_type_falls_back_to_any(self):
        from typing import Any
        assert iris_type_to_python("%SomeWeirdType") is Any

    def test_python_to_iris_str(self):
        assert python_type_to_iris(str) == "%String"

    def test_python_to_iris_int(self):
        assert python_type_to_iris(int) == "%Integer"

    def test_python_to_iris_float(self):
        assert python_type_to_iris(float) == "%Float"

    def test_python_to_iris_bool(self):
        assert python_type_to_iris(bool) == "%Boolean"

    def test_python_to_iris_date(self):
        assert python_type_to_iris(datetime.date) == "%Date"

    def test_python_to_iris_datetime(self):
        assert python_type_to_iris(datetime.datetime) == "%TimeStamp"

    def test_python_to_iris_fallback(self):
        class Foo:
            pass
        assert python_type_to_iris(Foo) == "%String"

    def test_annotation_string_str(self):
        assert iris_type_to_annotation("%String") == "Optional[str]"

    def test_annotation_string_date(self):
        assert iris_type_to_annotation("%Date") == "Optional[datetime.date]"

    def test_annotation_string_datetime(self):
        assert iris_type_to_annotation("%TimeStamp") == "Optional[datetime.datetime]"

    def test_annotation_unknown_is_any(self):
        assert iris_type_to_annotation("%Unknown") == "Any"

    def test_unwrap_optional(self):
        from typing import Optional
        assert unwrap_optional(Optional[str]) is str

    def test_unwrap_optional_datetime(self):
        from typing import Optional
        assert unwrap_optional(Optional[datetime.date]) is datetime.date

    def test_unwrap_non_optional_passthrough(self):
        assert unwrap_optional(str) is str
        assert unwrap_optional(int) is int

    def test_iris_to_python_dict_non_empty(self):
        assert len(IRIS_TO_PYTHON) > 5

    def test_python_to_iris_dict_non_empty(self):
        assert len(PYTHON_TO_IRIS) > 4


# ===========================================================================
# TestFields
# ===========================================================================

class TestFields:
    def test_field_creates_field_definition(self):
        fd = field(required=True, maxlen=100, description="A field")
        assert isinstance(fd, FieldDefinition)
        assert fd.required is True
        assert fd.maxlen == 100
        assert fd.description == "A field"

    def test_field_default_none(self):
        fd = field()
        assert fd.required is False
        assert fd.default is None
        assert fd.maxlen is None
        assert fd.collection == ""

    def test_field_with_default(self):
        fd = field(default="hello")
        assert fd.default == "hello"

    def test_field_with_iris_type(self):
        fd = field(iris_type="%Integer")
        assert fd.iris_type == "%Integer"

    def test_relationship_creates_definition(self):
        rd = relationship("Demo.Author", inverse="Posts", cardinality="parent")
        assert isinstance(rd, RelationshipDefinition)
        assert rd.related_classname == "Demo.Author"
        assert rd.inverse == "Posts"
        assert rd.cardinality == "parent"
        assert rd.on_delete == "cascade"

    def test_relationship_invalid_cardinality_raises(self):
        with pytest.raises(ValueError, match="cardinality"):
            relationship("Demo.Author", inverse="Posts", cardinality="bogus")

    def test_relationship_description(self):
        rd = relationship("A.B", inverse="x", cardinality="one", description="desc")
        assert rd.description == "desc"


# ===========================================================================
# TestIntrospection
# ===========================================================================

class TestIntrospection:
    def _make_row(self, name, type_, required, collection, default):
        return (name, type_, required, collection, default)

    def test_correct_sql_executed(self, fake_iris):
        fake_iris.sql.exec.return_value = []
        get_class_properties("Demo.Test")
        sql_call = fake_iris.sql.exec.call_args
        assert sql_call is not None
        sql_str = sql_call[0][0]
        assert "%Dictionary.PropertyDefinition" in sql_str
        assert "parent = ?" in sql_str
        assert "Relationship = 0" in sql_str

    def test_classname_passed_as_param(self, fake_iris):
        fake_iris.sql.exec.return_value = []
        get_class_properties("Demo.MyClass")
        params = fake_iris.sql.exec.call_args[0][1]
        assert params == ["Demo.MyClass"]

    def test_parses_property_list(self, fake_iris):
        rows = [
            self._make_row("Name", "%String", 1, "", ""),
            self._make_row("Age", "%Integer", 0, "", ""),
        ]
        fake_iris.sql.exec.return_value = iter(rows)
        props = get_class_properties("Demo.Test")
        assert len(props) == 2
        name_prop = props[0]
        assert name_prop.name == "Name"
        assert name_prop.iris_type == "%String"
        assert name_prop.python_type is str
        assert name_prop.required is True
        age_prop = props[1]
        assert age_prop.name == "Age"
        assert age_prop.python_type is int
        assert age_prop.required is False

    def test_unknown_type_fallback(self, fake_iris):
        from typing import Any
        rows = [self._make_row("Weird", "%SomeType", 0, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)
        props = get_class_properties("Demo.Test")
        assert props[0].python_type is Any

    def test_null_type_defaults_to_string(self, fake_iris):
        rows = [self._make_row("X", None, 0, None, None)]
        fake_iris.sql.exec.return_value = iter(rows)
        props = get_class_properties("Demo.Test")
        assert props[0].iris_type == "%String"

    def test_collection_lowercased(self, fake_iris):
        rows = [self._make_row("Tags", "%String", 0, "List", "")]
        fake_iris.sql.exec.return_value = iter(rows)
        props = get_class_properties("Demo.Test")
        assert props[0].collection == "list"


# ===========================================================================
# TestIRISDescriptor
# ===========================================================================

class TestIRISDescriptor:
    def _make_instance(self, prop_name="Name", python_type=str, required=False):
        """Return a descriptor and a minimal mock instance."""
        desc = IRISDescriptor(prop_name, python_type, required)
        desc.attr_name = prop_name
        iris_obj = MagicMock()

        class FakeModel:
            pass

        instance = object.__new__(FakeModel)
        object.__setattr__(instance, "_iris_obj", iris_obj)
        object.__setattr__(instance, "_iris_id", None)
        return desc, instance, iris_obj

    def test_get_coerces_to_python_type(self):
        desc, inst, iris_obj = self._make_instance("Age", int)
        iris_obj.Age = "42"
        assert desc.__get__(inst, type(inst)) == 42

    def test_get_none_for_empty_string(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        iris_obj.Name = ""
        assert desc.__get__(inst, type(inst)) is None

    def test_get_none_for_none(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        iris_obj.Name = None
        assert desc.__get__(inst, type(inst)) is None

    def test_set_serializes_string(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        desc.__set__(inst, "Alice")
        assert iris_obj.Name == "Alice"

    def test_set_none_serializes_to_empty_string(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        desc.__set__(inst, None)
        assert iris_obj.Name == ""

    def test_delete_sets_to_none(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        desc.__delete__(inst)
        assert iris_obj.Name == ""

    def test_set_date_serializes_isoformat(self):
        desc, inst, iris_obj = self._make_instance("BirthDate", datetime.date)
        desc.__set__(inst, datetime.date(2024, 1, 15))
        assert iris_obj.BirthDate == "2024-01-15"

    def test_set_datetime_serializes(self):
        desc, inst, iris_obj = self._make_instance("CreatedAt", datetime.datetime)
        desc.__set__(inst, datetime.datetime(2024, 1, 15, 10, 30, 0))
        assert iris_obj.CreatedAt == "2024-01-15 10:30:00"

    def test_set_time_serializes(self):
        desc, inst, iris_obj = self._make_instance("OpenTime", datetime.time)
        desc.__set__(inst, datetime.time(9, 0, 0))
        assert iris_obj.OpenTime == "09:00:00"

    def test_get_date_coerces_from_string(self):
        desc, inst, iris_obj = self._make_instance("BirthDate", datetime.date)
        iris_obj.BirthDate = "2024-06-01"
        result = desc.__get__(inst, type(inst))
        assert result == datetime.date(2024, 6, 1)

    def test_get_on_class_returns_descriptor(self):
        desc, inst, iris_obj = self._make_instance("Name", str)
        # Accessing on None (class-level access pattern)
        result = desc.__get__(None, type(inst))
        assert result is desc

    def test_set_raises_when_no_iris_obj(self):
        desc = IRISDescriptor("Name", str)
        desc.attr_name = "Name"

        class FakeModel:
            pass

        inst = object.__new__(FakeModel)
        object.__setattr__(inst, "_iris_obj", None)
        with pytest.raises(AttributeError):
            desc.__set__(inst, "Alice")

    def test_get_any_passthrough(self):
        from typing import Any
        desc, inst, iris_obj = self._make_instance("Data", Any)
        iris_obj.Data = {"key": "value"}
        result = desc.__get__(inst, type(inst))
        assert result == {"key": "value"}


# ===========================================================================
# TestIRISRelationshipDescriptor
# ===========================================================================

class TestIRISRelationshipDescriptor:
    def _make_model(self, classname):
        """Create a minimal model-like object."""
        class FakeModel:
            _iris_classname = classname

        return FakeModel

    def _make_instance_with_iris(self, iris_obj):
        class Host:
            pass

        inst = object.__new__(Host)
        object.__setattr__(inst, "_iris_obj", iris_obj)
        object.__setattr__(inst, "_iris_id", "1")
        return inst

    def test_get_parent_returns_wrapped_model(self):
        from iris_orm.metaclass import _MODEL_REGISTRY

        related_model = self._make_model("Demo.Author")
        _MODEL_REGISTRY["Demo.Author"] = related_model

        iris_obj = MagicMock()
        related_iris = MagicMock()
        related_iris._Id.return_value = "99"
        iris_obj.Author = related_iris

        desc = IRISRelationshipDescriptor("Author", "Demo.Author", "parent", "Posts")
        inst = self._make_instance_with_iris(iris_obj)

        result = desc.__get__(inst, type(inst))
        assert result is not None
        assert object.__getattribute__(result, "_iris_obj") is related_iris

    def test_get_children_returns_manager(self):
        from iris_orm.metaclass import _MODEL_REGISTRY

        related_model = self._make_model("Demo.Comment")
        _MODEL_REGISTRY["Demo.Comment"] = related_model

        iris_obj = MagicMock()
        collection_mock = MagicMock()
        iris_obj.Comments = collection_mock

        desc = IRISRelationshipDescriptor("Comments", "Demo.Comment", "children", "Post")
        inst = self._make_instance_with_iris(iris_obj)

        result = desc.__get__(inst, type(inst))
        assert isinstance(result, IRISRelationshipManager)

    def test_set_parent_sets_iris_obj(self):
        from iris_orm.metaclass import _MODEL_REGISTRY

        related_model = self._make_model("Demo.Author")
        _MODEL_REGISTRY["Demo.Author"] = related_model

        iris_obj = MagicMock()
        related_iris = MagicMock()

        class RelInst:
            pass

        rel_inst = object.__new__(RelInst)
        object.__setattr__(rel_inst, "_iris_obj", related_iris)

        desc = IRISRelationshipDescriptor("Author", "Demo.Author", "parent", "Posts")
        inst = self._make_instance_with_iris(iris_obj)

        desc.__set__(inst, rel_inst)
        assert iris_obj.Author == related_iris

    def test_set_children_raises(self):
        desc = IRISRelationshipDescriptor("Comments", "Demo.Comment", "children", "Post")
        inst = self._make_instance_with_iris(MagicMock())
        with pytest.raises(AttributeError, match="add"):
            desc.__set__(inst, MagicMock())

    def test_resolve_model_raises_when_not_registered(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Missing", None)
        desc = IRISRelationshipDescriptor("X", "Demo.Missing", "parent", "Y")
        with pytest.raises(LookupError, match="Demo.Missing"):
            desc._resolve_model()

    def test_get_on_class_returns_descriptor(self):
        desc = IRISRelationshipDescriptor("Author", "Demo.Author", "parent", "Posts")
        result = desc.__get__(None, object)
        assert result is desc


# ===========================================================================
# TestIRISRelationshipManager
# ===========================================================================

class TestIRISRelationshipManager:
    def _make_manager(self, items_count=2):
        class FakeModel:
            _iris_classname = "Demo.Item"

        iris_items = [MagicMock() for _ in range(items_count)]
        for i, item in enumerate(iris_items):
            item._Id.return_value = str(i + 1)

        collection = MagicMock()
        collection.Count.return_value = items_count
        collection.GetAt.side_effect = lambda i: iris_items[i - 1]

        return IRISRelationshipManager(collection, FakeModel), collection, iris_items

    def test_iter_wraps_objects(self):
        mgr, collection, iris_items = self._make_manager(3)
        results = list(mgr)
        assert len(results) == 3
        for i, res in enumerate(results):
            assert object.__getattribute__(res, "_iris_obj") is iris_items[i]

    def test_count(self):
        mgr, collection, _ = self._make_manager(5)
        assert mgr.count() == 5

    def test_len(self):
        mgr, collection, _ = self._make_manager(4)
        assert len(mgr) == 4

    def test_add_calls_insert(self):
        mgr, collection, _ = self._make_manager(0)
        collection.Count.return_value = 0

        class FakeModel:
            pass

        inst = object.__new__(FakeModel)
        iris_obj = MagicMock()
        object.__setattr__(inst, "_iris_obj", iris_obj)
        mgr.add(inst)
        collection.Insert.assert_called_once_with(iris_obj)

    def test_remove_calls_remove_at(self):
        mgr, collection, iris_items = self._make_manager(1)

        class FakeModel:
            pass

        inst = object.__new__(FakeModel)
        iris_obj = MagicMock()
        iris_obj._Id.return_value = "7"
        object.__setattr__(inst, "_iris_obj", iris_obj)
        mgr.remove(inst)
        collection.RemoveAt.assert_called_once_with("7")


# ===========================================================================
# TestIRISQuerySet
# ===========================================================================

class TestIRISQuerySet:
    def _make_model(self):
        class FakeModel:
            _iris_classname = "Demo.Thing"

            @classmethod
            def _open(cls, obj_id):
                inst = object.__new__(cls)
                object.__setattr__(inst, "_iris_id", obj_id)
                object.__setattr__(inst, "_iris_obj", MagicMock())
                return inst

        return FakeModel

    def test_filter_returns_new_queryset(self):
        m = self._make_model()
        qs = IRISQuerySet(m)
        qs2 = qs.filter(Name="Alice")
        assert qs is not qs2
        assert len(qs2._where) == 1
        assert qs2._where[0] == ("Name", "=", "Alice")

    def test_all_returns_clone(self):
        m = self._make_model()
        qs = IRISQuerySet(m, [("X", "=", 1)])
        qs2 = qs.all()
        assert qs is not qs2
        assert qs2._where == qs._where

    def test_count_executes_count_sql(self, fake_iris):
        m = self._make_model()
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=7)
        fake_iris.sql.exec.return_value = iter([row])
        qs = IRISQuerySet(m)
        result = qs.count()
        assert result == 7
        # No WHERE → called with sql only (no params arg)
        call_args = fake_iris.sql.exec.call_args[0]
        assert "COUNT(*)" in call_args[0]
        assert "Demo.Thing" in call_args[0]

    def test_filter_count_adds_where_clause(self, fake_iris):
        m = self._make_model()
        row = MagicMock()
        row.__getitem__ = MagicMock(return_value=3)
        fake_iris.sql.exec.return_value = iter([row])
        qs = IRISQuerySet(m).filter(Name="Bob")
        qs.count()
        sql, params = fake_iris.sql.exec.call_args[0]
        assert "WHERE" in sql
        assert "Name = ?" in sql
        assert params == ["Bob"]

    def test_iter_yields_model_instances(self, fake_iris):
        m = self._make_model()

        class FakeRow:
            def __getitem__(self, i):
                return "42"

        fake_iris.sql.exec.return_value = iter([FakeRow()])
        # Use explicit iteration rather than list() to avoid list() calling
        # __len__ (which fires a COUNT query and exhausts the iterator).
        results = [item for item in IRISQuerySet(m)]
        assert len(results) == 1
        assert object.__getattribute__(results[0], "_iris_id") == "42"

    def test_first_returns_first_result(self, fake_iris):
        m = self._make_model()

        class FakeRow:
            def __getitem__(self, i):
                return "1"

        fake_iris.sql.exec.return_value = iter([FakeRow(), FakeRow()])
        result = IRISQuerySet(m).first()
        assert result is not None
        assert object.__getattribute__(result, "_iris_id") == "1"

    def test_first_returns_none_when_empty(self, fake_iris):
        m = self._make_model()
        fake_iris.sql.exec.return_value = iter([])
        assert IRISQuerySet(m).first() is None


# ===========================================================================
# TestIRISModel — existing-class binding
# ===========================================================================

class TestIRISModelExistingBinding:
    @pytest.fixture(autouse=True)
    def setup_existing_binding_model(self, fake_iris):
        """Set up fake IRIS introspection rows and create a bound model."""
        rows = [
            ("Name", "%String", 1, "", ""),
            ("Score", "%Integer", 0, "", ""),
        ]
        fake_iris.sql.exec.return_value = iter(rows)

        # We need a fresh registry entry for each test — clear then recreate
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Widget", None)

        from iris_orm import IRISModel

        class Widget(IRISModel):
            _iris_classname = "Demo.Widget"

        self.Widget = Widget

    def test_descriptors_injected(self):
        assert isinstance(
            self.Widget.__dict__.get("Name"), IRISDescriptor
        ), "Name descriptor should be injected"

    def test_annotations_set(self):
        assert "Name" in self.Widget.__annotations__

    def test_objects_is_queryset(self):
        assert isinstance(self.Widget.objects, IRISQuerySet)

    def test_save(self, fake_iris):
        iris_obj = MagicMock()
        iris_obj._Save.return_value = 1
        iris_obj._Id.return_value = "5"
        instance = _wrap_iris_obj(self.Widget, iris_obj)
        instance.save()
        iris_obj._Save.assert_called_once()
        assert object.__getattribute__(instance, "_iris_id") == "5"

    def test_save_raises_when_no_iris_obj(self):
        from iris_orm import IRISModel
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Bare", None)

        class Bare(IRISModel):
            _iris_classname = "Demo.Bare"

        instance = Bare.__new__(Bare)
        object.__setattr__(instance, "_iris_obj", None)
        object.__setattr__(instance, "_iris_id", None)
        with pytest.raises(RuntimeError):
            instance.save()

    def test_create_wraps_new_iris_obj(self, fake_iris):
        new_iris_obj = MagicMock()
        new_iris_obj._Id.return_value = None
        fake_iris.cls.return_value._New.return_value = new_iris_obj
        instance = self.Widget.create(Name="Test")
        assert object.__getattribute__(instance, "_iris_obj") is new_iris_obj

    def test_get_returns_none_on_exception(self, fake_iris):
        fake_iris.cls.return_value._OpenId.side_effect = Exception("not found")
        result = self.Widget.get("999")
        assert result is None

    def test_delete(self, fake_iris):
        iris_obj = MagicMock()
        iris_obj._Id.return_value = "3"
        instance = _wrap_iris_obj(self.Widget, iris_obj)
        instance.delete()
        fake_iris.cls.return_value._DeleteId.assert_called_once_with("3")
        assert object.__getattribute__(instance, "_iris_id") is None

    def test_delete_raises_when_no_id(self):
        instance = self.Widget.__new__(self.Widget)
        object.__setattr__(instance, "_iris_obj", None)
        object.__setattr__(instance, "_iris_id", None)
        with pytest.raises(RuntimeError):
            instance.delete()

    def test_pk_property(self, fake_iris):
        iris_obj = MagicMock()
        iris_obj._Id.return_value = "7"
        instance = _wrap_iris_obj(self.Widget, iris_obj)
        assert instance.pk == "7"

    def test_declared_model_flag_is_false(self):
        assert self.Widget._iris_declared_model is False


# ===========================================================================
# TestIRISModel — declared models
# ===========================================================================

class TestIRISModelDeclared:
    @pytest.fixture(autouse=True)
    def setup_declared_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Article", None)
        _MODEL_REGISTRY.pop("Demo.Section", None)

        from iris_orm import IRISModel, field, relationship

        class Section(IRISModel):
            _iris_classname = "Demo.Section"
            Title: str = field(required=True, maxlen=200)

        class Article(IRISModel):
            _iris_classname = "Demo.Article"

            Title: str = field(required=True, maxlen=500, description="Article title")
            Views: int = field(default=0)
            section = relationship(
                "Demo.Section",
                inverse="Articles",
                cardinality="parent",
            )

        self.Article = Article
        self.Section = Section

    def test_declared_model_flag_is_true(self):
        assert self.Article._iris_declared_model is True

    def test_descriptors_injected_for_annotations(self):
        assert isinstance(self.Article.__dict__.get("Title"), IRISDescriptor)
        assert isinstance(self.Article.__dict__.get("Views"), IRISDescriptor)

    def test_rel_descriptor_injected(self):
        assert isinstance(self.Article.__dict__.get("section"), IRISRelationshipDescriptor)

    def test_field_defs_populated(self):
        assert "Title" in self.Article._iris_field_defs
        fd = self.Article._iris_field_defs["Title"]
        assert fd.required is True
        assert fd.maxlen == 500

    def test_rel_defs_populated(self):
        assert "section" in self.Article._iris_rel_defs
        rd = self.Article._iris_rel_defs["section"]
        assert rd.related_classname == "Demo.Section"
        assert rd.cardinality == "parent"

    def test_objects_is_queryset(self):
        assert isinstance(self.Article.objects, IRISQuerySet)

    def test_iris_properties_list_populated(self):
        names = [p.name for p in self.Article._iris_properties]
        assert "Title" in names
        assert "Views" in names

    def test_save(self, fake_iris):
        iris_obj = MagicMock()
        iris_obj._Save.return_value = 1
        iris_obj._Id.return_value = "10"
        instance = _wrap_iris_obj(self.Article, iris_obj)
        instance.save()
        assert instance.pk == "10"

    def test_create(self, fake_iris):
        new_iris_obj = MagicMock()
        new_iris_obj._Id.return_value = None
        fake_iris.cls.return_value._New.return_value = new_iris_obj
        instance = self.Article.create(Title="Hello")
        assert object.__getattribute__(instance, "_iris_obj") is new_iris_obj

    def test_delete(self, fake_iris):
        iris_obj = MagicMock()
        iris_obj._Id.return_value = "20"
        instance = _wrap_iris_obj(self.Article, iris_obj)
        instance.delete()
        fake_iris.cls.return_value._DeleteId.assert_called_once_with("20")


# ===========================================================================
# TestSchema
# ===========================================================================

class TestSchema:
    @pytest.fixture(autouse=True)
    def setup_models(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Schema.Author", None)
        _MODEL_REGISTRY.pop("Schema.Post", None)

        from iris_orm import IRISModel, field, relationship

        class SchemaAuthor(IRISModel):
            _iris_classname = "Schema.Author"
            Name: str = field(required=True, maxlen=200, description="Author name")
            Age: int = field()

        class SchemaPost(IRISModel):
            _iris_classname = "Schema.Post"
            Title: str = field(required=True, maxlen=500)
            Body: str = field(description="Post body")
            author = relationship(
                "Schema.Author",
                inverse="Posts",
                cardinality="parent",
            )

        self.Author = SchemaAuthor
        self.Post = SchemaPost

    def test_generate_cls_contains_class_line(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "Class Schema.Author" in src

    def test_generate_cls_extends_persistent(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "Extends %Persistent" in src

    def test_generate_cls_contains_property(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "Property Name" in src

    def test_generate_cls_contains_required_constraint(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "Required" in src

    def test_generate_cls_contains_maxlen_param(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "MAXLEN = 200" in src

    def test_generate_cls_contains_description_comment(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Author)
        assert "/// Author name" in src

    def test_generate_cls_contains_relationship(self):
        from iris_orm.schema import generate_cls
        src = generate_cls(self.Post)
        assert "Relationship author" in src
        assert "Cardinality = one" in src

    def test_generate_cls_raises_for_existing_binding(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.BoundWidget", None)

        rows = [("X", "%String", 0, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)

        from iris_orm import IRISModel
        from iris_orm.schema import generate_cls

        class BoundWidget(IRISModel):
            _iris_classname = "Demo.BoundWidget"

        with pytest.raises(ValueError, match="existing IRIS class"):
            generate_cls(BoundWidget)

    def test_write_cls_creates_file(self, tmp_path):
        from iris_orm.schema import write_cls
        path = write_cls(self.Author, str(tmp_path))
        assert path.exists()
        assert path.suffix == ".cls"
        content = path.read_text()
        assert "Class Schema.Author" in content

    def test_write_cls_correct_directory_structure(self, tmp_path):
        from iris_orm.schema import write_cls
        path = write_cls(self.Author, str(tmp_path))
        # Schema.Author → <tmp_path>/Schema/Author.cls
        assert path.parent.name == "Schema"
        assert path.name == "Author.cls"


# ===========================================================================
# TestStubGenerator
# ===========================================================================

class TestStubGenerator:
    @pytest.fixture(autouse=True)
    def setup_stubs_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Stub.Person", None)

        from iris_orm import IRISModel, field, relationship

        class StubPerson(IRISModel):
            _iris_classname = "Stub.Person"
            Name: str = field(required=True)
            BirthDate: datetime.date = field()

        self.Person = StubPerson

        # Make introspection return rows matching the registered model
        rows = [
            ("Name", "%String", 1, "", ""),
            ("BirthDate", "%Date", 0, "", ""),
        ]
        fake_iris.sql.exec.return_value = iter(rows)

    def test_generate_stub_contains_class(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "class Person" in stub

    def test_generate_stub_contains_property_stub(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def Name" in stub

    def test_generate_stub_contains_pk(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def pk" in stub

    def test_generate_stub_contains_save(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def save" in stub

    def test_generate_stub_contains_delete(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def delete" in stub

    def test_generate_stub_contains_get(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def get" in stub

    def test_generate_stub_contains_create(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "def create" in stub

    def test_generate_stub_auto_generated_comment(self, fake_iris):
        from iris_orm.stubs import generate_stub
        stub = generate_stub("Stub.Person")
        assert "auto-generated" in stub

    def test_write_stub_creates_pyi_not_py(self, tmp_path, fake_iris):
        from iris_orm.stubs import write_stub
        rows = [("Name", "%String", 1, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)
        path = write_stub("Stub.Person", str(tmp_path))
        assert path.suffix == ".pyi"
        assert not path.with_suffix(".py").exists()

    def test_write_stub_correct_directory_structure(self, tmp_path, fake_iris):
        from iris_orm.stubs import write_stub
        rows = [("Name", "%String", 1, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)
        path = write_stub("Stub.Person", str(tmp_path))
        # Stub.Person → <tmp_path>/Stub/Person.pyi
        assert path.parent.name == "Stub"
        assert path.name == "Person.pyi"


# ---------------------------------------------------------------------------
# Existing-class binding fallthrough & bind()
# ---------------------------------------------------------------------------

class TestExistingBindingFallthrough:
    """Tests that bound models work even when introspection returned no props
    (e.g. no IRIS connection at class-definition time).  __getattr__/__setattr__
    fall through to the underlying IRIS object."""

    def _empty_existing_binding_class(self, fake_iris):
        """Return a bound class whose metaclass found no properties."""
        fake_iris.sql.exec.return_value = iter([])  # empty → no descriptors injected
        from iris_orm import IRISModel

        class Article(IRISModel):
            _iris_classname = "Demo.Article"

        return Article

    def test_getattr_fallthrough_reads_from_iris_obj(self, fake_iris):
        Article = self._empty_existing_binding_class(fake_iris)

        iris_obj = MagicMock()
        iris_obj.Title = "Hello"
        iris_obj._Id.return_value = "1"
        instance = Article._open.__func__(Article, "1")

        # _open calls iris.cls(...)._OpenId("1")
        fake_iris.cls.return_value._OpenId.return_value = iris_obj
        instance = Article._open("1")

        assert instance.Title == "Hello"

    def test_setattr_fallthrough_writes_to_iris_obj(self, fake_iris):
        Article = self._empty_existing_binding_class(fake_iris)

        iris_obj = MagicMock()
        iris_obj.Title = ""
        iris_obj._Id.return_value = "2"
        fake_iris.cls.return_value._OpenId.return_value = iris_obj

        instance = Article._open("2")
        instance.Title = "Updated"

        assert iris_obj.Title == "Updated"

    def test_getattr_raises_for_private_names(self, fake_iris):
        Article = self._empty_existing_binding_class(fake_iris)

        iris_obj = MagicMock()
        iris_obj._Id.return_value = "3"
        fake_iris.cls.return_value._OpenId.return_value = iris_obj

        instance = Article._open("3")
        with pytest.raises(AttributeError):
            _ = instance._nonexistent_private

    def test_getattr_raises_when_no_iris_obj(self, fake_iris):
        from iris_orm import IRISModel

        # Fresh class, no iris_obj set
        fake_iris.sql.exec.return_value = iter([])

        class Article(IRISModel):
            _iris_classname = "Demo.Article2"

        instance = object.__new__(Article)
        object.__setattr__(instance, "_iris_obj", None)
        object.__setattr__(instance, "_iris_id", None)

        with pytest.raises(AttributeError, match="no underlying IRIS object"):
            _ = instance.Title

    def test_bind_injects_descriptors_after_connection(self, fake_iris):
        """bind() re-runs introspection and injects typed descriptors."""
        # First definition: no connection → empty
        fake_iris.sql.exec.return_value = iter([])
        from iris_orm import IRISModel
        from iris_orm.descriptors import IRISDescriptor

        class Article(IRISModel):
            _iris_classname = "Demo.Article3"

        assert "Title" not in Article.__dict__

        # Now simulate a live connection with properties available
        fake_iris.sql.exec.return_value = iter([("Title", "%String", 0, "", "")])
        Article.bind()

        assert "Title" in Article.__dict__
        assert isinstance(Article.__dict__["Title"], IRISDescriptor)

    def test_bind_raises_for_declared_model(self, fake_iris):
        """bind() on a declared model should raise RuntimeError."""
        fake_iris.sql.exec.return_value = iter([])
        from iris_orm import IRISModel, field

        class Article(IRISModel):
            _iris_classname = "Demo.Article4"
            Title: str = field()

        with pytest.raises(RuntimeError, match="declared in Python"):
            Article.bind()

    def test_descriptor_takes_priority_over_fallthrough(self, fake_iris):
        """When a descriptor IS injected, it is used (not the fallthrough)."""
        fake_iris.sql.exec.return_value = iter([("Title", "%String", 0, "", "")])
        from iris_orm import IRISModel
        from iris_orm.descriptors import IRISDescriptor

        class Article(IRISModel):
            _iris_classname = "Demo.Article5"

        # descriptor should have been injected by metaclass
        assert isinstance(Article.__dict__.get("Title"), IRISDescriptor)

        iris_obj = MagicMock()
        iris_obj.Title = 42  # raw IRIS value (int) — descriptor coerces to str
        iris_obj._Id.return_value = "7"
        fake_iris.cls.return_value._OpenId.return_value = iris_obj

        instance = Article._open("7")
        # Descriptor coerces int → str
        assert instance.Title == "42"
        assert isinstance(instance.Title, str)


# ===========================================================================
# TestIRISConnection
# ===========================================================================

class TestIRISConnection:
    def test_embedded_sql_exec_calls_iris_sql_exec(self, fake_iris):
        from iris_orm.connection import IRISConnection
        fake_iris.sql.exec.return_value = iter([])
        conn = IRISConnection()
        conn.sql_exec("SELECT 1", [])
        fake_iris.sql.exec.assert_called_once()

    def test_embedded_sql_exec_passes_params(self, fake_iris):
        from iris_orm.connection import IRISConnection
        fake_iris.sql.exec.return_value = iter([])
        conn = IRISConnection()
        conn.sql_exec("SELECT ?", ["hello"])
        call_args = fake_iris.sql.exec.call_args
        assert call_args[0][1] == ["hello"]

    def test_embedded_sql_exec_empty_params(self, fake_iris):
        from iris_orm.connection import IRISConnection
        fake_iris.sql.exec.return_value = iter([])
        conn = IRISConnection()
        conn.sql_exec("SELECT 1")
        call_args = fake_iris.sql.exec.call_args[0]
        # No params → iris.sql.exec called with sql only (no second arg)
        assert call_args[0] == "SELECT 1"
        assert len(call_args) == 1

    def test_embedded_iris_cls_returns_iris_cls(self, fake_iris):
        from iris_orm.connection import IRISConnection
        conn = IRISConnection()
        result = conn.iris_cls("Demo.Foo")
        fake_iris.cls.assert_called_with("Demo.Foo")
        assert result is fake_iris.cls.return_value

    def test_context_manager_embedded(self, fake_iris):
        from iris_orm.connection import IRISConnection
        fake_iris.sql.exec.return_value = iter([])
        with IRISConnection() as conn:
            conn.sql_exec("SELECT 1")
        fake_iris.sql.exec.assert_called_once()


# ===========================================================================
# TestConflictError
# ===========================================================================

class TestConflictError:
    def test_raises_with_correct_message(self):
        from iris_orm.schema import ConflictError, PropertyConflict
        conflicts = [
            PropertyConflict("Title", "%String", "%Integer", "%Float"),
            PropertyConflict("Body", "%String", "%Boolean", "%TimeStamp"),
        ]
        with pytest.raises(ConflictError) as exc_info:
            raise ConflictError(conflicts)
        assert "2 conflict(s)" in str(exc_info.value)
        assert "Title" in str(exc_info.value)
        assert "Body" in str(exc_info.value)

    def test_stores_conflicts_list(self):
        from iris_orm.schema import ConflictError, PropertyConflict
        conflicts = [PropertyConflict("X", "%String", "%Integer", "%Float")]
        err = ConflictError(conflicts)
        assert err.conflicts is conflicts

    def test_property_conflict_dataclass(self):
        from iris_orm.schema import PropertyConflict
        pc = PropertyConflict("Name", "%String", "%Integer", "%Float")
        assert pc.name == "Name"
        assert pc.snapshot_type == "%String"
        assert pc.python_type == "%Integer"
        assert pc.iris_type == "%Float"


# ===========================================================================
# TestSchemaDiff
# ===========================================================================

class TestSchemaDiff:
    def _make_diff(self, **kwargs):
        from iris_orm.schema import SchemaDiff
        defaults = dict(
            classname="Demo.Post",
            python_added=[],
            python_removed=[],
            python_changed=[],
            iris_added=[],
            iris_removed=[],
            iris_changed=[],
            conflicts=[],
        )
        defaults.update(kwargs)
        return SchemaDiff(**defaults)

    def test_in_sync_when_empty(self):
        d = self._make_diff()
        assert d.in_sync is True

    def test_not_in_sync_with_python_added(self):
        d = self._make_diff(python_added=["NewProp"])
        assert d.in_sync is False

    def test_not_in_sync_with_iris_added(self):
        d = self._make_diff(iris_added=["RemoteProp"])
        assert d.in_sync is False

    def test_not_in_sync_with_conflicts(self):
        from iris_orm.schema import PropertyConflict
        d = self._make_diff(conflicts=[PropertyConflict("X", "%String", "%Integer", "%Float")])
        assert d.in_sync is False

    def test_str_in_sync(self):
        d = self._make_diff()
        s = str(d)
        assert "up to date" in s

    def test_str_shows_python_added(self):
        d = self._make_diff(python_added=["Score"])
        s = str(d)
        assert "Score" in s
        assert "Python added" in s

    def test_str_shows_conflicts(self):
        from iris_orm.schema import PropertyConflict
        d = self._make_diff(conflicts=[PropertyConflict("Title", "%String", "%Integer", "%Float")])
        s = str(d)
        assert "Conflict" in s
        assert "Title" in s

    def test_str_shows_iris_added(self):
        d = self._make_diff(iris_added=["RemoteProp"])
        s = str(d)
        assert "RemoteProp" in s
        assert "IRIS added" in s


# ===========================================================================
# TestSchemaManager
# ===========================================================================

class TestSchemaManager:
    @pytest.fixture(autouse=True)
    def setup_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Mgr.Post", None)
        from iris_orm import IRISModel, field

        class MgrPost(IRISModel):
            _iris_classname = "Mgr.Post"
            Title: str = field(required=True)
            Body: str = field()

        self.Post = MgrPost
        # Start with empty snapshot
        self.Post._iris_schema_snapshot = {}

    def test_fetch_returns_property_map(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        result = self.Post.schema.fetch()
        assert result == {"Title": "%String", "Body": "%String"}

    def test_fetch_calls_sql_exec(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([])
        self.Post.schema.fetch()
        fake_iris.sql.exec.assert_called_once()
        sql_arg = fake_iris.sql.exec.call_args[0][0]
        assert "%Dictionary.PropertyDefinition" in sql_arg

    def test_status_python_added_when_snapshot_empty(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([])
        d = self.Post.schema.status()
        assert "Title" in d.python_added
        assert "Body" in d.python_added

    def test_status_iris_added_when_iris_has_extra(self, fake_iris):
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
            ("Score", "%Integer", 0, "", ""),
        ])
        d = self.Post.schema.status()
        assert "Score" in d.iris_added
        assert d.python_added == []

    def test_status_python_removed(self, fake_iris):
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String", "OldField": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        d = self.Post.schema.status()
        assert "OldField" in d.python_removed

    def test_status_conflict_when_both_changed_differently(self, fake_iris):
        # snapshot: Title=%Integer, python: Title=%String, iris: Title=%Float → conflict
        self.Post._iris_schema_snapshot = {"Title": "%Integer", "Body": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%Float", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        d = self.Post.schema.status()
        assert len(d.conflicts) == 1
        assert d.conflicts[0].name == "Title"
        assert d.conflicts[0].snapshot_type == "%Integer"
        assert d.conflicts[0].python_type == "%String"
        assert d.conflicts[0].iris_type == "%Float"

    def test_status_in_sync_when_all_match(self, fake_iris):
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        d = self.Post.schema.status()
        assert d.in_sync

    def test_commit_sets_snapshot(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([])
        self.Post.schema.commit()
        assert self.Post._iris_schema_snapshot == {"Title": "%String", "Body": "%String"}

    def test_commit_uses_current_python_props(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([])
        self.Post.schema.commit()
        assert "Title" in self.Post._iris_schema_snapshot
        assert "Body" in self.Post._iris_schema_snapshot

    def test_push_raises_conflict_error(self, fake_iris):
        from iris_orm.schema import ConflictError
        # snapshot: Title=%Integer; python: Title=%String; iris: Title=%Float → conflict
        self.Post._iris_schema_snapshot = {"Title": "%Integer", "Body": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%Float", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        with pytest.raises(ConflictError):
            self.Post.schema.push()

    def test_push_creates_property_def_for_new_props(self, fake_iris):
        # snapshot empty → Title and Body are python_added; IRIS is empty
        fake_iris.sql.exec.return_value = iter([])
        self.Post.schema.push()
        # Should have called iris.cls("%Dictionary.PropertyDefinition")
        calls = [str(c) for c in fake_iris.cls.call_args_list]
        assert any("%Dictionary.PropertyDefinition" in c for c in calls)

    def test_push_property_def_save_called(self, fake_iris):
        fake_iris.sql.exec.return_value = iter([])
        prop_def_instance = MagicMock()
        fake_iris.cls.return_value._New.return_value = prop_def_instance
        self.Post.schema.push()
        assert prop_def_instance._Save.called

    def test_push_warns_on_python_removed(self, fake_iris):
        # snapshot has OldField but python doesn't
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String", "OldField": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        with pytest.warns(UserWarning, match="OldField"):
            self.Post.schema.push()

    def test_pull_raises_conflict_error(self, fake_iris):
        from iris_orm.schema import ConflictError
        self.Post._iris_schema_snapshot = {"Title": "%Integer", "Body": "%String"}
        fake_iris.sql.exec.return_value = iter([
            ("Title", "%Float", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ])
        with pytest.raises(ConflictError):
            self.Post.schema.pull()

    def test_pull_updates_snapshot_with_iris_added(self, fake_iris):
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        rows = [
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
            ("Score", "%Integer", 0, "", ""),
        ]
        fake_iris.sql.exec.side_effect = [iter(rows), iter(rows)]
        self.Post.schema.pull()
        assert "Score" in self.Post._iris_schema_snapshot

    def test_pull_injects_descriptor_for_iris_added(self, fake_iris):
        from iris_orm.descriptors import IRISDescriptor
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        rows = [
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
            ("Score", "%Integer", 0, "", ""),
        ]
        fake_iris.sql.exec.side_effect = [iter(rows), iter(rows)]
        self.Post.schema.pull()
        assert isinstance(self.Post.__dict__.get("Score"), IRISDescriptor)

    def test_pull_returns_diff(self, fake_iris):
        from iris_orm.schema import SchemaDiff
        self.Post._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        rows = [
            ("Title", "%String", 1, "", ""),
            ("Body", "%String", 0, "", ""),
        ]
        fake_iris.sql.exec.return_value = iter(rows)
        result = self.Post.schema.pull()
        assert isinstance(result, SchemaDiff)


# ===========================================================================
# TestIRISModelClassAPI
# ===========================================================================

class TestIRISModelClassAPI:
    def test_schema_property_accessible_on_class(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Eng.Model4", None)
        from iris_orm import IRISModel, field
        from iris_orm.schema import SchemaManager

        class EngModel4(IRISModel):
            _iris_classname = "Eng.Model4"
            Name: str = field()

        mgr = EngModel4.schema
        assert isinstance(mgr, SchemaManager)
        assert mgr._cls is EngModel4

    def test_schema_snapshot_is_independent_per_class(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Eng.A", None)
        _MODEL_REGISTRY.pop("Eng.B", None)
        from iris_orm import IRISModel, field

        class EngA(IRISModel):
            _iris_classname = "Eng.A"
            X: str = field()

        class EngB(IRISModel):
            _iris_classname = "Eng.B"
            Y: str = field()

        EngA._iris_schema_snapshot = {"X": "%String"}
        assert EngB._iris_schema_snapshot == {}

    def test_version_updated(self):
        import iris_orm
        assert iris_orm.__version__ == "0.4.0"

    def test_iris_connection_exported(self):
        from iris_orm import IRISConnection
        assert IRISConnection is not None


# ===========================================================================
# TestIRISSerial
# ===========================================================================

class TestIRISSerial:
    """Tests for IRISSerial base class and IRISSerialDescriptor."""

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _make_instance_with_iris(self, iris_obj):
        class Host:
            pass

        inst = object.__new__(Host)
        object.__setattr__(inst, "_iris_obj", iris_obj)
        object.__setattr__(inst, "_iris_id", None)
        return inst

    # -----------------------------------------------------------------------
    # Declared serial basics
    # -----------------------------------------------------------------------

    def test_declared_serial_descriptors_injected(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Ser.Addr1", None)
        from iris_orm import IRISSerial

        class Addr1(IRISSerial):
            _iris_classname = "Demo.Ser.Addr1"
            City: str
            State: str

        assert isinstance(Addr1.__dict__.get("City"), IRISDescriptor)
        assert isinstance(Addr1.__dict__.get("State"), IRISDescriptor)

    def test_declared_serial_flag_is_true(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Ser.Addr2", None)
        from iris_orm import IRISSerial

        class Addr2(IRISSerial):
            _iris_classname = "Demo.Ser.Addr2"
            City: str

        assert Addr2._iris_declared_model is True

    def test_declared_serial_registered_in_model_registry(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Ser.Addr3", None)
        from iris_orm import IRISSerial

        class Addr3(IRISSerial):
            _iris_classname = "Demo.Ser.Addr3"
            City: str

        assert _MODEL_REGISTRY["Demo.Ser.Addr3"] is Addr3

    def test_serial_has_no_objects_attribute(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Ser.Addr4", None)
        from iris_orm import IRISSerial

        class Addr4(IRISSerial):
            _iris_classname = "Demo.Ser.Addr4"
            City: str

        assert not hasattr(Addr4, "objects")

    def test_serial_has_no_save_method(self):
        from iris_orm import IRISSerial
        assert not hasattr(IRISSerial, "save")

    def test_serial_has_no_delete_method(self):
        from iris_orm import IRISSerial
        assert not hasattr(IRISSerial, "delete")

    def test_serial_has_no_get_method(self):
        from iris_orm import IRISSerial
        assert not hasattr(IRISSerial, "get")

    def test_serial_iris_id_is_none_on_init(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Ser.Addr5", None)
        from iris_orm import IRISSerial

        class Addr5(IRISSerial):
            _iris_classname = "Demo.Ser.Addr5"
            City: str

        addr = Addr5()
        assert object.__getattribute__(addr, "_iris_id") is None

    # -----------------------------------------------------------------------
    # IRISSerialDescriptor unit tests
    # -----------------------------------------------------------------------

    def test_serial_descriptor_get_returns_none_for_none(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.TSer.D1", None)
        from iris_orm import IRISSerial

        class TSer_D1(IRISSerial):
            _iris_classname = "Demo.TSer.D1"
            X: str

        desc = IRISSerialDescriptor("Addr", "Demo.TSer.D1")
        mock_iris_obj = MagicMock()
        mock_iris_obj.Addr = None
        inst = self._make_instance_with_iris(mock_iris_obj)
        assert desc.__get__(inst, type(inst)) is None

    def test_serial_descriptor_get_returns_none_for_empty_string(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.TSer.D2", None)
        from iris_orm import IRISSerial

        class TSer_D2(IRISSerial):
            _iris_classname = "Demo.TSer.D2"
            X: str

        desc = IRISSerialDescriptor("Addr", "Demo.TSer.D2")
        mock_iris_obj = MagicMock()
        mock_iris_obj.Addr = ""
        inst = self._make_instance_with_iris(mock_iris_obj)
        assert desc.__get__(inst, type(inst)) is None

    def test_serial_descriptor_get_wraps_iris_obj(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.TSer.D3", None)
        from iris_orm import IRISSerial

        class TSer_D3(IRISSerial):
            _iris_classname = "Demo.TSer.D3"
            X: str

        raw_serial = MagicMock()
        raw_serial._Id.side_effect = Exception("no id")

        desc = IRISSerialDescriptor("Addr", "Demo.TSer.D3")
        mock_iris_obj = MagicMock()
        mock_iris_obj.Addr = raw_serial
        inst = self._make_instance_with_iris(mock_iris_obj)

        result = desc.__get__(inst, type(inst))
        assert result is not None
        assert object.__getattribute__(result, "_iris_obj") is raw_serial

    def test_serial_descriptor_set_unwraps_iris_obj(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.TSer.D4", None)
        from iris_orm import IRISSerial

        class TSer_D4(IRISSerial):
            _iris_classname = "Demo.TSer.D4"
            X: str

        raw_serial = MagicMock()
        desc = IRISSerialDescriptor("Addr", "Demo.TSer.D4")
        mock_iris_obj = MagicMock()
        host = self._make_instance_with_iris(mock_iris_obj)

        # Create a value to set (a wrapped serial instance)
        serial_inst = object.__new__(TSer_D4)
        object.__setattr__(serial_inst, "_iris_obj", raw_serial)
        object.__setattr__(serial_inst, "_iris_id", None)

        desc.__set__(host, serial_inst)
        assert mock_iris_obj.Addr == raw_serial

    def test_serial_descriptor_set_none_stores_empty_string(self):
        from iris_orm.descriptors import IRISSerialDescriptor

        desc = IRISSerialDescriptor("Addr", "Demo.SomeSerial")
        mock_iris_obj = MagicMock()
        host = self._make_instance_with_iris(mock_iris_obj)
        desc.__set__(host, None)
        assert mock_iris_obj.Addr == ""

    def test_serial_descriptor_resolve_raises_lookup_error_when_not_registered(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.NoSuch.Serial", None)

        desc = IRISSerialDescriptor("Prop", "Demo.NoSuch.Serial")
        with pytest.raises(LookupError, match="Demo.NoSuch.Serial"):
            desc._resolve_model()

    def test_serial_descriptor_on_class_returns_descriptor(self):
        from iris_orm.descriptors import IRISSerialDescriptor
        desc = IRISSerialDescriptor("Addr", "Demo.Address")
        result = desc.__get__(None, object)
        assert result is desc

    # -----------------------------------------------------------------------
    # Parent model with serial property (declared model)
    # -----------------------------------------------------------------------

    def test_parent_model_serial_property_injects_serial_descriptor(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.SerAddr.A", None)
        _MODEL_REGISTRY.pop("Demo.SerCust.A", None)
        from iris_orm import IRISSerial, IRISModel
        from iris_orm.descriptors import IRISSerialDescriptor

        class SerAddrA(IRISSerial):
            _iris_classname = "Demo.SerAddr.A"
            City: str

        class SerCustA(IRISModel):
            _iris_classname = "Demo.SerCust.A"
            Name: str
            Address: SerAddrA  # type: ignore[assignment]

        assert isinstance(SerCustA.__dict__.get("Address"), IRISSerialDescriptor)

    def test_parent_model_serial_property_get_wraps_serial(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.SerAddr.B", None)
        _MODEL_REGISTRY.pop("Demo.SerCust.B", None)
        from iris_orm import IRISSerial, IRISModel
        from iris_orm.descriptors import _wrap_iris_obj

        class SerAddrB(IRISSerial):
            _iris_classname = "Demo.SerAddr.B"
            City: str

        class SerCustB(IRISModel):
            _iris_classname = "Demo.SerCust.B"
            Name: str
            Address: SerAddrB  # type: ignore[assignment]

        raw_serial = MagicMock()
        raw_serial._Id.side_effect = Exception("no id")
        mock_iris_obj = MagicMock()
        mock_iris_obj.Address = raw_serial

        cust = _wrap_iris_obj(SerCustB, mock_iris_obj)
        result = cust.Address
        assert result is not None
        assert object.__getattribute__(result, "_iris_obj") is raw_serial
        assert isinstance(result, SerAddrB)

    def test_parent_model_serial_property_set_unwraps_serial(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.SerAddr.C", None)
        _MODEL_REGISTRY.pop("Demo.SerCust.C", None)
        from iris_orm import IRISSerial, IRISModel
        from iris_orm.descriptors import _wrap_iris_obj

        class SerAddrC(IRISSerial):
            _iris_classname = "Demo.SerAddr.C"
            City: str

        class SerCustC(IRISModel):
            _iris_classname = "Demo.SerCust.C"
            Name: str
            Address: SerAddrC  # type: ignore[assignment]

        raw_serial = MagicMock()
        mock_iris_obj = MagicMock()
        cust = _wrap_iris_obj(SerCustC, mock_iris_obj)

        addr = object.__new__(SerAddrC)
        object.__setattr__(addr, "_iris_obj", raw_serial)
        object.__setattr__(addr, "_iris_id", None)

        cust.Address = addr
        assert mock_iris_obj.Address == raw_serial

    # -----------------------------------------------------------------------
    # Schema generation
    # -----------------------------------------------------------------------

    def test_generate_cls_serial_extends_serial_object(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.Ser1", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import generate_cls

        class SchSer1(IRISSerial):
            _iris_classname = "Demo.Sch.Ser1"
            City: str

        source = generate_cls(SchSer1)
        assert "Extends %SerialObject" in source

    def test_generate_cls_serial_not_persistent(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.Ser2", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import generate_cls

        class SchSer2(IRISSerial):
            _iris_classname = "Demo.Sch.Ser2"
            City: str

        source = generate_cls(SchSer2)
        assert "Extends %Persistent" not in source

    def test_generate_cls_serial_has_no_storage_block(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.Ser3", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import generate_cls

        class SchSer3(IRISSerial):
            _iris_classname = "Demo.Sch.Ser3"
            City: str
            _iris_storage = "Storage Default { <Data name='DefaultData'><Structure>listbuiltin</Structure></Data> }"

        source = generate_cls(SchSer3)
        assert "Storage" not in source

    def test_generate_cls_serial_has_properties(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.Ser4", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import generate_cls

        class SchSer4(IRISSerial):
            _iris_classname = "Demo.Sch.Ser4"
            City: str
            ZipCode: str

        source = generate_cls(SchSer4)
        assert "Property City As %String;" in source
        assert "Property ZipCode As %String;" in source

    def test_generate_cls_parent_with_serial_property_uses_classname_as_type(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.SerAddr5", None)
        _MODEL_REGISTRY.pop("Demo.Sch.SerCust5", None)
        from iris_orm import IRISSerial, IRISModel
        from iris_orm.schema import generate_cls

        class SerAddr5(IRISSerial):
            _iris_classname = "Demo.Sch.SerAddr5"
            City: str

        class SerCust5(IRISModel):
            _iris_classname = "Demo.Sch.SerCust5"
            Name: str
            Address: SerAddr5  # type: ignore[assignment]

        source = generate_cls(SerCust5)
        assert "Property Address As Demo.Sch.SerAddr5;" in source

    def test_schema_manager_push_raises_for_serial(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.PushSer", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import SchemaManager

        class PushSer(IRISSerial):
            _iris_classname = "Demo.Sch.PushSer"
            City: str

        mgr = SchemaManager(PushSer)
        with pytest.raises(RuntimeError, match="SerialObject"):
            mgr.push()

    def test_schema_manager_pull_raises_for_serial(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.PullSer", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import SchemaManager

        class PullSer(IRISSerial):
            _iris_classname = "Demo.Sch.PullSer"
            City: str

        mgr = SchemaManager(PullSer)
        with pytest.raises(RuntimeError, match="SerialObject"):
            mgr.pull()

    def test_schema_manager_status_raises_for_serial(self):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Demo.Sch.StatusSer", None)
        from iris_orm import IRISSerial
        from iris_orm.schema import SchemaManager

        class StatusSer(IRISSerial):
            _iris_classname = "Demo.Sch.StatusSer"
            City: str

        mgr = SchemaManager(StatusSer)
        with pytest.raises(RuntimeError, match="SerialObject"):
            mgr.status()


# ===========================================================================
# TestEnsureIrisClass
# ===========================================================================

class TestEnsureIrisClass:
    @pytest.fixture(autouse=True)
    def setup_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Dict.Widget", None)
        from iris_orm import IRISModel, field

        class DictWidget(IRISModel):
            _iris_classname = "Dict.Widget"
            Name: str = field(required=True, maxlen=200)
            Score: int = field(default=0)

        self.Widget = DictWidget
        self.fake_iris = fake_iris

    def _make_conn(self, class_exists=False):
        """Return a fake IRISConnection whose sql_exec indicates class existence."""
        from iris_orm.connection import IRISConnection
        conn = MagicMock(spec=IRISConnection)
        # sql_exec for _class_exists_in_iris: returns row if class exists
        conn.sql_exec.return_value = iter([("Dict.Widget",)] if class_exists else [])
        return conn

    def test_ensure_iris_class_creates_class_when_missing(self, fake_iris):
        from iris_orm.schema import _ensure_iris_class_impl

        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            conn.sql_exec.return_value = iter([])  # class does not exist

            _ensure_iris_class_impl(self.Widget)

            # Should have created %Dictionary.ClassDefinition
            conn.iris_cls.assert_any_call("%Dictionary.ClassDefinition")

    def test_ensure_iris_class_raises_for_existing_binding(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Dict.Bound", None)
        from iris_orm import IRISModel
        from iris_orm.schema import _ensure_iris_class_impl

        rows = [("X", "%String", 0, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)

        class ExistingBindingOnly(IRISModel):
            _iris_classname = "Dict.Bound"

        with pytest.raises(ValueError, match="existing IRIS class"):
            _ensure_iris_class_impl(ExistingBindingOnly)

    def test_ensure_iris_class_skips_creation_when_exists(self, fake_iris):
        from iris_orm.schema import _ensure_iris_class_impl

        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            # Class exists → sql_exec returns a row
            conn.sql_exec.return_value = iter([("Dict.Widget",)])

            _ensure_iris_class_impl(self.Widget)

            # _New should NOT be called on ClassDefinition
            for call_args in conn.iris_cls.call_args_list:
                if call_args[0][0] == "%Dictionary.ClassDefinition":
                    conn.iris_cls.return_value._New.assert_not_called()
                    break

    def test_ensure_iris_class_upserts_all_properties(self, fake_iris):
        from iris_orm.schema import _ensure_iris_class_impl

        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            conn.sql_exec.return_value = iter([("Dict.Widget",)])  # class exists

            _ensure_iris_class_impl(self.Widget)

            # %Dictionary.PropertyDefinition should have been accessed for each prop
            prop_def_calls = [
                c for c in conn.iris_cls.call_args_list
                if c[0][0] == "%Dictionary.PropertyDefinition"
            ]
            assert len(prop_def_calls) == len(self.Widget._iris_properties)

    def test_ensure_iris_class_compiles_after_changes(self, fake_iris):
        from iris_orm.schema import _ensure_iris_class_impl

        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            conn.sql_exec.return_value = iter([("Dict.Widget",)])

            _ensure_iris_class_impl(self.Widget)

            conn.iris_cls.assert_any_call("%SYSTEM.OBJ")

    def test_ensure_iris_class_via_schema_manager(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Widget)
        with patch("iris_orm.schema._ensure_iris_class_impl") as mock_ensure:
            mgr.ensure_iris_class()
            mock_ensure.assert_called_once_with(self.Widget)

    def test_compile_to_iris_deprecated_alias(self, fake_iris):
        import warnings
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Widget)
        with patch("iris_orm.schema._ensure_iris_class_impl"), \
             warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            mgr.compile_to_iris()
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_module_level_compile_to_iris_deprecated(self, fake_iris):
        import warnings
        from iris_orm.schema import compile_to_iris

        with patch("iris_orm.schema._ensure_iris_class_impl"), \
             warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compile_to_iris(self.Widget)
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_module_level_generate_cls_deprecated(self):
        import warnings
        from iris_orm.schema import generate_cls

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            generate_cls(self.Widget)
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_module_level_write_cls_deprecated(self, tmp_path):
        import warnings
        from iris_orm.schema import write_cls

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            write_cls(self.Widget, str(tmp_path))
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)


# ===========================================================================
# TestDeleteProperty
# ===========================================================================

class TestDeleteProperty:
    @pytest.fixture(autouse=True)
    def setup_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Del.Article", None)
        from iris_orm import IRISModel, field

        class DelArticle(IRISModel):
            _iris_classname = "Del.Article"
            Title: str = field(required=True)
            Body: str = field()

        self.Article = DelArticle

    def test_delete_property_calls_delete_id(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            mgr.delete_property("Body")
            conn.iris_cls.assert_any_call("%Dictionary.PropertyDefinition")
            conn.iris_cls.return_value._DeleteId.assert_called_once_with("Del.Article||Body")

    def test_delete_property_recompiles_class(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            mgr.delete_property("Body")
            conn.iris_cls.assert_any_call("%SYSTEM.OBJ")
            conn.iris_cls.return_value.Compile.assert_called_once_with("Del.Article", "ck")

    def test_delete_property_removes_from_iris_properties(self, fake_iris):
        from iris_orm.schema import SchemaManager

        assert any(p.name == "Body" for p in self.Article._iris_properties)
        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection"):
            mgr.delete_property("Body")
        assert not any(p.name == "Body" for p in self.Article._iris_properties)

    def test_delete_property_removes_from_field_defs(self, fake_iris):
        from iris_orm.schema import SchemaManager

        assert "Body" in self.Article._iris_field_defs
        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection"):
            mgr.delete_property("Body")
        assert "Body" not in self.Article._iris_field_defs

    def test_delete_property_removes_from_snapshot(self, fake_iris):
        from iris_orm.schema import SchemaManager

        self.Article._iris_schema_snapshot = {"Title": "%String", "Body": "%String"}
        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection"):
            mgr.delete_property("Body")
        assert "Body" not in self.Article._iris_schema_snapshot

    def test_delete_property_raises_on_iris_failure(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Article)
        with patch("iris_orm.connection.IRISConnection") as MockConn:
            conn = MockConn.return_value
            conn.iris_cls.return_value._DeleteId.side_effect = Exception("not found")
            with pytest.raises(RuntimeError, match="Failed to delete"):
                mgr.delete_property("Body")


# ===========================================================================
# TestPushEnhancements
# ===========================================================================

class TestPushEnhancements:
    @pytest.fixture(autouse=True)
    def setup_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Push.Product", None)
        from iris_orm import IRISModel, field

        class PushProduct(IRISModel):
            _iris_classname = "Push.Product"
            Name: str = field(required=True)
            Price: float = field()

        PushProduct._iris_schema_snapshot = {"Name": "%String"}
        self.Product = PushProduct

    def test_push_calls_upsert_for_added_properties(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Product)
        with patch("iris_orm.connection.IRISConnection") as MockConn, \
             patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
             patch("iris_orm.schema._upsert_property_via_dict") as mock_upsert:

            mock_fetch = MagicMock(return_value={"Name": "%String"})
            mgr.fetch = mock_fetch

            mgr.push()
            # Price was added (in python but not in snapshot)
            assert mock_upsert.called

    def test_push_creates_class_if_missing(self, fake_iris):
        from iris_orm.schema import SchemaManager

        mgr = SchemaManager(self.Product)
        with patch("iris_orm.connection.IRISConnection"), \
             patch("iris_orm.schema._class_exists_in_iris", return_value=False), \
             patch("iris_orm.schema._ensure_iris_class_impl") as mock_ensure:

            mock_fetch = MagicMock(return_value={"Name": "%String"})
            mgr.fetch = mock_fetch

            mgr.push()
            mock_ensure.assert_called_once_with(self.Product)

    def test_push_warns_on_removed_properties(self, fake_iris):
        from iris_orm.schema import SchemaManager
        import warnings

        # snapshot has Price but python model doesn't have it anymore
        self.Product._iris_schema_snapshot = {"Name": "%String", "OldProp": "%String"}
        # OldProp not in _iris_properties → python_removed = ["OldProp"]
        mgr = SchemaManager(self.Product)
        with patch("iris_orm.connection.IRISConnection"), \
             patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
             patch("iris_orm.schema._upsert_property_via_dict"):

            mock_fetch = MagicMock(return_value={"Name": "%String", "OldProp": "%String"})
            mgr.fetch = mock_fetch

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                mgr.push()
                removal_warnings = [x for x in w if "delete_property" in str(x.message)]
                assert len(removal_warnings) == 1

    def test_push_upserts_changed_properties(self, fake_iris):
        from iris_orm.schema import SchemaManager

        # snapshot has Name as %Integer, python has %String → changed
        self.Product._iris_schema_snapshot = {"Name": "%Integer", "Price": "%Double"}
        mgr = SchemaManager(self.Product)

        with patch("iris_orm.connection.IRISConnection"), \
             patch("iris_orm.schema._class_exists_in_iris", return_value=True), \
             patch("iris_orm.schema._upsert_property_via_dict") as mock_upsert:

            mock_fetch = MagicMock(return_value={"Name": "%Integer", "Price": "%Double"})
            mgr.fetch = mock_fetch

            mgr.push()
            upserted_names = {call[0][1].name for call in mock_upsert.call_args_list}
            assert "Name" in upserted_names
