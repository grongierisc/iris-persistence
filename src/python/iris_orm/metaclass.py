"""
Metaclass and base model for IRIS ORM.

Two modes:
  Plan A — introspection-first: set _iris_classname; metaclass queries IRIS for properties.
  Plan C — Python-first: write typed annotations + field()/relationship() in the class body.
"""
from __future__ import annotations

import typing
from typing import Any, ClassVar, Optional, get_type_hints

from .descriptors import IRISDescriptor, IRISRelationshipDescriptor, _wrap_iris_obj
from .fields import FieldDefinition, RelationshipDefinition
from .introspection import PropertyInfo, get_class_properties
from .query import IRISQuerySet
from .types import python_type_to_iris, unwrap_optional

# Global registry: IRIS classname → Python model class
_MODEL_REGISTRY: dict[str, type] = {}


def _is_classvar(annotation: Any) -> bool:
    """Return True if the annotation is ClassVar[...] or ClassVar."""
    origin = getattr(annotation, "__origin__", None)
    if origin is ClassVar:
        return True
    # typing.ClassVar before __origin__ support
    if hasattr(typing, "ClassVar") and annotation is ClassVar:
        return True
    str_ann = str(annotation)
    return str_ann.startswith("typing.ClassVar") or str_ann.startswith("ClassVar")


class IRISMeta(type):
    """Metaclass that wires up IRIS descriptors for model classes."""

    def __new__(
        mcs,
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)

        iris_classname: str = namespace.get("_iris_classname", "")
        if not iris_classname:
            # Base class (IRISModel itself) — nothing to wire up.
            return cls

        raw_annotations: dict[str, Any] = namespace.get("__annotations__", {})

        # Detect Python-first mode: user-defined, non-private, non-ClassVar annotations
        # OR FieldDefinition / RelationshipDefinition values in the namespace.
        user_annotations: dict[str, Any] = {
            k: v
            for k, v in raw_annotations.items()
            if not k.startswith("_") and not _is_classvar(v)
        }
        has_field_defs = any(
            isinstance(v, (FieldDefinition, RelationshipDefinition))
            for v in namespace.values()
        )
        python_first = bool(user_annotations or has_field_defs)

        if python_first:
            mcs._setup_python_first(cls, iris_classname, namespace, user_annotations)
        else:
            mcs._setup_plan_a(cls, iris_classname, namespace)

        _MODEL_REGISTRY[iris_classname] = cls
        cls.objects = IRISQuerySet(cls)  # type: ignore[attr-defined]
        return cls

    # ------------------------------------------------------------------
    @staticmethod
    def _setup_python_first(
        cls: type,
        iris_classname: str,
        namespace: dict[str, Any],
        user_annotations: dict[str, Any],
    ) -> None:
        iris_properties: list[PropertyInfo] = []
        iris_field_defs: dict[str, FieldDefinition] = {}
        iris_rel_defs: dict[str, RelationshipDefinition] = {}

        # Resolve annotations with forward-ref support where possible.
        try:
            resolved = get_type_hints(cls)
        except Exception:
            resolved = dict(user_annotations)

        for attr_name, raw_type in user_annotations.items():
            # Skip relationship annotations handled below.
            namespace_val = namespace.get(attr_name)
            if isinstance(namespace_val, RelationshipDefinition):
                continue

            # Unwrap Optional[T] → T for type resolution.
            resolved_type = resolved.get(attr_name, raw_type)
            inner_type = unwrap_optional(resolved_type)

            # Get or create FieldDefinition.
            if isinstance(namespace_val, FieldDefinition):
                fd = namespace_val
            else:
                fd = FieldDefinition()

            fd.prop_name = attr_name
            fd.python_type = inner_type

            # Determine IRIS type.
            iris_type = fd.iris_type or python_type_to_iris(inner_type)
            fd.iris_type = iris_type

            prop_info = PropertyInfo(
                name=attr_name,
                iris_type=iris_type,
                python_type=inner_type,
                required=fd.required,
                collection=fd.collection,
                default="" if fd.default is None else str(fd.default),
            )
            iris_properties.append(prop_info)
            iris_field_defs[attr_name] = fd

            # Inject descriptor (don't overwrite explicitly defined methods/properties).
            if attr_name not in namespace or isinstance(namespace[attr_name], FieldDefinition):
                descriptor = IRISDescriptor(attr_name, inner_type, fd.required)
                descriptor.attr_name = attr_name
                setattr(cls, attr_name, descriptor)

            # Ensure annotation is Optional[T].
            if not hasattr(cls, "__annotations__"):
                cls.__annotations__ = {}
            cls.__annotations__[attr_name] = Optional[inner_type]  # type: ignore[valid-type]

        # Process RelationshipDefinitions.
        for attr_name, val in namespace.items():
            if not isinstance(val, RelationshipDefinition):
                continue
            rd: RelationshipDefinition = val
            rd.prop_name = attr_name
            iris_rel_defs[attr_name] = rd

            descriptor = IRISRelationshipDescriptor(
                prop_name=attr_name,
                related_classname=rd.related_classname,
                cardinality=rd.cardinality,
                inverse=rd.inverse,
            )
            descriptor.attr_name = attr_name
            setattr(cls, attr_name, descriptor)

        cls._iris_properties = iris_properties  # type: ignore[attr-defined]
        cls._iris_field_defs = iris_field_defs  # type: ignore[attr-defined]
        cls._iris_rel_defs = iris_rel_defs  # type: ignore[attr-defined]
        cls._iris_python_first = True  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    @staticmethod
    def _setup_plan_a(
        cls: type,
        iris_classname: str,
        namespace: dict[str, Any],
    ) -> None:
        try:
            props = get_class_properties(iris_classname)
        except Exception:
            props = []

        if not hasattr(cls, "__annotations__"):
            cls.__annotations__ = {}

        for prop in props:
            attr_name = prop.name
            # Don't overwrite user-defined attributes.
            if attr_name in namespace:
                continue
            descriptor = IRISDescriptor(attr_name, prop.python_type, prop.required)
            descriptor.attr_name = attr_name
            setattr(cls, attr_name, descriptor)
            cls.__annotations__[attr_name] = Optional[prop.python_type]  # type: ignore[valid-type]

        cls._iris_properties = props  # type: ignore[attr-defined]
        cls._iris_field_defs = {}  # type: ignore[attr-defined]
        cls._iris_rel_defs = {}  # type: ignore[attr-defined]
        cls._iris_python_first = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Base model
# ---------------------------------------------------------------------------

class IRISModel(metaclass=IRISMeta):
    """Base class for all IRIS ORM models."""

    _iris_classname: ClassVar[str] = ""

    # Set by metaclass:
    _iris_properties: ClassVar[list[PropertyInfo]]
    _iris_field_defs: ClassVar[dict[str, FieldDefinition]]
    _iris_rel_defs: ClassVar[dict[str, RelationshipDefinition]]
    _iris_python_first: ClassVar[bool]
    objects: ClassVar[IRISQuerySet]

    def __init__(self, **kwargs: Any) -> None:
        object.__setattr__(self, "_iris_id", None)
        classname = type(self)._iris_classname
        iris_obj = None
        if classname:
            import iris  # noqa: PLC0415
            iris_obj = iris.cls(classname)._New()
        object.__setattr__(self, "_iris_obj", iris_obj)
        for key, value in kwargs.items():
            setattr(self, key, value)

    # ------------------------------------------------------------------
    # Attribute fallthrough to underlying IRIS object
    #
    # These two methods make Plan A binding resilient: if introspection
    # failed at class-definition time (no IRIS connection yet) and no
    # typed descriptors were injected, attribute access is still forwarded
    # directly to the wrapped IRIS object.  When a typed descriptor *is*
    # present on the class, Python resolves it first (data-descriptor
    # protocol) and neither of these methods is ever called for that name.
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attribute reads to the underlying IRIS object."""
        # __getattr__ is only called when normal lookup (including descriptors)
        # has already failed — so this is the fallback, not the fast path.
        if name.startswith("_"):
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        try:
            iris_obj = object.__getattribute__(self, "_iris_obj")
        except AttributeError:
            raise AttributeError(f"{type(self).__name__!r} has no attribute {name!r}")
        if iris_obj is None:
            raise AttributeError(
                f"{type(self).__name__!r} has no attribute {name!r} "
                "(no underlying IRIS object; use create() or get() first)"
            )
        return getattr(iris_obj, name)

    def __setattr__(self, name: str, value: Any) -> None:
        """Forward unknown attribute writes to the underlying IRIS object."""
        # Check for a data descriptor on the class (or its MRO).
        for klass in type(self).__mro__:
            if name in klass.__dict__:
                descriptor = klass.__dict__[name]
                if hasattr(descriptor, "__set__"):
                    descriptor.__set__(self, value)
                    return
                break  # found the name but it's not a data descriptor
        # No descriptor — forward to iris_obj if available, else instance dict.
        if not name.startswith("_"):
            try:
                iris_obj = object.__getattribute__(self, "_iris_obj")
                if iris_obj is not None:
                    setattr(iris_obj, name, value)
                    return
            except AttributeError:
                pass
        object.__setattr__(self, name, value)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist the instance to IRIS. Raises RuntimeError on failure."""
        iris_obj = object.__getattribute__(self, "_iris_obj")
        if iris_obj is None:
            raise RuntimeError(
                "No underlying IRIS object. Use MyModel.create() to obtain a new instance."
            )
        status = iris_obj._Save()
        # IRIS status: 1 = success; $$$OK also evaluates to 1.
        if not status:
            raise RuntimeError(f"_Save() failed with status: {status!r}")
        try:
            object.__setattr__(self, "_iris_id", str(iris_obj._Id()))
        except Exception:
            pass

    def delete(self) -> None:
        """Delete the instance from IRIS. Raises RuntimeError if not saved."""
        obj_id = object.__getattribute__(self, "_iris_id")
        if not obj_id:
            raise RuntimeError("Cannot delete: object has no ID (not yet saved).")
        import iris  # noqa: PLC0415
        iris.cls(self._iris_classname)._DeleteId(obj_id)
        object.__setattr__(self, "_iris_obj", None)
        object.__setattr__(self, "_iris_id", None)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pk(self) -> Optional[str]:
        return object.__getattribute__(self, "_iris_id")

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, obj_id: Any) -> Optional["IRISModel"]:
        """Open an existing IRIS object by ID. Returns None if not found."""
        return cls._open(str(obj_id))

    @classmethod
    def create(cls, **kwargs: Any) -> "IRISModel":
        """
        Create a new (unsaved) instance backed by a fresh IRIS object.
        Call .save() to persist.
        """
        import iris  # noqa: PLC0415
        iris_obj = iris.cls(cls._iris_classname)._New()
        instance = _wrap_iris_obj(cls, iris_obj)
        for key, value in kwargs.items():
            setattr(instance, key, value)
        return instance

    @classmethod
    def _open(cls, obj_id: str) -> Optional["IRISModel"]:
        """Open an existing IRIS object by ID. Returns None if not found."""
        try:
            import iris  # noqa: PLC0415
            iris_obj = iris.cls(cls._iris_classname)._OpenId(obj_id)
            if iris_obj is None:
                return None
            return _wrap_iris_obj(cls, iris_obj)
        except Exception:
            return None

    @classmethod
    def bind(cls) -> None:
        """Re-run Plan A introspection against a live IRIS connection.

        Call this after connecting to IRIS when the class was defined before
        a connection was available (e.g. at module import time)::

            class Post(IRISModel):
                _iris_classname = "Demo.Post"

            # ... later, after connecting:
            Post.bind()  # injects typed descriptors from %Dictionary.PropertyDefinition
        """
        if getattr(cls, "_iris_python_first", False):
            raise RuntimeError(
                f"{cls.__name__} was defined in Python-first (Plan C) mode. "
                "bind() is only needed for Plan A (introspection-first) classes."
            )
        IRISMeta._setup_plan_a(cls, cls._iris_classname, {})
