from __future__ import annotations

import csv
import io
import json
from typing import Any

from iris_persistence.field_utils import (
    collection_kind_from_field,
    is_percent_list_field,
)

_SCALAR_PRIMITIVES = (int, str, float, bool, bytes, bytearray)


def _uses_iris_collection_class(field_meta: Any | None) -> bool:
    return collection_kind_from_field(field_meta) is not None


class IRISValueAdapterMixin:
    """Persistence-specific IRIS value conversion shared by runtime adapters."""

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        raise NotImplementedError

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        raise NotImplementedError

    def get_property(self, obj: Any, prop_name: str) -> Any:
        raise NotImplementedError

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
                if not callable(getattr(current_prop, "Insert", None)):
                    return False
                for item in val:
                    getattr(current_prop, "Insert")(item)
                return True

            if collection_kind == "array" and isinstance(val, dict):
                if not callable(getattr(current_prop, "SetAt", None)):
                    return False
                for key, item in val.items():
                    getattr(current_prop, "SetAt")(item, str(key))
                return True
        except Exception:
            return False

        return False

    def _native_handles(self, obj: Any) -> tuple[Any, Any, bool] | None:
        oref = obj._oref if hasattr(obj, "_oref") else obj
        db = obj._db if hasattr(obj, "_db") else None
        if db is None:
            return None
        return (oref, db, hasattr(oref, "invoke"))

    @staticmethod
    def _native_get(handles: tuple[Any, Any, bool], field_name: str) -> Any:
        oref, db, use_core_methods = handles
        return oref.get(field_name) if use_core_methods else db.get(oref, field_name)

    @staticmethod
    def _native_set(handles: tuple[Any, Any, bool], field_name: str, value: Any) -> None:
        oref, db, use_core_methods = handles
        if use_core_methods:
            oref.set(field_name, value)
        else:
            db.set(oref, field_name, value)

    @staticmethod
    def _native_invoke(
        handles: tuple[Any, Any, bool],
        target: Any,
        method_name: str,
        *args: Any,
    ) -> None:
        _oref, db, use_core_methods = handles
        if use_core_methods:
            target.invoke(method_name, *args)
        else:
            db.invoke(target, method_name, *args)

    def _clear_property_value(self, obj: Any, field_name: str) -> bool:
        handles = self._native_handles(obj)
        if handles is not None:
            try:
                stream_oref = self._native_get(handles, field_name)
                self._native_invoke(handles, stream_oref, "Clear")
                return True
            except Exception:
                return False

        current_prop = self.get_property(obj, field_name)
        if not hasattr(current_prop, "Clear"):
            return False
        current_prop.Clear()
        return True

    def _set_null_property_value(self, obj: Any, field_name: str) -> bool:
        handles = self._native_handles(obj)
        if handles is None:
            return False

        try:
            self._native_set(handles, field_name, "")
            return True
        except Exception:
            return False

    def _write_stream_property(self, obj: Any, field_name: str, val: bytes | bytearray) -> bool:
        handles = self._native_handles(obj)
        if handles is not None:
            try:
                stream_oref = self._native_get(handles, field_name)
                self._native_invoke(handles, stream_oref, "Clear")
                self._native_invoke(handles, stream_oref, "Write", val)
                return True
            except Exception:
                return False

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
        handles = self._native_handles(obj)
        if handles is not None:
            _oref, db, _use_core_methods = handles
            dyn_value = db.classMethodValue(iris_class_name, "%FromJSON", json.dumps(val))
            self._native_set(handles, field_name, dyn_value)
            return True

        dyn_value = self.call_classmethod(iris_class_name, "_FromJSON", json.dumps(val))
        self.set_property(obj, field_name, dyn_value)
        return True

    def _inject_mapping_value(
        self,
        obj: Any,
        field_name: str,
        val: dict[Any, Any],
        field_meta: Any | None = None,
    ) -> None:
        if _uses_iris_collection_class(field_meta):
            if self._populate_collection_property(obj, field_name, val, field_meta=field_meta):
                return
            if is_percent_list_field(field_meta):
                self.set_property(obj, field_name, val)
                return
        try:
            if self._set_dynamic_json_value(obj, field_name, "%Library.DynamicObject", val):
                return
        except Exception:
            pass
        self.set_property(obj, field_name, val)

    def _encode_percent_list(self, values: list[Any]) -> Any:
        row = io.StringIO()
        csv.writer(row, lineterminator="").writerow(values)
        return self.call_classmethod("%Library.List", "OdbcToLogical", row.getvalue())

    def _inject_sequence_value(
        self,
        obj: Any,
        field_name: str,
        val: list[Any],
        field_meta: Any | None = None,
    ) -> None:
        if is_percent_list_field(field_meta):
            self.set_property(obj, field_name, self._encode_percent_list(val))
            return
        if _uses_iris_collection_class(field_meta):
            if self._populate_collection_property(obj, field_name, val, field_meta=field_meta):
                return
        try:
            if self._set_dynamic_json_value(obj, field_name, "%Library.DynamicArray", val):
                return
        except Exception:
            pass
        self.set_property(obj, field_name, val)

    def _extract_collection_value(self, val: Any) -> Any:
        if (
            callable(getattr(val, "Count", None))
            and callable(getattr(val, "Next", None))
            and callable(getattr(val, "GetAt", None))
        ):
            try:
                key = getattr(val, "Next")("")
                if isinstance(key, str) and key not in ("", None):
                    first_value = getattr(val, "GetAt")(key)
                    if first_value is not None:
                        items: dict[str, Any] = {}
                        while key not in ("", None):
                            items[str(key)] = self.extract_python_value(getattr(val, "GetAt")(key))
                            key = getattr(val, "Next")(key)
                        if items:
                            return items
            except Exception:
                pass

        if callable(getattr(val, "Count", None)) and callable(getattr(val, "GetAt", None)):
            try:
                total = getattr(val, "Count")()
                if isinstance(total, int):
                    return [
                        self.extract_python_value(getattr(val, "GetAt")(index))
                        for index in range(1, total + 1)
                    ]
            except Exception:
                pass

        return None

    def extract_python_value(self, val: Any) -> Any:
        if type(val) in _SCALAR_PRIMITIVES:
            return val
        extracted_collection = self._extract_collection_value(val)
        if extracted_collection is not None:
            return extracted_collection

        iris_class = None
        if hasattr(val, "_ClassName"):
            try:
                iris_class = val._ClassName(1)
            except Exception:
                pass
        else:
            iris_class = type(val).__name__

        if iris_class in ("%Library.DynamicObject", "%Library.DynamicArray"):
            try:
                stream = self.call_classmethod("%Stream.GlobalCharacter", "_New")
                val._ToJSON(stream)
                stream.Rewind()
                val = json.loads(stream.Read())
            except Exception:
                pass
        elif iris_class in (
            "%Stream.GlobalBinary",
            "%Stream.GlobalCharacter",
            "%Stream.FileBinary",
            "%Stream.FileCharacter",
        ):
            try:
                val.Rewind()
                size_val = getattr(val, "Size", 0)
                size = size_val() if callable(size_val) else size_val
                content = val.Read(size) if size and size > 0 else b""
                if isinstance(content, str) and "Binary" in iris_class:
                    content = content.encode("latin1")
                val = content
            except Exception:
                pass
        return val

    def decode_percent_list(self, value: Any) -> list[Any]:
        if value in (None, ""):
            return []

        import iris

        logical_bytes = value if isinstance(value, bytes) else str(value).encode("latin1")
        iris_list = iris.IRISList(logical_bytes)
        return [iris_list.get(index) for index in range(1, iris_list.count() + 1)]

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
            self._inject_mapping_value(obj, field_name, val, field_meta=field_meta)
        elif isinstance(val, list):
            self._inject_sequence_value(obj, field_name, val, field_meta=field_meta)
        else:
            self.set_property(obj, field_name, val)
