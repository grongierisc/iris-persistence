"""
Abstract wrapper for IRIS backend. Toggles between the FakeAdapter and true real IRIS DB-API contexts seamlessly.
"""
from typing import Any, Protocol

class RuntimeAdapter(Protocol):
    """Abstraction for IRIS capabilities so we don't strictly require live IRIS in testing environments."""
    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any: ...
    def save_object(self, obj: Any) -> Any: ...
    def get_object(self, class_name: str, obj_id: str) -> Any: ...
    def delete_object(self, class_name: str, obj_id: str) -> bool: ...
    def get_dbapi_connection(self) -> Any: ...

_active_runtime: RuntimeAdapter | None = None

def get_runtime() -> RuntimeAdapter:
    global _active_runtime
    if _active_runtime is None:
        try:
            import iris
            # By default fallback mapping if iris can be imported and configure is not explicitly called:
            iris.runtime.configure()  # automatic
            _active_runtime = NativeIRISAdapter()
        except ImportError:
            raise RuntimeError("iris_orm not configured and `iris` module is unavailable. Please call iris_orm.configure().")
    return _active_runtime

def configure_default_runtime(runtime: RuntimeAdapter) -> None:
    global _active_runtime
    _active_runtime = runtime

def configure(native_connection=None) -> None:
    """Configures iris_orm to use an underlying iris runtime."""
    try:
        import iris
    except ImportError:
        raise ImportError("Failed to import the `iris` package. Please install `iris-embedded-python-wrapper`.")
    
    if native_connection:
        iris.runtime.configure(mode="native", native_connection=native_connection)
    else:
        iris.runtime.configure()  # Auto discovery embedded/native
        
    configure_default_runtime(NativeIRISAdapter())

class NativeIRISAdapter:
    def _cls(self, class_name: str):
        import iris
        return iris.cls(class_name)

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        cls_ref = self._cls(class_name)
        mapped_name = method_name.replace("%", "_", 1) if method_name.startswith("%") else method_name
        if args:
            return getattr(cls_ref, mapped_name)(*args)
        else:
            return getattr(cls_ref, mapped_name)()

    def save_object(self, obj: Any) -> Any:
        return obj._Save()

    def get_object(self, class_name: str, obj_id: str) -> Any:
        cls_ref = self._cls(class_name)
        return cls_ref._OpenId(obj_id)

    def delete_object(self, class_name: str, obj_id: str) -> bool:
        cls_ref = self._cls(class_name)
        status = cls_ref._DeleteId(obj_id)
        return getattr(status, "IsOK", lambda: True)()
        
    def get_dbapi_connection(self) -> Any:
        import iris
        return iris.dbapi.connect(mode="auto")
