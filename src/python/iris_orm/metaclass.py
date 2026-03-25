"""
IRISMeta — metaclass that introspects an IRIS class at Python class-creation
time and injects typed :class:`~iris_orm.descriptors.IRISDescriptor` instances
plus ``__annotations__`` so that IDEs see full type information.
"""
from __future__ import annotations

from typing import Any, Optional

from .descriptors import IRISDescriptor
from .introspection import PropertyInfo, get_class_properties
from .query import IRISQuerySet


class IRISMeta(type):
    """Metaclass for all :class:`IRISModel` subclasses.

    When Python creates a new subclass of :class:`IRISModel`, ``__new__``
    is called with the class dictionary as ``namespace``.  If the class
    sets ``_iris_classname``, the metaclass:

    1. Queries ``%Dictionary.PropertyDefinition`` for every non-system property.
    2. Creates an :class:`~iris_orm.descriptors.IRISDescriptor` for each property.
    3. Injects the descriptors and updates ``__annotations__``.
    4. Attaches an ``objects`` :class:`~iris_orm.query.IRISQuerySet` manager.
    """

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> "IRISMeta":
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        iris_classname: Optional[str] = namespace.get("_iris_classname")
        if not iris_classname:
            # Base class (IRISModel itself) — skip introspection.
            return cls

        # Attempt live introspection; gracefully degrade when no IRIS
        # connection is available (e.g., during unit tests).
        try:
            properties: list[PropertyInfo] = get_class_properties(iris_classname)
        except Exception:
            properties = []

        annotations: dict[str, Any] = {}

        for prop in properties:
            descriptor = IRISDescriptor(
                prop_name=prop.name,
                python_type=prop.python_type,
                required=prop.required,
            )
            # Inject descriptor only if the user has not already defined one.
            if prop.name not in namespace:
                setattr(cls, prop.name, descriptor)

            # Build Optional[T] annotation (all IRIS properties are nullable
            # by default unless Required=1, but we still type as Optional to
            # match IRIS semantics).
            py_name = prop.python_type.__name__ if hasattr(prop.python_type, "__name__") else "Any"
            annotations[prop.name] = Optional[prop.python_type]  # type: ignore[valid-type]

        # Merge with any annotations already present on the class.
        existing = cls.__dict__.get("__annotations__", {})
        cls.__annotations__ = {**annotations, **existing}

        # Store the resolved property metadata for later use (stubs, etc.).
        cls._iris_properties: list[PropertyInfo] = properties  # type: ignore[attr-defined]

        # Attach the default manager.
        cls.objects: IRISQuerySet = IRISQuerySet(cls)  # type: ignore[attr-defined]

        return cls


class IRISModel(metaclass=IRISMeta):
    """Base class for all IRIS persistent model classes.

    Subclass this and set ``_iris_classname`` to the fully-qualified IRIS
    class name (e.g. ``"Demo.Test"``).  The metaclass will introspect the
    class and inject typed descriptors automatically.

    Example::

        class Post(IRISModel):
            _iris_classname = "Demo.Post"

        post = Post.get("1")
        post.Title = "Hello"
        post.save()

    CRUD
    ----
    * :meth:`save`      — persists the wrapped IRIS object (``_Save``).
    * :meth:`delete`    — deletes the record (``_DeleteId``).
    * :classmethod:`get`    — opens by ID (``_OpenId``).
    * :classmethod:`create` — creates a new instance (``_New``).
    * ``objects``       — :class:`~iris_orm.query.IRISQuerySet` for queries.
    """

    _iris_classname: str = ""

    def __init__(self) -> None:
        # _iris_obj is set by _open() / create(); None signals an unsaved object.
        object.__setattr__(self, "_iris_obj", None)
        object.__setattr__(self, "_iris_id", None)

    # ------------------------------------------------------------------
    # CRUD helpers
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the wrapped IRIS object.  Raises ``RuntimeError`` on failure."""
        iris_obj = object.__getattribute__(self, "_iris_obj")
        if iris_obj is None:
            raise RuntimeError("Cannot save: no underlying IRIS object (use create() first).")
        status = iris_obj._Save()
        if not status:
            raise RuntimeError(f"_Save() failed with status: {status}")
        # Update stored ID after first save.
        object.__setattr__(self, "_iris_id", str(iris_obj._Id()))

    def delete(self) -> None:
        """Delete this record by ID."""
        iris_id = object.__getattribute__(self, "_iris_id")
        if iris_id is None:
            raise RuntimeError("Cannot delete: object has no ID.")
        import iris  # type: ignore[import]
        iris.cls(self._iris_classname)._DeleteId(iris_id)
        object.__setattr__(self, "_iris_obj", None)
        object.__setattr__(self, "_iris_id", None)

    @property
    def pk(self) -> Optional[str]:
        """The object's IRIS ID, or ``None`` if not yet saved."""
        return object.__getattribute__(self, "_iris_id")  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # class-level constructors
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, obj_id: str) -> Optional["IRISModel"]:
        """Open an existing IRIS object by its ID.

        Returns ``None`` if the ID does not exist.
        """
        return cls._open(str(obj_id))

    @classmethod
    def create(cls, **kwargs: Any) -> "IRISModel":
        """Create a new IRIS object, set properties from *kwargs*, and return
        the unsaved instance.  Call :meth:`save` to persist.
        """
        import iris  # type: ignore[import]

        iris_obj = iris.cls(cls._iris_classname)._New()
        instance = cls.__new__(cls)
        IRISModel.__init__(instance)
        object.__setattr__(instance, "_iris_obj", iris_obj)
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    @classmethod
    def _open(cls, obj_id: str) -> Optional["IRISModel"]:
        """Internal: open by ID, wrapping the IRIS object."""
        import iris  # type: ignore[import]

        try:
            iris_obj = iris.cls(cls._iris_classname)._OpenId(obj_id)
        except Exception:
            return None
        if iris_obj is None:
            return None
        instance = cls.__new__(cls)
        IRISModel.__init__(instance)
        object.__setattr__(instance, "_iris_obj", iris_obj)
        object.__setattr__(instance, "_iris_id", obj_id)
        return instance

    def __repr__(self) -> str:  # pragma: no cover
        iris_id = object.__getattribute__(self, "_iris_id")
        return f"<{self.__class__.__name__} pk={iris_id!r}>"
