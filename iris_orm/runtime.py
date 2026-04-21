from __future__ import annotations

import csv
import io
import os
from typing import Any, Protocol


class RuntimeAdapter(Protocol):
    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any: ...
    def create_object(self, class_name: str) -> Any: ...
    def save_object(self, obj: Any) -> Any: ...
    def get_object(self, class_name: str, obj_id: str) -> Any: ...
    def delete_object(self, class_name: str, obj_id: str) -> bool: ...
    def get_dbapi_connection(self) -> Any: ...

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None: ...
    def get_property(self, obj: Any, prop_name: str) -> Any: ...
    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any: ...
    def get_object_id(self, obj: Any) -> str: ...
    def is_ok(self, status: Any) -> bool: ...
    def format_status(self, status: Any) -> str: ...
    def extract_python_value(self, val: Any) -> Any: ...
    def decode_percent_list(self, value: Any) -> list[Any]: ...
    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None: ...


_active_runtime: RuntimeAdapter | None = None


_IRIS_COLLECTION_CLASSES = {
    "%List",
    "%ListOfDataTypes",
    "%ListOfObjects",
    "%ArrayOfDataTypes",
    "%ArrayOfObjects",
    "%Library.List",
    "%Library.ListOfDataTypes",
    "%Library.ListOfObjects",
    "%Library.ArrayOfDataTypes",
    "%Library.ArrayOfObjects",
}


def _is_missing_class_error(exc: BaseException) -> bool:
    message = str(exc)
    return "iris.cls: error finding class" in message


def _format_missing_class_error(class_name: str) -> str:
    return (
        f"IRIS class {class_name!r} does not exist in the current namespace. "
        "If this model is defined in Python, run `Model.sync_schema()` first. "
        "Otherwise verify `Meta.classname` and the active IRIS namespace."
    )


def _uses_iris_collection_class(field_meta: Any | None) -> bool:
    collection = getattr(field_meta, "collection", None)
    if collection in {"list", "array"}:
        return True
    iris_type = getattr(field_meta, "iris_type", None)
    return iris_type in _IRIS_COLLECTION_CLASSES


def _is_percent_list_field(field_meta: Any | None) -> bool:
    return getattr(field_meta, "iris_type", None) in {"%List", "%Library.List"}


def _collection_kind_from_field(field_meta: Any | None) -> str | None:
    collection = getattr(field_meta, "collection", None)
    if collection in {"list", "array"}:
        return collection

    iris_type = getattr(field_meta, "iris_type", None)
    if iris_type in {
        "%List",
        "%ListOfDataTypes",
        "%ListOfObjects",
        "%Library.List",
        "%Library.ListOfDataTypes",
        "%Library.ListOfObjects",
    }:
        return "list"
    if iris_type in {
        "%ArrayOfDataTypes",
        "%ArrayOfObjects",
        "%Library.ArrayOfDataTypes",
        "%Library.ArrayOfObjects",
    }:
        return "array"
    return None


def get_runtime() -> RuntimeAdapter:
    global _active_runtime
    if _active_runtime is None:
        try:
            import iris

            iris.runtime.configure()
            mode = getattr(iris.runtime, "mode", "embedded")
            if mode == "native":
                _active_runtime = NativeProxyAdapter()
            else:
                _active_runtime = EmbeddedAdapter()
        except ImportError:
            raise RuntimeError("iris_orm not configured and `iris` module is unavailable.")
    return _active_runtime


def configure_default_runtime(runtime: RuntimeAdapter) -> None:
    global _active_runtime
    _active_runtime = runtime


def configure(native_connection=None) -> None:
    try:
        import iris
    except ImportError:
        raise ImportError("Failed to import the `iris` package.")

    if native_connection:
        iris.runtime.configure(mode="native", native_connection=native_connection)
        configure_default_runtime(NativeProxyAdapter(native_connection))
    else:
        iris.runtime.configure()
        mode = getattr(iris.runtime, "mode", "embedded")
        if mode == "native":
            configure_default_runtime(NativeProxyAdapter())
        else:
            configure_default_runtime(EmbeddedAdapter())


class BaseIRISAdapter:
    def _encode_percent_list(self, values: list[Any]) -> Any:
        row = io.StringIO()
        csv.writer(row, lineterminator="").writerow(values)
        return self.call_classmethod("%Library.List", "OdbcToLogical", row.getvalue())

    def decode_percent_list(self, value: Any) -> list[Any]:
        if value in (None, ""):
            return []

        import iris

        logical_bytes = value if isinstance(value, bytes) else str(value).encode("latin1")
        iris_list = iris.IRISList(logical_bytes)
        return [iris_list.get(index) for index in range(1, iris_list.count() + 1)]

    def _cls(self, class_name: str):
        import iris

        try:
            return iris.cls(class_name)
        except RuntimeError as exc:
            if _is_missing_class_error(exc):
                raise RuntimeError(_format_missing_class_error(class_name)) from exc
            raise

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        cls_ref = self._cls(class_name)
        if args:
            return getattr(cls_ref, method_name)(*args)
        else:
            return getattr(cls_ref, method_name)()

    def create_object(self, class_name: str) -> Any:
        return self.call_classmethod(class_name, "_New")

    def save_object(self, obj: Any) -> Any:
        return obj._Save()

    def format_status(self, status: Any) -> str:
        try:
            message = self.call_classmethod("%SYSTEM.Status", "GetErrorText", status)
            if isinstance(message, str):
                message = message.strip()
                if message:
                    return message
        except Exception:
            pass
        return str(status)

    def get_object(self, class_name: str, obj_id: str) -> Any:
        cls_ref = self._cls(class_name)
        return cls_ref._OpenId(obj_id)

    def delete_object(self, class_name: str, obj_id: str) -> bool:
        cls_ref = self._cls(class_name)
        status = cls_ref._DeleteId(obj_id)
        return self.is_ok(status)

    def get_dbapi_connection(self) -> Any:
        import iris

        return iris.dbapi.connect(mode="auto")

    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any:
        if args:
            return getattr(obj, method_name)(*args)
        else:
            return getattr(obj, method_name)()

    def _populate_collection_property(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> bool:
        collection_kind = _collection_kind_from_field(field_meta)
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
            import json

            try:
                s = self.call_classmethod("%Stream.GlobalCharacter", "_New")
                val._ToJSON(s)
                s.Rewind()
                val = json.loads(s.Read())
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

    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None:
        if val is None:
            current_prop = self.get_property(obj, field_name)
            if hasattr(current_prop, "Clear"):
                current_prop.Clear()
                return
            self.set_property(obj, field_name, val)
        elif isinstance(val, (bytes, bytearray)):
            current_prop = self.get_property(obj, field_name)
            if hasattr(current_prop, "Write"):
                current_prop.Clear()
                current_prop.Write(val)
            else:
                self.set_property(obj, field_name, val)
        elif isinstance(val, dict):
            if _uses_iris_collection_class(field_meta):
                if self._populate_collection_property(obj, field_name, val, field_meta=field_meta):
                    return
                if getattr(field_meta, "iris_type", None) in {"%List", "%Library.List"}:
                    self.set_property(obj, field_name, val)
                    return
            import json

            try:
                dyn_obj = self.call_classmethod(
                    "%Library.DynamicObject", "_FromJSON", json.dumps(val)
                )
                self.set_property(obj, field_name, dyn_obj)
            except Exception:
                self.set_property(obj, field_name, val)
        elif isinstance(val, list):
            if _is_percent_list_field(field_meta):
                self.set_property(obj, field_name, self._encode_percent_list(val))
                return
            if _uses_iris_collection_class(field_meta):
                if self._populate_collection_property(obj, field_name, val, field_meta=field_meta):
                    return
            import json

            try:
                dyn_arr = self.call_classmethod(
                    "%Library.DynamicArray", "_FromJSON", json.dumps(val)
                )
                self.set_property(obj, field_name, dyn_arr)
            except Exception:
                self.set_property(obj, field_name, val)
        else:
            self.set_property(obj, field_name, val)


class NativeProxyAdapter(BaseIRISAdapter):
    def __init__(self, native_connection: Any | None = None):
        self._native_connection = native_connection

    def get_dbapi_connection(self) -> Any:
        import iris

        connection = self._native_connection
        hostname = getattr(connection, "hostname", None)
        port = getattr(connection, "port", None)
        namespace = getattr(connection, "namespace", None)
        username = os.environ.get("IRISUSERNAME")
        password = os.environ.get("IRISPASSWORD")

        if hostname and port and namespace and username and password:
            return iris.dbapi.connect(
                hostname=hostname,
                port=port,
                namespace=namespace,
                username=username,
                password=password,
            )

        return iris.dbapi.connect(mode="auto")

    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None:
        import json

        oref = obj._oref if hasattr(obj, "_oref") else obj
        db = obj._db if hasattr(obj, "_db") else None

        if db is None:
            return super().inject_iris_value(obj, field_name, val, field_meta=field_meta)

        use_core_methods = hasattr(oref, "invoke")

        if val is None:
            try:
                stream_oref = oref.get(field_name) if use_core_methods else db.get(oref, field_name)
                clear = getattr(stream_oref, "invoke", None)
                if use_core_methods and callable(clear):
                    stream_oref.invoke("Clear")
                    return
                if callable(getattr(db, "invoke", None)):
                    db.invoke(stream_oref, "Clear")
                    return
            except Exception:
                self.set_property(obj, field_name, val)
                return
            self.set_property(obj, field_name, val)
        elif isinstance(val, (bytes, bytearray)):
            try:
                stream_oref = oref.get(field_name) if use_core_methods else db.get(oref, field_name)
                if use_core_methods:
                    stream_oref.invoke("Clear")
                    stream_oref.invoke("Write", val)
                else:
                    db.invoke(stream_oref, "Clear")
                    db.invoke(stream_oref, "Write", val)
            except Exception:
                self.set_property(obj, field_name, val)
        elif isinstance(val, dict):
            if _uses_iris_collection_class(field_meta):
                return super().inject_iris_value(obj, field_name, val, field_meta=field_meta)
            try:
                dyn_obj = db.classMethodValue(
                    "%Library.DynamicObject", "%FromJSON", json.dumps(val)
                )

                if use_core_methods:
                    oref.set(field_name, dyn_obj)
                else:
                    db.set(oref, field_name, dyn_obj)
            except Exception:
                self.set_property(obj, field_name, val)
        elif isinstance(val, list):
            if _uses_iris_collection_class(field_meta):
                return super().inject_iris_value(obj, field_name, val, field_meta=field_meta)
            try:
                dyn_obj = db.classMethodValue("%Library.DynamicArray", "%FromJSON", json.dumps(val))

                if use_core_methods:
                    oref.set(field_name, dyn_obj)
                else:
                    db.set(oref, field_name, dyn_obj)
            except Exception:
                self.set_property(obj, field_name, val)
        else:
            self.set_property(obj, field_name, val)

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        setattr(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return getattr(obj, prop_name)

    def get_object_id(self, obj: Any) -> str:
        try:
            val = obj._Id()
            if val:
                return str(val)
        except AttributeError:
            pass
        try:
            val = obj.Id()
            if val:
                return str(val)
        except AttributeError:
            pass
        if hasattr(obj, "%Id"):
            val = getattr(obj, "%Id")()
            if val:
                return str(val)
        return None

    def is_ok(self, status: Any) -> bool:
        if getattr(status, "IsOK", None):
            return status.IsOK()
        if isinstance(status, int) and status == 1:
            return True
        return False


class EmbeddedAdapter(BaseIRISAdapter):
    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        if isinstance(value, bool):
            value = 1 if value else 0
        setattr(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return getattr(obj, prop_name)

    def get_object_id(self, obj: Any) -> str:
        try:
            val = obj._Id()
            if val:
                return str(val)
        except AttributeError:
            pass
        try:
            val = obj.Id()
            if val:
                return str(val)
        except AttributeError:
            pass
        if hasattr(obj, "%Id"):
            val = getattr(obj, "%Id")()
            if val:
                return str(val)
        return None

    def is_ok(self, status: Any) -> bool:
        if isinstance(status, int):
            return status != 0
        if isinstance(status, str):
            return not status.startswith("0 ")
        if getattr(status, "IsOK", None):
            return status.IsOK()
        return False
