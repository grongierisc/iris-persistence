"""
Developer-experience facade over the explicit IRIS runtime.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

from .adapter import IRISAdapter
from .binder import Binder
from .registry import Registry
from .schema import SchemaApplier, SchemaCompiler, SchemaPlan, SchemaPlanner
from .session import Session


class DefaultRuntime:
    """Lazy runtime facade for ObjectScript-style workflows."""

    def __init__(self) -> None:
        self.registry = Registry()
        self._adapter: IRISAdapter | None = None
        self._binder: Binder | None = None
        self._session_var: ContextVar[Session | None] = ContextVar("iris_orm_default_session", default=None)
        self._prepared: dict[str, int] = {}

    @property
    def adapter(self) -> IRISAdapter:
        if self._adapter is None:
            self._adapter = IRISAdapter()
        return self._adapter

    @property
    def binder(self) -> Binder:
        if self._binder is None:
            self._binder = Binder(self.registry, self.adapter)
        return self._binder

    def register(self, model_class: type) -> type:
        self.registry.register(model_class)
        classname = str(getattr(model_class, "_iris_classname", "") or "")
        if classname:
            model_id = id(model_class)
            if self._prepared.get(classname) not in {None, model_id}:
                self._prepared.pop(classname, None)
                if self._binder is not None:
                    self._binder._bound.pop(classname, None)  # type: ignore[attr-defined]
        return model_class

    def bind_existing(
        self,
        classname: str,
        *,
        model_name: str | None = None,
        serial: bool = False,
    ) -> type:
        model_class = self.registry.bind_existing(classname, model_name=model_name, serial=serial)
        self.bind(model_class)
        return model_class

    def bind(self, model_class: type) -> type:
        self.register(model_class)
        self._prepare_model(model_class)
        return self.binder.bind_model(model_class)

    def plan(self, model_class: type) -> SchemaPlan:
        self.registry.register(model_class)
        self._ensure_python_mode(model_class)
        classnames = [model_class._iris_classname]  # type: ignore[attr-defined]
        live = SchemaCompiler(self.adapter).catalog_from_iris(classnames)
        desired = self.registry.export_schema().select(classnames)
        return SchemaPlanner().diff(live, desired)

    def sync(
        self,
        model_class: type,
        *,
        force: bool = False,
        allow_manual: bool | None = None,
    ) -> SchemaPlan:
        plan = self.plan(model_class)
        manual = force if allow_manual is None else allow_manual
        if not plan.is_empty():
            SchemaApplier(self.adapter).apply(plan, allow_manual=manual)
        self._mark_prepared(model_class)
        return plan

    def query(self, model_class: type) -> Any:
        self._prepare_model(model_class)
        session = self._current_session() or Session(self.binder, self.adapter)
        return session.query(model_class)

    def get(self, model_class: type, obj_id: Any) -> Any | None:
        self._prepare_model(model_class)
        session = self._current_session() or Session(self.binder, self.adapter)
        return session.get(model_class, obj_id)

    def save(self, instance: Any) -> Any:
        self._prepare_model(type(instance))
        session = self._current_session()
        if session is None:
            session = Session(self.binder, self.adapter)
            session.add(instance)
            session.commit()
            return instance
        session.add(instance)
        session.flush()
        return instance

    def delete(self, instance: Any) -> None:
        self._prepare_model(type(instance))
        session = self._current_session()
        if session is None:
            session = Session(self.binder, self.adapter)
            session.delete(instance)
            session.commit()
            return
        session.delete(instance)
        session.flush()

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = Session(self.binder, self.adapter)
        token = self._session_var.set(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            self._session_var.reset(token)

    def _current_session(self) -> Session | None:
        return self._session_var.get()

    def _prepare_model(self, model_class: type) -> None:
        self.register(model_class)
        classname = model_class._iris_classname  # type: ignore[attr-defined]
        model_id = id(model_class)
        if self._prepared.get(classname) == model_id:
            return
        mode = self._model_mode(model_class)
        if mode == "python":
            plan = self.plan(model_class)
            if plan.manual_operations:
                names = ", ".join(f"{item.kind}:{item.classname}" for item in plan.manual_operations)
                raise RuntimeError(
                    f"{model_class.__name__} requires manual schema alignment: {names}. "
                    'Run sync(force=True) to apply destructive changes explicitly.'
                )
            if plan.executable_operations:
                SchemaApplier(self.adapter).apply(plan, allow_manual=False)
        self.binder.bind_model(model_class)
        self._mark_prepared(model_class)

    def _mark_prepared(self, model_class: type) -> None:
        classname = str(getattr(model_class, "_iris_classname", "") or "")
        if classname:
            self._prepared[classname] = id(model_class)

    @staticmethod
    def _model_mode(model_class: type) -> str:
        return str(getattr(model_class, "_iris_mode", "python") or "python").strip().lower()

    def _ensure_python_mode(self, model_class: type) -> None:
        mode = self._model_mode(model_class)
        if mode == "python":
            return
        raise RuntimeError(
            f"{model_class.__name__} is in {mode!r} mode. "
            'Schema plan/sync is only available for models with _iris_mode = "python".'
        )


_DEFAULT_RUNTIME = DefaultRuntime()


def get_default_runtime() -> DefaultRuntime:
    return _DEFAULT_RUNTIME


def configure_default_runtime(
    *,
    adapter: IRISAdapter | None = None,
    registry: Registry | None = None,
) -> DefaultRuntime:
    if registry is not None:
        _DEFAULT_RUNTIME.registry = registry
    if adapter is not None:
        _DEFAULT_RUNTIME._adapter = adapter
    _DEFAULT_RUNTIME._binder = None
    return _DEFAULT_RUNTIME


def reset_default_runtime() -> DefaultRuntime:
    _DEFAULT_RUNTIME.registry = Registry()
    _DEFAULT_RUNTIME._adapter = None
    _DEFAULT_RUNTIME._binder = None
    _DEFAULT_RUNTIME._prepared = {}
    _DEFAULT_RUNTIME._session_var.set(None)
    return _DEFAULT_RUNTIME


def bind_existing(classname: str, *, model_name: str | None = None, serial: bool = False) -> type:
    return _DEFAULT_RUNTIME.bind_existing(classname, model_name=model_name, serial=serial)


def session_scope() -> Any:
    return _DEFAULT_RUNTIME.session_scope()
