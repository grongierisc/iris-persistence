from __future__ import annotations

from typing import Any

from .schema import (
    SUPPORTED_PROPERTY_PARAMETERS,
    _to_int,
    coerce_to_iris_logical,
    is_dynamic_type,
    is_list_of_datatypes,
    is_stream_type,
    read_dynamic_value,
    read_stream_value,
)


class _PropertyValueMixin:
    """Type-specific property I/O: streams, dynamic objects, IRISList, and property parameters.

    Depends on ``_IRISObjectMixin`` being present in the MRO (uses ``_object_get``,
    ``_object_set``, ``_object_invoke``, ``_class_method_object``,
    ``looks_like_iris_object``).
    """

    # ------------------------------------------------------------------ IRISList support

    def _use_iris_list_for_datatypes(self) -> bool:
        return False

    def _new_iris_list(self) -> Any:
        raise TypeError("IRISList support is unavailable for this runtime")

    def _iris_list_from_python(self, value: list[Any]) -> Any:
        iris_list = self._new_iris_list()
        for item in value:
            append = getattr(iris_list, "append", None)
            if callable(append):
                append(item)
            else:
                raise TypeError("IRISList object does not support append()")
        return iris_list

    @staticmethod
    def _python_from_iris_list(value: Any) -> list[Any]:
        if value is None:
            return []
        size = getattr(value, "size", None)
        getter = getattr(value, "get", None)
        if callable(size) and callable(getter):
            return [getter(i) for i in range(1, int(size()) + 1)]
        return list(value)

    # ------------------------------------------------------------------ Property value read/write

    def _read_property_value(self, obj: Any, prop_name: str, iris_type: str) -> Any:
        if is_list_of_datatypes(iris_type) and self._use_iris_list_for_datatypes():
            value = self._object_get(obj, prop_name, iris_type)  # type: ignore[attr-defined]
            return None if value is None else self._python_from_iris_list(value)
        value = self._object_get(obj, prop_name, iris_type)  # type: ignore[attr-defined]
        if is_stream_type(iris_type):
            return read_stream_value(value, iris_type)
        if is_dynamic_type(iris_type):
            return read_dynamic_value(value)
        return value

    def _write_stream_property(self, obj: Any, prop_name: str, value: Any, iris_type: str) -> None:
        if value is None:
            self._object_set(obj, prop_name, None)  # type: ignore[attr-defined]
            return
        payload = self._coerce_runtime_value(value, iris_type)
        # Preferred path: call the IRIS-generated getter (e.g. ``bytesGet``) to obtain
        # the stream ORef already attached to the object, then write in-place.  This
        # avoids passing an ORef as an argument, which fails over the network gateway
        # because IRISList cannot encode ORef type 36.
        try:
            stream = self._object_invoke(obj, f"{prop_name}Get")  # type: ignore[attr-defined]
            if stream is not None and stream != "" and self.looks_like_iris_object(stream):  # type: ignore[attr-defined]
                self._stream_call(stream, "Clear")
                self._stream_call(stream, "Write", payload)
                self._stream_call(stream, "Rewind")
                return
        except Exception:
            pass
        # Fallback: create a new stream object and assign via setattr.  Works in
        # embedded (in-process) mode; may fail in remote mode if the stream property
        # was not pre-initialised by %New.
        stream = self._new_stream_object(iris_type)
        self._stream_call(stream, "Write", payload)
        self._stream_call(stream, "Rewind")
        self._object_set(obj, prop_name, stream)  # type: ignore[attr-defined]

    def _write_dynamic_property(self, obj: Any, prop_name: str, value: Any, iris_type: str) -> None:
        if value is None:
            self._object_set(obj, prop_name, None)  # type: ignore[attr-defined]
            return
        payload = self._coerce_runtime_value(value, iris_type)  # JSON string
        # Preferred path (remote mode): use setObject() on the underlying IRISObject
        # directly (intersystems_iris 2021+).  Bypasses IRISList encoding that rejects
        # ORef type 36.
        dynamic_obj = self._class_method_object(iris_type, "%FromJSON", payload)  # type: ignore[attr-defined]
        obj_oref = getattr(obj, "_oref", None)
        dynamic_oref = getattr(dynamic_obj, "_oref", None)
        if obj_oref is not None and dynamic_oref is not None:
            set_object = getattr(obj_oref, "setObject", None)
            if callable(set_object):
                try:
                    set_object(prop_name, dynamic_oref)
                    return
                except Exception:
                    pass
        # Fallback: use the IRIS-generated property setter via invoke(), then fall
        # back further to setattr.  Works in embedded mode.
        try:
            self._object_invoke(obj, f"{prop_name}Set", dynamic_obj)  # type: ignore[attr-defined]
        except Exception:
            self._object_set(obj, prop_name, dynamic_obj)  # type: ignore[attr-defined]

    @staticmethod
    def _coerce_runtime_value(value: Any, iris_type: str) -> Any:
        return coerce_to_iris_logical(value, iris_type)

    def _new_stream_object(self, iris_type: str) -> Any:
        return self._class_method_object(iris_type, "%New")  # type: ignore[attr-defined]

    @staticmethod
    def _stream_call(stream: Any, method_name: str, *args: Any) -> Any:
        method = getattr(stream, method_name, None)
        if callable(method):
            return method(*args)
        invoke = getattr(stream, "invoke", None)
        if callable(invoke):
            return invoke(method_name, *args)
        raise TypeError(f"Stream object does not support {method_name}()")

    # ------------------------------------------------------------------ Property parameters

    def _prop_param_get(self, prop: Any, key: str) -> str | None:
        getter = getattr(prop, "ParametersGetAt", None)
        if callable(getter):
            try:
                value = getter(key)
                return str(value) if value not in {"", None} else None
            except Exception:
                return None
        collection = self._schema_get(prop, "Parameters", as_object=True)  # type: ignore[attr-defined]
        if collection is None:
            return None
        get_at = getattr(collection, "GetAt", None)
        if callable(get_at):
            try:
                value = get_at(key)
                return str(value) if value not in {"", None} else None
            except Exception:
                return None
        return None

    def _prop_param_set(self, prop: Any, key: str, value: str) -> None:
        setter = getattr(prop, "ParametersSetAt", None)
        if callable(setter):
            setter(value, key)
            return
        collection = self._schema_get(prop, "Parameters", as_object=True)  # type: ignore[attr-defined]
        if collection is None:
            return
        set_at = getattr(collection, "SetAt", None)
        if callable(set_at):
            set_at(value, key)

    def _prop_param_remove(self, prop: Any, key: str) -> None:
        remover = getattr(prop, "ParametersRemoveAt", None)
        if callable(remover):
            try:
                remover(key)
            except Exception:
                pass
            return
        collection = self._schema_get(prop, "Parameters", as_object=True)  # type: ignore[attr-defined]
        if collection is None:
            return
        remove_at = getattr(collection, "RemoveAt", None)
        if callable(remove_at):
            try:
                remove_at(key)
            except Exception:
                pass

    def _read_maxlen(self, prop: Any) -> int | None:
        value = self._prop_param_get(prop, "MAXLEN")
        return _to_int(value) or None

    def _extract_property_parameters(self, prop: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            value = self._prop_param_get(prop, name)
            if value is not None:
                result[name] = value
        return result

    def _write_maxlen(self, prop_def: Any, maxlen: int | None) -> None:
        if maxlen is not None:
            self._prop_param_set(prop_def, "MAXLEN", str(maxlen))
        else:
            self._prop_param_remove(prop_def, "MAXLEN")

    def _replace_property_parameters(self, prop_def: Any, parameters: dict[str, str]) -> None:
        normalized = {k: v for k, v in parameters.items() if k in SUPPORTED_PROPERTY_PARAMETERS}
        for name in SUPPORTED_PROPERTY_PARAMETERS:
            if name in normalized:
                self._prop_param_set(prop_def, name, normalized[name])
            else:
                self._prop_param_remove(prop_def, name)
