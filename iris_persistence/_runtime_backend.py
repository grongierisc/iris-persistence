from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class RuntimeConfigurationError(RuntimeError):
    """The IRIS wrapper cannot provide a usable runtime."""


class RuntimeOperationError(RuntimeError):
    """A normalized runtime operation failed."""

    def __init__(self, operation: str, message: str, *, backend: str = "wrapper"):
        self.operation = operation
        self.backend = backend
        super().__init__(f"{operation} failed ({backend}): {message}")


class RuntimeStatusError(RuntimeOperationError):
    """IRIS returned a failing status value."""


class RuntimeClassNotFoundError(RuntimeOperationError):
    """An IRIS class is unavailable in the active namespace."""


class UnsupportedRuntimeOperation(RuntimeOperationError):
    """The configured runtime cannot perform an operation."""


@dataclass(frozen=True)
class NativeHandles:
    object_ref: Any
    database: Any
    core_methods: bool


class _DBAPIHandleProxy:
    """Normalize vendor DBAPI failures without leaking wrapper exception types."""

    def __init__(self, handle: Any, error_type: type[BaseException], backend: str):
        self._handle = handle
        self._error_type = error_type
        self._backend = backend

    def __getattr__(self, name: str) -> Any:
        value = getattr(self._handle, name)
        if not callable(value):
            return value

        def invoke(*args: Any, **kwargs: Any) -> Any:
            try:
                return value(*args, **kwargs)
            except self._error_type as exc:
                raise RuntimeOperationError(
                    f"dbapi_{name}", str(exc), backend=self._backend
                ) from exc

        return invoke

    def __iter__(self) -> _DBAPIHandleProxy:
        return self

    def __next__(self) -> Any:
        try:
            return next(self._handle)
        except self._error_type as exc:
            raise RuntimeOperationError(
                "dbapi_iterate", str(exc), backend=self._backend
            ) from exc


class ManagedConnectionProxy(_DBAPIHandleProxy):
    def __init__(
        self,
        connection: Any,
        error_type: type[BaseException],
        backend: str,
        *,
        close_owned: bool,
    ):
        super().__init__(connection, error_type, backend)
        self._close_owned = close_owned

    def cursor(self, *args: Any, **kwargs: Any) -> _DBAPIHandleProxy:
        try:
            cursor = self._handle.cursor(*args, **kwargs)
        except self._error_type as exc:
            raise RuntimeOperationError(
                "dbapi_cursor", str(exc), backend=self._backend
            ) from exc
        return _DBAPIHandleProxy(cursor, self._error_type, self._backend)

    def close(self) -> None:
        if self._close_owned:
            super().__getattr__("close")()


class WrapperBackend:
    """The only layer that knows wrapper mode and native object representation."""

    @classmethod
    def configure(cls, **config: Any) -> None:
        try:
            cls._iris().runtime.configure(**config)
        except (AttributeError, RuntimeError, TypeError) as exc:
            raise RuntimeConfigurationError(str(exc)) from exc

    @staticmethod
    def _iris() -> Any:
        try:
            import iris
        except ImportError as exc:
            raise RuntimeConfigurationError(
                "iris_persistence is not configured and the `iris` module is unavailable"
            ) from exc
        return iris

    def state(self) -> Any | None:
        iris = self._iris()
        runtime = getattr(iris, "runtime", None)
        get_state = getattr(runtime, "get", None)
        return get_state() if callable(get_state) else None

    def backend_name(self) -> str:
        return str(getattr(self.state(), "mode", None) or "wrapper")

    def class_ref(self, class_name: str) -> Any:
        iris = self._iris()
        if getattr(self.state(), "state", None) == "unavailable":
            raise RuntimeConfigurationError("no IRIS runtime is available")
        try:
            return iris.cls(class_name)
        except RuntimeError as exc:
            if "iris.cls: error finding class" in str(exc):
                raise RuntimeClassNotFoundError(
                    "class_ref",
                    f"IRIS class {class_name!r} does not exist in the current namespace. "
                    "Run Model.sync_schema() for Python-defined models, then verify "
                    "Meta.classname and the active IRIS namespace",
                    backend=self.backend_name(),
                ) from exc
            raise RuntimeOperationError(
                "class_ref", str(exc), backend=self.backend_name()
            ) from exc

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        try:
            return getattr(self.class_ref(class_name), method_name)(*args)
        except RuntimeOperationError:
            raise
        except (AttributeError, RuntimeError, TypeError) as exc:
            raise RuntimeOperationError(
                "call_classmethod", str(exc), backend=self.backend_name()
            ) from exc

    def new_object(self, class_name: str) -> Any:
        return self.class_ref(class_name)._New()

    @staticmethod
    def save_object(obj: Any) -> Any:
        return obj._Save()

    def get_object(self, class_name: str, obj_id: str) -> Any:
        return self.class_ref(class_name)._OpenId(obj_id)

    def delete_object(self, class_name: str, obj_id: str) -> Any:
        return self.class_ref(class_name)._DeleteId(obj_id)

    def begin_transaction(self) -> None:
        self._iris().tstart()

    def commit_transaction(self) -> None:
        self._iris().tcommit()

    def rollback_transaction(self) -> None:
        iris = self._iris()
        rollback_one = getattr(iris, "trollbackone", None)
        if callable(rollback_one):
            rollback_one()
        else:
            iris.trollback()

    def dbapi_connection(self) -> Any:
        iris = self._iris()
        state = self.state()
        error_type = getattr(getattr(iris, "dbapi", None), "Error", RuntimeError)
        if not isinstance(error_type, type) or not issubclass(error_type, BaseException):
            error_type = RuntimeError
        backend = str(getattr(state, "mode", None) or "wrapper")
        if getattr(state, "dbapi", None) is not None:
            connection = iris.dbapi.connect(mode="auto")
            return ManagedConnectionProxy(connection, error_type, backend, close_owned=True)
        if getattr(state, "mode", None) == "native":
            native_connection = getattr(state, "native_connection", None)
            if native_connection is not None and callable(
                getattr(native_connection, "cursor", None)
            ):
                return ManagedConnectionProxy(
                    native_connection,
                    error_type,
                    backend,
                    close_owned=False,
                )
            hostname = getattr(native_connection, "hostname", None)
            port = getattr(native_connection, "port", None)
            namespace = getattr(native_connection, "namespace", None)
            username = os.environ.get("IRISUSERNAME")
            password = os.environ.get("IRISPASSWORD")
            if hostname and port and namespace and username and password:
                connection = iris.dbapi.connect(
                    mode="native",
                    hostname=hostname,
                    port=port,
                    namespace=namespace,
                    username=username,
                    password=password,
                )
                return ManagedConnectionProxy(
                    connection, error_type, backend, close_owned=True
                )
        connection = iris.dbapi.connect(mode="auto")
        return ManagedConnectionProxy(connection, error_type, backend, close_owned=True)

    @staticmethod
    def invoke_method(obj: Any, method_name: str, *args: Any) -> Any:
        return getattr(obj, method_name)(*args)

    @staticmethod
    def set_property(obj: Any, prop_name: str, value: Any) -> None:
        setattr(obj, prop_name, 1 if value is True else 0 if value is False else value)

    @staticmethod
    def get_property(obj: Any, prop_name: str) -> Any:
        return getattr(obj, prop_name)

    @staticmethod
    def object_id(obj: Any) -> str | None:
        method = getattr(obj, "_Id", None)
        if not callable(method):
            return None
        value = method()
        return str(value) if value else None

    @staticmethod
    def is_ok(status: Any) -> bool:
        if isinstance(status, int):
            return status != 0
        if isinstance(status, str):
            return not status.startswith("0 ")
        checker = getattr(status, "IsOK", None)
        return bool(checker()) if callable(checker) else False

    def format_status(self, status: Any) -> str:
        try:
            message = self.call_classmethod("%SYSTEM.Status", "GetErrorText", status)
        except RuntimeOperationError:
            return str(status)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return str(status)

    @staticmethod
    def native_handles(obj: Any) -> NativeHandles | None:
        object_ref = getattr(obj, "_oref", obj)
        database = getattr(obj, "_db", None)
        if database is None:
            return None
        return NativeHandles(object_ref, database, hasattr(object_ref, "invoke"))

    def try_native_get(self, obj: Any, field_name: str) -> tuple[bool, Any]:
        handles = self.native_handles(obj)
        if handles is None:
            return False, None
        try:
            if handles.core_methods:
                return True, handles.object_ref.get(field_name)
            return True, handles.database.get(handles.object_ref, field_name)
        except (AttributeError, RuntimeError, TypeError):
            return True, None

    def try_native_set(self, obj: Any, field_name: str, value: Any) -> tuple[bool, bool]:
        handles = self.native_handles(obj)
        if handles is None:
            return False, False
        try:
            if handles.core_methods:
                handles.object_ref.set(field_name, value)
            else:
                handles.database.set(handles.object_ref, field_name, value)
            return True, True
        except (AttributeError, RuntimeError, TypeError):
            return False, True

    def try_native_invoke(self, obj: Any, method_name: str, *args: Any) -> bool:
        handles = self.native_handles(obj)
        if handles is None:
            return False
        try:
            if handles.core_methods:
                handles.object_ref.invoke(method_name, *args)
            else:
                handles.database.invoke(handles.object_ref, method_name, *args)
            return True
        except (AttributeError, RuntimeError, TypeError):
            return False

    def try_native_invoke_target(self, obj: Any, target: Any, method_name: str, *args: Any) -> bool:
        handles = self.native_handles(obj)
        if handles is None:
            return False
        try:
            if handles.core_methods:
                target.invoke(method_name, *args)
            else:
                handles.database.invoke(target, method_name, *args)
            return True
        except (AttributeError, RuntimeError, TypeError):
            return False

    def dynamic_json_value(self, obj: Any, class_name: str, value: str) -> tuple[bool, Any]:
        handles = self.native_handles(obj)
        if handles is None:
            return False, None
        return True, handles.database.classMethodValue(class_name, "%FromJSON", value)

    def decode_percent_list(self, value: Any) -> list[Any]:
        logical_bytes = value if isinstance(value, bytes) else str(value).encode("latin1")
        iris_list = self._iris().IRISList(logical_bytes)
        return [iris_list.get(index) for index in range(1, iris_list.count() + 1)]
