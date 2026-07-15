from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, ContextManager, Iterator, Literal, Protocol

from iris_persistence._runtime_backend import (
    RuntimeClassNotFoundError,
    RuntimeConfigurationError,
    RuntimeOperationError,
    RuntimeStatusError,
    UnsupportedRuntimeOperation,
    WrapperBackend,
)
from iris_persistence.persistence.values import IRISValueCodec


@dataclass(frozen=True)
class RuntimeConfig:
    mode: Literal["auto", "embedded", "native"] = "auto"
    install_dir: str | None = None
    native_connection: Any | None = None
    dbapi_connection: Any | None = None
    iris_handle: Any | None = None


class Runtime(Protocol):
    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any: ...
    def new_object(self, class_name: str) -> Any: ...
    def save_object(self, obj: Any) -> Any: ...
    def get_object(self, class_name: str, obj_id: str) -> Any: ...
    def delete_object(self, class_name: str, obj_id: str) -> bool: ...
    def connection(self) -> ContextManager[Any]: ...
    def transaction(self) -> ContextManager[None]: ...
    def set_property(self, obj: Any, prop_name: str, value: Any) -> None: ...
    def get_property(self, obj: Any, prop_name: str) -> Any: ...
    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any: ...
    def get_object_id(self, obj: Any) -> str | None: ...
    def check_status(self, status: Any, operation: str) -> None: ...
    def compile_class(self, class_name: str, flags: str = "fc /display=none") -> None: ...
    def extract_python_value(self, val: Any) -> Any: ...
    def extract_typed_python_value(self, val: Any, collection_kind: str | None) -> Any: ...
    def clear_reference(self, obj: Any, field_name: str, *, serial: bool = False) -> None: ...
    def decode_percent_list(self, value: Any) -> list[Any]: ...
    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None: ...


class IRISRuntime:
    """Normalized semantic runtime backed by the configured iris wrapper."""

    def __init__(self, backend: WrapperBackend | None = None):
        self._backend = backend or WrapperBackend()
        self._values = IRISValueCodec(self._backend, self)

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        return self._backend.call_classmethod(class_name, method_name, *args)

    def new_object(self, class_name: str) -> Any:
        return self._backend.new_object(class_name)

    def save_object(self, obj: Any) -> Any:
        return self._backend.save_object(obj)

    def get_object(self, class_name: str, obj_id: str) -> Any:
        return self._backend.get_object(class_name, obj_id)

    def delete_object(self, class_name: str, obj_id: str) -> bool:
        return self._backend.is_ok(self._backend.delete_object(class_name, obj_id))

    def get_dbapi_connection(self) -> Any:
        """Compatibility escape hatch; algorithms should use connection()."""
        return self._backend.dbapi_connection()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self._backend.dbapi_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._backend.begin_transaction()
        try:
            yield
        except BaseException as operation_error:
            self._rollback_preserving(operation_error)
            raise
        self._commit_transaction()

    def _rollback_preserving(self, primary_error: BaseException) -> None:
        try:
            self._backend.rollback_transaction()
        except BaseException as rollback_error:
            setattr(primary_error, "rollback_error", rollback_error)

    def _commit_transaction(self) -> None:
        try:
            self._backend.commit_transaction()
        except BaseException as commit_error:
            self._rollback_preserving(commit_error)
            raise RuntimeOperationError(
                "commit_transaction",
                str(commit_error),
                backend=self._backend.backend_name(),
            ) from commit_error

    # Retained temporarily for adapters/tests migrating to context managers.
    def begin_transaction(self) -> None:
        self._backend.begin_transaction()

    def commit_transaction(self) -> None:
        self._backend.commit_transaction()

    def rollback_transaction(self) -> None:
        self._backend.rollback_transaction()

    def invoke_method(self, obj: Any, method_name: str, *args: Any) -> Any:
        return self._backend.invoke_method(obj, method_name, *args)

    def set_property(self, obj: Any, prop_name: str, value: Any) -> None:
        self._backend.set_property(obj, prop_name, value)

    def get_property(self, obj: Any, prop_name: str) -> Any:
        return self._backend.get_property(obj, prop_name)

    def get_object_id(self, obj: Any) -> str | None:
        return self._backend.object_id(obj)

    def is_ok(self, status: Any) -> bool:
        return self._backend.is_ok(status)

    def format_status(self, status: Any) -> str:
        try:
            message = self.call_classmethod("%SYSTEM.Status", "GetErrorText", status)
        except (RuntimeOperationError, RuntimeError, AttributeError, TypeError):
            return str(status)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return str(status)

    def check_status(self, status: Any, operation: str) -> None:
        if not self._backend.is_ok(status):
            raise RuntimeStatusError(
                operation,
                self.format_status(status),
                backend=self._backend.backend_name(),
            )

    def compile_class(self, class_name: str, flags: str = "fc /display=none") -> None:
        status = self.call_classmethod("%SYSTEM.OBJ", "Compile", class_name, flags)
        self.check_status(status, f"compile {class_name}")

    def extract_python_value(self, val: Any) -> Any:
        return self._values.extract_python_value(val)

    def extract_typed_python_value(self, val: Any, collection_kind: str | None) -> Any:
        return self._values.extract_typed_python_value(val, collection_kind)

    def clear_reference(self, obj: Any, field_name: str, *, serial: bool = False) -> None:
        self._values.clear_reference(obj, field_name, serial=serial)

    def decode_percent_list(self, value: Any) -> list[Any]:
        return self._values.decode_percent_list(value)

    def inject_iris_value(
        self,
        obj: Any,
        field_name: str,
        val: Any,
        field_meta: Any | None = None,
    ) -> None:
        self._values.inject_iris_value(obj, field_name, val, field_meta)


_active_runtime: Runtime | None = None


def _reset_model_runtime_caches() -> None:
    try:
        import iris_persistence.models as models
    except ImportError:
        return

    def walk(model_cls: Any) -> Iterator[Any]:
        for subclass in model_cls.__subclasses__():
            yield subclass
            yield from walk(subclass)

    for model_cls in walk(models.Model):
        if "_sql_table_name" in getattr(model_cls, "__dict__", {}):
            delattr(model_cls, "_sql_table_name")

    try:
        import iris_persistence.query as query
    except ImportError:
        return
    query._AUTO_SYNCED.clear()


def install_runtime(runtime: Runtime) -> None:
    global _active_runtime
    _active_runtime = runtime
    _reset_model_runtime_caches()


def get_runtime() -> Runtime:
    global _active_runtime
    if _active_runtime is None:
        _active_runtime = IRISRuntime()
    return _active_runtime


def configure_runtime(config: RuntimeConfig = RuntimeConfig()) -> Runtime:
    wrapper_config: dict[str, Any] = {"mode": config.mode}
    if config.install_dir is not None:
        wrapper_config["install_dir"] = config.install_dir
    if config.native_connection is not None:
        wrapper_config["native_connection"] = config.native_connection
    if config.dbapi_connection is not None:
        wrapper_config["dbapi"] = config.dbapi_connection
    if config.iris_handle is not None:
        wrapper_config["iris"] = config.iris_handle
    WrapperBackend.configure(**wrapper_config)

    runtime = IRISRuntime()
    install_runtime(runtime)
    return runtime


__all__ = [
    "IRISRuntime",
    "Runtime",
    "RuntimeClassNotFoundError",
    "RuntimeConfig",
    "RuntimeConfigurationError",
    "RuntimeOperationError",
    "RuntimeStatusError",
    "UnsupportedRuntimeOperation",
    "configure_runtime",
    "get_runtime",
    "install_runtime",
]
