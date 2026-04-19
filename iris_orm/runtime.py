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
    def extract_python_value(self, val: Any) -> Any: ...
    def inject_iris_value(self, obj: Any, field_name: str, val: Any) -> None: ...

_active_runtime: RuntimeAdapter | None = None

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
        configure_default_runtime(NativeProxyAdapter())
    else:
        iris.runtime.configure()
        mode = getattr(iris.runtime, "mode", "embedded")
        if mode == "native":
            configure_default_runtime(NativeProxyAdapter())
        else:
            configure_default_runtime(EmbeddedAdapter())

class BaseIRISAdapter:
    def _cls(self, class_name: str):
        import iris
        return iris.cls(class_name)

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

    def extract_python_value(self, val: Any) -> Any:
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
        elif iris_class in ("%Stream.GlobalBinary", "%Stream.GlobalCharacter", "%Stream.FileBinary", "%Stream.FileCharacter"):
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

    def inject_iris_value(self, obj: Any, field_name: str, val: Any) -> None:
        if isinstance(val, (bytes, bytearray)):
            current_prop = self.get_property(obj, field_name)
            if hasattr(current_prop, "Write"):
                current_prop.Clear()
                current_prop.Write(val)
            else:
                self.set_property(obj, field_name, val)
        elif isinstance(val, dict):
            import json
            try:
                dyn_obj = self.call_classmethod("%Library.DynamicObject", "_FromJSON", json.dumps(val))
                self.set_property(obj, field_name, dyn_obj)
            except Exception:
                self.set_property(obj, field_name, val)
        elif isinstance(val, list):
            import json
            try:
                dyn_arr = self.call_classmethod("%Library.DynamicArray", "_FromJSON", json.dumps(val))
                self.set_property(obj, field_name, dyn_arr)
            except Exception:
                self.set_property(obj, field_name, val)
        else:
            self.set_property(obj, field_name, val)

class NativeProxyAdapter(BaseIRISAdapter):
    def inject_iris_value(self, obj: Any, field_name: str, val: Any) -> None:
        import json
        oref = obj._oref if hasattr(obj, "_oref") else obj
        db = obj._db if hasattr(obj, "_db") else None
        
        if db is None:
            return super().inject_iris_value(obj, field_name, val)
            
        use_core_methods = hasattr(oref, "invoke")
            
        if isinstance(val, (bytes, bytearray)):
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
            try:
                dyn_obj = db.classMethodValue("%Library.DynamicObject", "%FromJSON", json.dumps(val))
                    
                if use_core_methods:
                    oref.set(field_name, dyn_obj)
                else:
                    db.set(oref, field_name, dyn_obj)
            except Exception:
                self.set_property(obj, field_name, val)
        elif isinstance(val, list):
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
            if val: return str(val)
        except AttributeError:
            pass
        try:
            val = obj.Id()
            if val: return str(val)
        except AttributeError:
            pass
        if hasattr(obj, "%Id"):
            val = getattr(obj, "%Id")()
            if val: return str(val)
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
            if val: return str(val)
        except AttributeError:
            pass
        try:
            val = obj.Id()
            if val: return str(val)
        except AttributeError:
            pass
        if hasattr(obj, "%Id"):
            val = getattr(obj, "%Id")()
            if val: return str(val)
        return None
        
    def is_ok(self, status: Any) -> bool:
        if isinstance(status, int):
            return status != 0
        if isinstance(status, str):
            return not status.startswith("0 ")
        if getattr(status, "IsOK", None):
            return status.IsOK()
        return False
