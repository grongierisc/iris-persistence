from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING, Any

from iris_persistence.field_utils import (
    PYTHON_SCALAR_TYPES,
    collection_kind_from_field,
    is_percent_list_field,
)

_DYNAMIC_CLASSES = frozenset({"%Library.DynamicObject", "%Library.DynamicArray"})
_STREAM_CLASSES = frozenset(
    {
        "%Stream.GlobalBinary",
        "%Stream.GlobalCharacter",
        "%Stream.FileBinary",
        "%Stream.FileCharacter",
    }
)

if TYPE_CHECKING:
    from iris_persistence._runtime_backend import WrapperBackend


class IRISValueCodec:
    """Backend-neutral persistence value conversion used by :class:`IRISRuntime`."""

    def __init__(self, backend: WrapperBackend, operations: Any):
        self._backend = backend
        self._operations = operations

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        return self._operations.call_classmethod(class_name, method_name, *args)

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        self._operations.set_property(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return self._operations.get_property(obj, prop_name)

    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any:
        return self._operations.invoke_method(obj, method_name, *args)

    def _populate_collection_property(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> bool:
        collection_kind = collection_kind_from_field(field_meta)
        if collection_kind is None:
            return False

        current_prop = self.get_property(obj, field_name)
        if current_prop is None:
            return False

        try:
            clear = getattr(current_prop, "Clear", None)
            if callable(clear):
                clear()
            if collection_kind == "list" and isinstance(val, list):
                return self._populate_list(current_prop, val)
            if collection_kind == "array" and isinstance(val, dict):
                return self._populate_array(current_prop, val)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return False
        return False

    @staticmethod
    def _populate_list(target: Any, values: list[Any]) -> bool:
        if not callable(getattr(target, "Insert", None)):
            return False
        for item in values:
            getattr(target, "Insert")(item)
        return True

    @staticmethod
    def _populate_array(target: Any, values: dict[Any, Any]) -> bool:
        if not callable(getattr(target, "SetAt", None)):
            return False
        for key, item in values.items():
            getattr(target, "SetAt")(item, str(key))
        return True

    def clear_reference(self, obj: Any, field_name: str, *, serial: bool = False) -> None:
        """Clear an object reference across embedded and native IRIS APIs."""
        if not serial and self._clear_reference_with_method(obj, field_name):
            return
        cleared, native_attempted = self._backend.try_native_set(obj, field_name, "")
        if cleared:
            return
        if native_attempted:
            self._raise_clear_reference_error(field_name)
        self._clear_reference_property(obj, field_name)

    def _clear_reference_with_method(self, obj: Any, field_name: str) -> bool:
        attempts = (
            (f"{field_name}SetObjectId", ""),
            (f"{field_name}SetObjectId", None),
            (f"{field_name}SetObject", None),
        )
        for method_name, value in attempts:
            try:
                self.invoke_method(obj, method_name, value)
                return True
            except (AttributeError, RuntimeError, TypeError):
                if self._backend.try_native_invoke(obj, method_name, value):
                    return True
        return False

    def _clear_reference_property(self, obj: Any, field_name: str) -> None:
        try:
            self.set_property(obj, field_name, "")
        except (AttributeError, RuntimeError, TypeError) as exc:
            from iris_persistence._runtime_backend import RuntimeOperationError

            raise RuntimeOperationError(
                "clear_reference", str(exc), backend=self._backend.backend_name()
            ) from exc

    def _raise_clear_reference_error(self, field_name: str) -> None:
        from iris_persistence._runtime_backend import RuntimeOperationError

        raise RuntimeOperationError(
            "clear_reference",
            f"unable to clear {field_name!r}",
            backend=self._backend.backend_name(),
        )

    def _clear_property_value(self, obj: Any, field_name: str) -> bool:
        native, stream_ref = self._backend.try_native_get(obj, field_name)
        if native:
            return stream_ref is not None and self._backend.try_native_invoke_target(
                obj, stream_ref, "Clear"
            )

        current_prop = self.get_property(obj, field_name)
        if not hasattr(current_prop, "Clear"):
            return False
        current_prop.Clear()
        return True

    def _set_null_property_value(self, obj: Any, field_name: str) -> bool:
        cleared, _attempted = self._backend.try_native_set(obj, field_name, "")
        return cleared

    def _write_stream_property(self, obj: Any, field_name: str, val: bytes | bytearray) -> bool:
        native, stream_ref = self._backend.try_native_get(obj, field_name)
        if native:
            if stream_ref is None or not self._backend.try_native_invoke_target(
                obj, stream_ref, "Clear"
            ):
                return False
            return self._backend.try_native_invoke_target(obj, stream_ref, "Write", val)

        current_prop = self.get_property(obj, field_name)
        if not hasattr(current_prop, "Write"):
            return False
        current_prop.Clear()
        current_prop.Write(val)
        return True

    def _set_dynamic_json_value(
        self,
        obj: Any,
        field_name: str,
        iris_class_name: str,
        val: Any,
    ) -> bool:
        native, dyn_value = self._backend.dynamic_json_value(
            obj, iris_class_name, json.dumps(val)
        )
        if native:
            written, _attempted = self._backend.try_native_set(obj, field_name, dyn_value)
            if not written:
                return False
            return True

        dyn_value = self.call_classmethod(iris_class_name, "_FromJSON", json.dumps(val))
        self.set_property(obj, field_name, dyn_value)
        return True

    def _inject_collection_value(
        self,
        obj: Any,
        field_name: str,
        val: dict[Any, Any] | list[Any],
        *,
        kind: str,
        field_meta: Any | None = None,
    ) -> None:
        if kind == "list" and is_percent_list_field(field_meta):
            assert isinstance(val, list)
            self.set_property(obj, field_name, self._encode_percent_list(val))
            return
        if collection_kind_from_field(
            field_meta
        ) is not None and self._populate_collection_property(
            obj, field_name, val, field_meta=field_meta
        ):
            return
        dynamic_class = "%Library.DynamicArray" if kind == "list" else "%Library.DynamicObject"
        try:
            dynamic_written = self._set_dynamic_json_value(obj, field_name, dynamic_class, val)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            dynamic_written = False
        if dynamic_written:
            return
        self.set_property(obj, field_name, val)

    def _encode_percent_list(self, values: list[Any]) -> Any:
        row = io.StringIO()
        csv.writer(row, lineterminator="").writerow(values)
        return self.call_classmethod("%Library.List", "OdbcToLogical", row.getvalue())

    def _extract_collection_value(self, val: Any, expected_kind: str | None = None) -> Any:
        if expected_kind != "list" and self._supports_methods(val, "Count", "Next", "GetAt"):
            array = self._extract_array_value(val)
            if array is not None or expected_kind == "array":
                return array
        if expected_kind in (None, "list") and self._supports_methods(val, "Count", "GetAt"):
            return self._extract_list_value(val)
        return None

    @staticmethod
    def _supports_methods(value: Any, *names: str) -> bool:
        return all(callable(getattr(value, name, None)) for name in names)

    def _extract_array_value(self, value: Any) -> dict[str, Any] | None:
        try:
            key = value.Next("")
            items: dict[str, Any] = {}
            while key not in ("", None):
                items[str(key)] = self.extract_python_value(value.GetAt(key))
                key = value.Next(key)
            return items
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None

    def _extract_list_value(self, value: Any) -> list[Any] | None:
        try:
            total = value.Count()
            if not isinstance(total, int):
                return None
            return [self.extract_python_value(value.GetAt(index)) for index in range(1, total + 1)]
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None

    @staticmethod
    def _iris_class_name(value: Any) -> str | None:
        if not hasattr(value, "_ClassName"):
            return type(value).__name__
        try:
            return value._ClassName(1)
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None

    def _extract_dynamic_json(self, value: Any) -> Any:
        try:
            stream = self.call_classmethod("%Stream.GlobalCharacter", "_New")
            value._ToJSON(stream)
            stream.Rewind()
            return json.loads(stream.Read())
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return value

    @staticmethod
    def _extract_stream(value: Any, iris_class: str) -> Any:
        try:
            value.Rewind()
            size_value = getattr(value, "Size", 0)
            size = size_value() if callable(size_value) else size_value
            content = value.Read(size) if size and size > 0 else b""
            if isinstance(content, str) and "Binary" in iris_class:
                return content.encode("latin1")
            return content
        except (AttributeError, RuntimeError, TypeError, ValueError, UnicodeError):
            return value

    def extract_python_value(self, val: Any, expected_collection_kind: str | None = None) -> Any:
        if type(val) in PYTHON_SCALAR_TYPES:
            return val
        extracted_collection = self._extract_collection_value(val, expected_collection_kind)
        if extracted_collection is not None:
            return extracted_collection
        iris_class = self._iris_class_name(val)
        if iris_class in _DYNAMIC_CLASSES:
            return self._extract_dynamic_json(val)
        if iris_class in _STREAM_CLASSES:
            assert iris_class is not None
            return self._extract_stream(val, iris_class)
        return val

    def extract_typed_python_value(self, val: Any, collection_kind: str | None) -> Any:
        return self.extract_python_value(val, collection_kind)

    def decode_percent_list(self, value: Any) -> list[Any]:
        if value in (None, ""):
            return []

        return self._backend.decode_percent_list(value)

    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None:
        if val is None or (isinstance(val, str) and val == ""):
            if self._clear_property_value(obj, field_name):
                return
            if self._set_null_property_value(obj, field_name):
                return
            self.set_property(obj, field_name, val)
        elif isinstance(val, (bytes, bytearray)):
            if self._write_stream_property(obj, field_name, val):
                return
            self.set_property(obj, field_name, val)
        elif isinstance(val, dict):
            self._inject_collection_value(obj, field_name, val, kind="array", field_meta=field_meta)
        elif isinstance(val, list):
            self._inject_collection_value(obj, field_name, val, kind="list", field_meta=field_meta)
        else:
            self.set_property(obj, field_name, val)
