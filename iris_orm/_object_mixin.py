from __future__ import annotations

from typing import Any


class _IRISObjectMixin:
    """Low-level IRIS object primitives: create/open/delete/invoke and lifecycle ops.

    Expects ``self.runtime`` to be set by the concrete subclass.
    """

    # ------------------------------------------------------------------ CRUD primitives

    def _object_new(self, classname: str) -> Any:
        return self._class_method_object(classname, "%New")

    def _object_open(self, classname: str, obj_id: Any) -> Any:
        return self._class_method_object(classname, "%OpenId", obj_id)

    def _object_delete_id(self, classname: str, obj_id: Any) -> Any:
        return self._class_method_object(classname, "%DeleteId", obj_id)

    def _object_get(self, obj: Any, prop_name: str, iris_type: str | None = None) -> Any:
        return getattr(obj, prop_name, None)

    def _object_set(self, obj: Any, prop_name: str, value: Any) -> None:
        setattr(obj, prop_name, value)

    # ------------------------------------------------------------------ Invocation

    @staticmethod
    def _unwrap_args(*args: Any) -> tuple[Any, ...]:
        """Unwrap NativeObjectProxy → raw IRISObject for gateway serialisation compat.

        ``oref.invoke()`` accepts IRISObject, not the Python proxy wrapper, so ORef
        arguments must be unwrapped before crossing the gateway boundary.
        """
        return tuple(getattr(a, "_oref", a) for a in args)

    def _object_invoke(self, obj: Any, method_name: str, *args: Any) -> Any:
        unwrapped = self._unwrap_args(*args)
        attr_name = f"_{method_name[1:]}" if method_name.startswith("%") else method_name
        attr = getattr(obj, attr_name, None)
        if callable(attr):
            return attr(*unwrapped)
        # NativeObjectProxy: speculative oref.get() may return a non-callable scalar
        # for methods like %Id that return a value directly (e.g. after %Save).
        if not unwrapped and attr is not None and attr != "":
            return attr
        # Fallback: call invoke() on the underlying oref directly.  Needed when the
        # Python proxy intercepts attribute access and returns a non-callable stub.
        oref = getattr(obj, "_oref", obj)
        invoke_fn = getattr(oref, "invoke", None)
        if callable(invoke_fn):
            return invoke_fn(method_name, *unwrapped)
        raise AttributeError(f"Cannot invoke {method_name!r} on {type(obj).__name__}")

    def _object_invoke_object(self, obj: Any, method_name: str, *args: Any) -> Any:
        return self._object_invoke(obj, method_name, *args)

    def _wrap_native_object(self, obj: Any, classname: str) -> Any:  # noqa: ARG002
        return obj

    def _class_method_object(self, classname: str, method_name: str, *args: Any) -> Any:
        target = self.cls(classname)
        resolved_name = f"_{method_name[1:]}" if method_name.startswith("%") else method_name
        method = getattr(target, resolved_name, None)
        if not callable(method):
            raise AttributeError(f"{classname}.{method_name}")
        return method(*self._unwrap_args(*args))

    # ------------------------------------------------------------------ Guard / coerce

    def looks_like_iris_object(self, value: Any) -> bool:
        return value is not None and value != ""

    def _check_status(self, status: Any, *, compile: bool = False, schema: bool = False) -> None:
        if status in {None, "", 1, True}:
            return
        try:
            ok = bool(self.cls("%SYSTEM.Status")._IsOK(status))
        except Exception:
            ok = bool(status)
        if not ok:
            try:
                error_text = str(self.cls("%SYSTEM.Status")._GetErrorText(status))
            except Exception:
                error_text = repr(status)
            from .exceptions import IRISCompileError, IRISConcurrencyError, IRISSchemaError, IRISStatusError
            if compile:
                raise IRISCompileError(error_text, status=status)
            if schema:
                raise IRISSchemaError(error_text, status=status)
            lower = error_text.lower()
            if "lock" in lower or "concurr" in lower:
                raise IRISConcurrencyError(error_text, status=status)
            raise IRISStatusError(error_text, status=status)

    @staticmethod
    def _set_value(obj: Any, name: str, value: Any) -> None:
        if isinstance(value, bool):
            value = 1 if value else 0
        setter = getattr(obj, f"{name}Set", None)
        if callable(setter):
            setter(value)
            return
        setattr(obj, name, value)

    # ------------------------------------------------------------------ Runtime API surface

    def cls(self, classname: str) -> Any:
        return self.runtime.cls(classname)  # type: ignore[attr-defined]

    def native_class(self, classname: str) -> Any:
        return self.cls(classname)

    # ------------------------------------------------------------------ Transaction management

    def begin(self) -> None:
        self.runtime.tstart()  # type: ignore[attr-defined]

    def commit(self) -> None:
        self.runtime.tcommit()  # type: ignore[attr-defined]

    def rollback(self) -> None:
        self.runtime.trollback()  # type: ignore[attr-defined]

    def close(self) -> None:
        pass
