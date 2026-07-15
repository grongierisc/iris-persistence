from __future__ import annotations

import os
import warnings
from typing import Any, Protocol

from iris_persistence.values import IRISValueAdapterMixin


class RuntimeAdapter(Protocol):
    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any: ...
    def new_object(self, class_name: str) -> Any: ...
    def save_object(self, obj: Any) -> Any: ...
    def get_object(self, class_name: str, obj_id: str) -> Any: ...
    def delete_object(self, class_name: str, obj_id: str) -> bool: ...
    def get_dbapi_connection(self) -> Any: ...
    def begin_transaction(self) -> None: ...
    def commit_transaction(self) -> None: ...
    def rollback_transaction(self) -> None: ...

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None: ...
    def get_property(self, obj: Any, prop_name: str) -> Any: ...
    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any: ...
    def get_object_id(self, obj: Any) -> str | None: ...
    def is_ok(self, status: Any) -> bool: ...
    def format_status(self, status: Any) -> str: ...
    def extract_python_value(self, val: Any) -> Any: ...
    def extract_typed_python_value(self, val: Any, collection_kind: str | None) -> Any: ...
    def clear_reference(self, obj: Any, field_name: str, *, serial: bool = False) -> bool: ...
    def decode_percent_list(self, value: Any) -> list[Any]: ...
    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None: ...


_active_runtime: RuntimeAdapter | None = None
_wrapper_runtime: IRISRuntimeAdapter | None = None


class _NonClosingConnectionProxy:
    def __init__(self, connection: Any):
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def close(self) -> None:
        return None


def get_runtime() -> RuntimeAdapter:
    if _active_runtime is not None:
        return _active_runtime
    global _wrapper_runtime
    if _wrapper_runtime is None:
        _wrapper_runtime = IRISRuntimeAdapter()
    return _wrapper_runtime


def _reset_model_runtime_caches() -> None:
    try:
        import iris_persistence.models as models
    except Exception:
        return

    def walk(model_cls: Any):
        for subclass in model_cls.__subclasses__():
            yield subclass
            yield from walk(subclass)

    for model_cls in walk(models.Model):
        if "_sql_table_name" in getattr(model_cls, "__dict__", {}):
            delattr(model_cls, "_sql_table_name")

    try:
        import iris_persistence.query as query
    except Exception:
        return
    query._AUTO_SYNCED.clear()


def configure_default_runtime(runtime: RuntimeAdapter | None) -> None:
    """Override the wrapper-backed runtime, primarily for unit tests."""
    global _active_runtime
    _active_runtime = runtime
    _reset_model_runtime_caches()


def configure_runtime(
    native_connection: Any | None = None,
    *,
    dbapi_connection: Any | None = None,
    iris_handle: Any | None = None,
    mode: str | None = None,
    install_dir: str | None = None,
) -> None:
    """Configure the underlying iris wrapper runtime and clear test overrides."""
    try:
        import iris
    except ImportError:
        raise ImportError("Failed to import the `iris` package.")

    config: dict[str, Any] = {}
    if mode is not None:
        config["mode"] = mode
    if install_dir is not None:
        config["install_dir"] = install_dir
    if native_connection is not None:
        config["native_connection"] = native_connection
    if dbapi_connection is not None:
        config["dbapi"] = dbapi_connection
    if iris_handle is not None:
        config["iris"] = iris_handle

    iris.runtime.configure(**config)
    configure_default_runtime(None)


def configure(
    native_connection: Any | None = None,
    *,
    dbapi_connection: Any | None = None,
    iris_handle: Any | None = None,
    mode: str | None = None,
    install_dir: str | None = None,
) -> None:
    """Deprecated alias for :func:`configure_runtime`."""
    warnings.warn(
        "iris_persistence.configure() is deprecated; use configure_runtime() instead",
        DeprecationWarning,
        stacklevel=2,
    )
    configure_runtime(
        native_connection,
        dbapi_connection=dbapi_connection,
        iris_handle=iris_handle,
        mode=mode,
        install_dir=install_dir,
    )


class IRISRuntimeAdapter(IRISValueAdapterMixin):
    """Thin adapter over the iris wrapper facade plus persistence-specific value handling."""

    def _runtime_state(self) -> Any | None:
        try:
            import iris
        except ImportError:
            return None

        runtime = getattr(iris, "runtime", None)
        get_state = getattr(runtime, "get", None)
        if callable(get_state):
            return get_state()
        return None

    def _cls(self, class_name: str):
        try:
            import iris
        except ImportError:
            raise RuntimeError("iris_persistence not configured and `iris` module is unavailable.")

        state = self._runtime_state()
        if getattr(state, "state", None) == "unavailable":
            raise RuntimeError(
                "No IRIS runtime is available. Configure embedded mode with "
                "`IRISINSTALLDIR`, `iris.connect(path=...)`, or configure native "
                "mode with `iris_persistence.configure(connection)`."
            )

        try:
            return iris.cls(class_name)
        except RuntimeError as exc:
            if "iris.cls: error finding class" in str(exc):
                raise RuntimeError(
                    f"IRIS class {class_name!r} does not exist in the current namespace. "
                    "If this model is defined in Python, run `Model.sync_schema()` first. "
                    "Otherwise verify `Meta.classname` and the active IRIS namespace."
                ) from exc
            raise

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        cls_ref = self._cls(class_name)
        return getattr(cls_ref, method_name)(*args)

    def new_object(self, class_name: str) -> Any:
        return self._cls(class_name)._New()

    def save_object(self, obj: Any) -> Any:
        return obj._Save()

    def begin_transaction(self) -> None:
        import iris

        iris.tstart()

    def commit_transaction(self) -> None:
        import iris

        iris.tcommit()

    def rollback_transaction(self) -> None:
        import iris

        rollback_one = getattr(iris, "trollbackone", None)
        if callable(rollback_one):
            rollback_one()
        else:
            iris.trollback()

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
        try:
            import iris
        except ImportError:
            raise RuntimeError("iris_persistence not configured and `iris` module is unavailable.")

        state = self._runtime_state()
        if getattr(state, "dbapi", None) is not None:
            return iris.dbapi.connect(mode="auto")

        if getattr(state, "mode", None) == "native":
            native_connection = getattr(state, "native_connection", None)
            if native_connection is not None and callable(
                getattr(native_connection, "cursor", None)
            ):
                return _NonClosingConnectionProxy(native_connection)

            hostname = getattr(native_connection, "hostname", None)
            port = getattr(native_connection, "port", None)
            namespace = getattr(native_connection, "namespace", None)
            username = os.environ.get("IRISUSERNAME")
            password = os.environ.get("IRISPASSWORD")
            if hostname and port and namespace and username and password:
                return iris.dbapi.connect(
                    mode="native",
                    hostname=hostname,
                    port=port,
                    namespace=namespace,
                    username=username,
                    password=password,
                )

        return iris.dbapi.connect(mode="auto")

    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any:
        return getattr(obj, method_name)(*args)

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        if isinstance(value, bool):
            value = 1 if value else 0
        setattr(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return getattr(obj, prop_name)

    def get_object_id(self, obj: Any) -> str | None:
        for method_name in ("_Id", "Id", "%Id"):
            method = getattr(obj, method_name, None)
            if not callable(method):
                continue
            val = method()
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
