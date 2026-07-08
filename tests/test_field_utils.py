from typing import Any

from iris_persistence import Field, Model
from iris_persistence.field_utils import (
    coerce_bool,
    collection_kind_from_field,
    collection_kind_from_iris_type,
    collection_value_type,
    is_application_iris_class,
    is_iris_collection_type,
    is_percent_list_field,
    is_scalar_string_field,
)


class HelperChild(Model, serial=True):
    Name: str | None = None


def test_optional_model_field_is_detected_after_type_resolution():
    class HelperParent(Model):
        Child: HelperChild | None = None

    model_field = HelperParent.__model_fields__["Child"]

    assert model_field.declared_type is HelperChild
    assert model_field._is_model_field is True


def test_collection_value_type_infers_list_and_dict_elements():
    assert collection_value_type(list[str]) == ("list", str)
    assert collection_value_type(dict[str, HelperChild]) == ("array", HelperChild)
    assert collection_value_type(list[Any]) == ("list", Any)
    assert collection_value_type(str) == (None, None)


def test_field_metadata_detects_percent_list_and_scalar_string_types():
    assert is_percent_list_field(Field(iris_type="%List")) is True
    assert is_percent_list_field(Field(iris_type="%Library.List")) is True
    assert is_percent_list_field(Field(iris_type="%ListOfDataTypes")) is False

    assert is_scalar_string_field(Field(iris_type="%Library.String")) is True
    assert is_scalar_string_field(Field(iris_type="%Library.String", collection="list")) is False


def test_collection_kind_from_field_uses_metadata_and_iris_collection_types():
    assert collection_kind_from_field(Field(collection="list")) == "list"
    assert collection_kind_from_field(Field(collection="array")) == "array"
    assert collection_kind_from_field(Field(iris_type="%ListOfDataTypes")) == "list"
    assert collection_kind_from_field(Field(iris_type="%Library.ListOfObjects")) == "list"
    assert collection_kind_from_field(Field(iris_type="%ArrayOfDataTypes")) == "array"
    assert collection_kind_from_field(Field(iris_type="%Library.ArrayOfObjects")) == "array"
    assert collection_kind_from_field(Field(iris_type="%Library.String")) is None


def test_iris_type_helpers_detect_collection_and_application_classes():
    assert collection_kind_from_iris_type("%Library.ListOfDataTypes") == "list"
    assert collection_kind_from_iris_type("%Library.ArrayOfObjects") == "array"
    assert collection_kind_from_iris_type("%Library.String") is None

    assert is_iris_collection_type("%ListOfObjects") is True
    assert is_iris_collection_type("%Library.String") is False

    assert is_application_iris_class("Demo.Widget") is True
    assert is_application_iris_class("%Library.String") is False
    assert is_application_iris_class("") is False


def test_metadata_bool_coercion_matches_dictionary_values():
    assert coerce_bool(1) is True
    assert coerce_bool("1") is True
    assert coerce_bool(True) is True
    assert coerce_bool("true") is True
    assert coerce_bool(0) is False
    assert coerce_bool("") is False
    assert coerce_bool(None) is False
