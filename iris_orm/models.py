from __future__ import annotations

import keyword
from inspect import Parameter, Signature
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    get_args,
    get_origin,
    get_type_hints,
)

from iris_orm.codecs import resolve_declared_type
from iris_orm.types import ClassMetadata
from iris_orm.types import Field
from iris_orm.types import FieldInfo, Index, ModelField, UNSET

# Types that need no coercion before being passed to set_property.
_PRIMITIVE_TYPES: frozenset[type] = frozenset({str, int, float, bool})

if TYPE_CHECKING:
    from iris_orm.query import QuerySet

T = TypeVar("T", bound="Model")


class _FactoryDefault:
    def __repr__(self) -> str:
        return "<factory>"


FACTORY_DEFAULT = _FactoryDefault()
RESERVED_FIELD_NAMES = frozenset({"pk", "_pk", "_iris_obj"})


def _is_empty_class_metadata(metadata: ClassMetadata | None) -> bool:
    if metadata is None:
        return True
    return (
        metadata.description is None
        and not metadata.deprecated
        and not metadata.final
        and metadata.sql_table_name is None
        and not metadata.procedure_block
    )


def _parse_class_metadata(meta_inner: Any) -> ClassMetadata | None:
    if meta_inner is None:
        return None

    metadata = getattr(meta_inner, "metadata", None)
    if metadata is None:
        metadata = ClassMetadata(
            description=getattr(meta_inner, "description", None),
            deprecated=getattr(meta_inner, "deprecated", False),
            final=getattr(meta_inner, "final", False),
            sql_table_name=getattr(meta_inner, "sql_table_name", None),
            procedure_block=getattr(meta_inner, "procedure_block", False),
        )

    return None if _is_empty_class_metadata(metadata) else metadata


def _extract_annotation_field(hint: Any) -> tuple[Any, FieldInfo | None]:
    origin = get_origin(hint)
    if origin is not Annotated:
        return (hint, None)

    args = get_args(hint)
    metadata = [item for item in args[1:] if isinstance(item, FieldInfo)]
    if len(metadata) > 1:
        raise TypeError("A field annotation may include at most one Field(...) metadata object")
    return (args[0], metadata[0] if metadata else None)


def _normalize_superclasses(value: Any) -> str:
    if value is None:
        return "%Persistent"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _is_optional_type(hint: Any) -> bool:
    origin = get_origin(hint)
    if origin is None:
        return False
    return type(None) in get_args(hint)


def _build_model_field(
    field_name: str,
    hint: Any,
    assigned_value: Any,
    assigned_field: FieldInfo | Any,
) -> ModelField:
    declared_type, annotation_field = _extract_annotation_field(hint)
    if isinstance(assigned_field, FieldInfo) and annotation_field is not None:
        raise TypeError(
            f"Field '{field_name}' cannot declare Field(...) in both Annotated metadata and "
            "a class assignment"
        )

    if isinstance(assigned_field, FieldInfo):
        field_info = assigned_field
    elif annotation_field is not None:
        field_info = annotation_field
    else:
        field_info = FieldInfo()

    field_info = FieldInfo(**field_info.__dict__)

    if assigned_value is not UNSET:
        if field_info.default_factory is not UNSET:
            raise TypeError(
                f"Field '{field_name}' cannot define both default_factory and a class default"
            )
        field_info.default = assigned_value

    resolved_type = resolve_declared_type(declared_type)
    nullable = field_info.nullable
    if nullable is None:
        nullable = (
            _is_optional_type(declared_type)
            or field_info.default is None
            or not field_info.required
        )

    from iris_orm.query import (
        _is_model_type,
        _is_percent_list_field,
        _is_scalar_string_field,
        _collection_value_type,
    )
    is_percent_list = _is_percent_list_field(field_info)
    is_scalar_string = _is_scalar_string_field(field_info)
    collection_kind, element_type = _collection_value_type(resolved_type)
    is_model_field = _is_model_type(resolved_type)

    return ModelField(
        name=field_name,
        declared_type=resolved_type,
        field_info=field_info,
        required=field_info.required,
        nullable=bool(nullable),
        sql_field_name=field_info.sql_field_name,
        _is_percent_list=is_percent_list,
        _is_scalar_string=is_scalar_string,
        _collection_kind=collection_kind,
        _element_type=element_type,
        _is_model_field=is_model_field,
    )


def _build_signature(model_fields: Dict[str, ModelField]) -> Signature:
    parameters = []
    for model_field in model_fields.values():
        default = Parameter.empty
        if model_field.default_factory is not UNSET:
            default = FACTORY_DEFAULT
        elif model_field.default is not UNSET:
            default = model_field.default
        elif not model_field.required:
            default = None
        parameters.append(
            Parameter(
                model_field.name,
                kind=Parameter.KEYWORD_ONLY,
                default=default,
                annotation=model_field.declared_type,
            )
        )
    return Signature(parameters=parameters)


def _build_generated_init(model_fields: Dict[str, ModelField]) -> Any | None:
    if any(not name.isidentifier() or keyword.iskeyword(name) for name in model_fields):
        return None

    params = ["self"]
    if model_fields:
        params.append("*")
    body = ["    provided_values = {}"]
    for model_field in model_fields.values():
        if model_field.required:
            params.append(model_field.name)
        else:
            params.append(f"{model_field.name}=UNSET")
        body.append(f"    provided_values[{model_field.name!r}] = {model_field.name}")
    body.append("    self._initialize_model_state(provided_values)")

    source = "def __init__(" + ", ".join(params) + "):\n" + "\n".join(body)
    namespace = {"UNSET": UNSET}
    exec(source, namespace)
    return namespace["__init__"]


def _build_fast_init(model_fields: Dict[str, ModelField]) -> Any | None:
    """Generate an optimised __init__ for models with validate_on_init=False.

    Bypasses _initialize_model_state entirely: just sets _pk/_iris_obj to None
    and assigns each field directly into self.__dict__, eliminating the field
    loop, the intermediate provided_values dict, and all setattr dispatch.
    """
    if any(not name.isidentifier() or keyword.iskeyword(name) for name in model_fields):
        return None

    params = ["self"]
    if model_fields:
        params.append("*")

    body = [
        "    self._pk = None",
        "    self._iris_obj = None",
    ]
    if model_fields:
        body.append("    d = self.__dict__")

    namespace: dict[str, Any] = {"UNSET": UNSET}
    for i, (name, mf) in enumerate(model_fields.items()):
        if mf.required:
            params.append(name)
            body.append(f"    d[{name!r}] = {name}")
        elif mf.field_info.default_factory is not UNSET:
            factory_var = f"_dfact_{i}"
            namespace[factory_var] = mf.field_info.default_factory
            params.append(f"{name}=UNSET")
            body.append(f"    d[{name!r}] = {name} if {name} is not UNSET else {factory_var}()")
        elif mf.field_info.default is not UNSET:
            default_var = f"_dval_{i}"
            namespace[default_var] = mf.field_info.default
            params.append(f"{name}=UNSET")
            body.append(f"    d[{name!r}] = {name} if {name} is not UNSET else {default_var}")
        else:
            params.append(f"{name}=UNSET")
            body.append(f"    if {name} is not UNSET: d[{name!r}] = {name}")

    source = "def __init__(" + ", ".join(params) + "):\n" + "\n".join(body)
    exec(source, namespace)
    return namespace["__init__"]


def _build_fast_load(model_cls: Any, model_fields: Dict[str, ModelField], is_serial: bool) -> Any:
    """Generate a per-class _fast_load using direct attribute access (LOAD_ATTR bytecode).

    IRIS objects have a 2-3× penalty when property access goes through Python's getattr()
    built-in vs a compiled `obj.Name` LOAD_ATTR instruction.  Code-gen lets us produce:

        d['Name'] = iris_obj.Name          # fast  (LOAD_ATTR)

    instead of what the generic loop does:

        getattr(iris_obj, 'Name', None)    # slow (getattr builtin)

    Returns None for models with complex fields (collections, related models) or non-standard
    scalar types (datetime, bytes, …) so those fall back to the generic path.
    """
    # Field names must be valid Python identifiers (no special chars like %)
    if any(not name.isidentifier() or keyword.iskeyword(name) for name in model_fields):
        return None

    lines = [
        "def _fast_load(iris_obj, known_pk=None):",
        "    if iris_obj is None: return None",
        "    instance = _model_cls.__new__(_model_cls)",
        "    d = instance.__dict__",
        "    d['_iris_obj'] = iris_obj",
    ]

    if is_serial:
        lines.append("    d['_pk'] = None")
    else:
        # known_pk is provided on the hot path (get(pk)).
        # For related model loading (known_pk=None), fall back to get_object_id.
        lines.append("    if known_pk is not None:")
        lines.append("        d['_pk'] = known_pk")
        lines.append("    else:")
        lines.append("        _oid = _get_runtime().get_object_id(iris_obj)")
        lines.append("        d['_pk'] = str(_oid) if _oid else None")

    for name, mf in model_fields.items():
        if mf._is_percent_list or mf._collection_kind is not None or mf._is_model_field:
            return None  # complex field — cannot use this fast path
        if mf.declared_type is str:
            lines.append(
                f"    _v = iris_obj.{name}; "
                f"d[{name!r}] = None if _v == _NULL_STRING else (_v if _v else '')"
            )
        elif mf.declared_type is bool:
            lines.append(f"    d[{name!r}] = bool(iris_obj.{name} or 0)")
        elif mf.declared_type in (int, float):
            lines.append(f"    d[{name!r}] = iris_obj.{name}")
        else:
            return None  # datetime, bytes, or other type needing coercion

    lines.append("    return instance")
    source = "\n".join(lines)
    from iris_orm.runtime import get_runtime as _get_runtime_fn
    namespace: dict[str, Any] = {
        "_model_cls": model_cls,
        "_get_runtime": _get_runtime_fn,
        "_NULL_STRING": chr(0),
    }
    exec(source, namespace)
    fn = namespace["_fast_load"]
    fn.__qualname__ = f"{model_cls.__qualname__}._fast_load"
    return fn


def _build_fast_save(model_cls: Any, model_fields: Dict[str, ModelField], scalar_fast_fields: list) -> Any:
    """Generate a per-class _fast_save using direct attribute assignment (STORE_ATTR bytecode).

    Like _build_fast_load, this avoids the overhead of calling set_property() per field
    (a Python function call + isinstance(val, bool) check each time) by emitting direct
    `iris_obj.Field = val` assignments via code-gen.

    Only generated for models where all writable fields are primitive scalars with no
    coercion or complex fields (collections, related models).  Falls back to the generic
    loop in save_model for all other models.
    """
    if not scalar_fast_fields:
        return None
    # Field names must be valid Python identifiers
    if any(not name.isidentifier() or keyword.iskeyword(name) for name in scalar_fast_fields):
        return None

    lines = ["def _fast_save(iris_obj, inst_dict):"]
    for name in scalar_fast_fields:
        mf = model_fields[name]
        if mf.declared_type is str:
            lines.append(f"    if {name!r} in inst_dict:")
            lines.append(f"        _v = inst_dict.get({name!r})")
            lines.append(f"        iris_obj.{name} = _NULL_STRING if _v is None else _v")
        elif mf.declared_type is bool:
            lines.append(f"    _v = inst_dict.get({name!r})")
            lines.append(f"    if _v is not None: iris_obj.{name} = 1 if _v else 0")
        else:
            lines.append(f"    _v = inst_dict.get({name!r})")
            lines.append(f"    if _v is not None: iris_obj.{name} = _v")

    source = "\n".join(lines)
    namespace: dict[str, Any] = {"_NULL_STRING": chr(0)}
    exec(source, namespace)
    fn = namespace["_fast_save"]
    fn.__qualname__ = f"{model_cls.__qualname__}._fast_save"
    return fn


def _type_name(value: Any) -> str:
    return getattr(value, "__name__", repr(value))


def _value_matches_declared_type(declared_type: Any, value: Any) -> bool:
    origin = get_origin(declared_type)
    if declared_type is Any:
        return True
    if origin is None:
        if isinstance(declared_type, type):
            if declared_type is float and isinstance(value, (int, float)) and not isinstance(value, bool):
                return True
            if declared_type is int and isinstance(value, bool):
                return False
            return isinstance(value, declared_type)
        return True
    if origin in (list, List):
        if not isinstance(value, list):
            return False
        args = get_args(declared_type)
        if not args:
            return True
        return all(_value_matches_declared_type(args[0], item) for item in value)
    if origin in (dict, Dict):
        if not isinstance(value, dict):
            return False
        args = get_args(declared_type)
        if len(args) != 2:
            return True
        key_type, value_type = args
        return all(
            _value_matches_declared_type(key_type, key)
            and _value_matches_declared_type(value_type, item)
            for key, item in value.items()
        )
    args = [arg for arg in get_args(declared_type) if arg is not type(None)]
    if args:
        return any(_value_matches_declared_type(arg, value) for arg in args)
    return True


def _validate_field_value(model_field: ModelField, value: Any) -> Any:
    if value is None:
        if model_field.nullable or model_field.default is None:
            return value
        raise ValueError(f"Field '{model_field.name}' does not allow null values")

    max_length = model_field.field_info.max_length
    if max_length is not None and hasattr(value, "__len__") and len(value) > max_length:
        raise ValueError(
            f"Field '{model_field.name}' exceeds max_length={max_length}: {len(value)}"
        )

    if not _value_matches_declared_type(model_field.declared_type, value):
        raise TypeError(
            f"Field '{model_field.name}' expected {_type_name(model_field.declared_type)}, "
            f"got {type(value).__name__}"
        )

    return value


def _split_index_properties(properties: str) -> list[str]:
    return [item.strip() for item in properties.split(",") if item.strip()]


def _field_requires_index(field_info: FieldInfo) -> bool:
    return bool(field_info.index or field_info.unique or field_info.primary_key)


def _synthesize_indexes(
    model_name: str,
    model_fields: Dict[str, ModelField],
    declared_indexes: list[Index],
) -> list[Index]:
    indexes = list(declared_indexes)
    indexed_fields: dict[str, list[Index]] = {}
    used_names = set()

    for index in indexes:
        used_names.add(index.name)
        for field_name in _split_index_properties(index.properties):
            indexed_fields.setdefault(field_name, []).append(index)

    synthesized: list[Index] = []
    for field_name, model_field in model_fields.items():
        field_info = model_field.field_info
        if not _field_requires_index(field_info):
            continue

        if field_name in indexed_fields:
            existing = ", ".join(sorted(index.name for index in indexed_fields[field_name]))
            raise TypeError(
                f"Field '{field_name}' on model {model_name} declares index metadata, "
                f"but Meta.indexes already defines index(es): {existing}"
            )

        index_name = field_info.index_name or f"{field_name}Idx"
        if index_name in used_names:
            raise TypeError(
                f"Field '{field_name}' on model {model_name} generated duplicate index name "
                f"'{index_name}'"
            )

        synthesized.append(
            Index(
                index_name,
                properties=field_name,
                unique=bool(field_info.unique or field_info.primary_key),
                primary_key=field_info.primary_key,
                type=field_info.index_type,
            )
        )
        used_names.add(index_name)

    return indexes + synthesized


class ModelMeta(type):
    def __new__(mcs, name: str, bases: tuple, namespace: dict, **kwargs: Any):
        namespace_copy = dict(namespace)
        annotations = namespace.get("__annotations__", {})
        reserved = sorted(field_name for field_name in annotations if field_name in RESERVED_FIELD_NAMES)
        if reserved:
            reserved_fields = ", ".join(reserved)
            raise TypeError(
                f"Model {name} uses reserved field name(s): {reserved_fields}"
            )
        declared_field_assignments = {}
        for field_name in annotations:
            value = namespace.get(field_name, UNSET)
            if isinstance(value, FieldInfo):
                declared_field_assignments[field_name] = value
                namespace_copy.pop(field_name, None)

        namespace_copy["_declared_field_assignments__"] = declared_field_assignments
        namespace_copy["_declared_model_options__"] = dict(kwargs)
        return super().__new__(mcs, name, bases, namespace_copy)

    def __init__(cls, name: str, bases: tuple, namespace: dict, **kwargs: Any):
        super().__init__(name, bases, namespace)
        if name == "Model":
            return

        model_fields: dict[str, ModelField] = {}
        for base in reversed(cls.__mro__[1:]):
            model_fields.update(getattr(base, "__model_fields__", {}))

        try:
            hints = get_type_hints(cls, include_extras=True)
        except Exception:
            hints = {}

        declared_field_assignments = getattr(cls, "_declared_field_assignments__", {})
        annotations = namespace.get("__annotations__", {})
        for field_name in annotations:
            if field_name.startswith("_"):
                continue
            raw_default = namespace.get(field_name, UNSET)
            if isinstance(raw_default, FieldInfo):
                raw_default = UNSET
            model_fields[field_name] = _build_model_field(
                field_name,
                hints.get(field_name, Any),
                raw_default,
                declared_field_assignments.get(field_name, UNSET),
            )

        setattr(cls, "__model_fields__", model_fields)
        setattr(cls, "_fields", {name: model_field.field_info for name, model_field in model_fields.items()})
        generated_init = _build_generated_init(model_fields)
        if generated_init is not None:
            generated_init.__qualname__ = f"{cls.__qualname__}.__init__"
            setattr(cls, "__init__", generated_init)
        setattr(cls, "__signature__", _build_signature(model_fields))
        if hasattr(cls, "_declared_field_assignments__"):
            delattr(cls, "_declared_field_assignments__")

        # Parse inner Meta class
        meta_inner = namespace.get("Meta", None)
        declared_model_options = getattr(cls, "_declared_model_options__", {})
        if hasattr(cls, "_declared_model_options__"):
            delattr(cls, "_declared_model_options__")
        declared_superclasses = declared_model_options.get("superclasses")
        persistent = bool(declared_model_options.get("persistent", False))
        serial = bool(declared_model_options.get("serial", False))
        if persistent and serial and declared_superclasses is None and getattr(meta_inner, "superclasses", None) is None:
            raise TypeError("Model cannot declare both persistent=True and serial=True")
        if getattr(meta_inner, "superclasses", None) is not None:
            superclasses = meta_inner.superclasses
        elif declared_superclasses is not None:
            superclasses = declared_superclasses
        elif serial:
            superclasses = "%SerialObject"
        elif persistent:
            superclasses = "%Persistent"
        else:
            superclasses = "%Persistent"
        setattr(cls, "_classname", getattr(meta_inner, "classname", name))
        setattr(cls, "_sync_mode", getattr(meta_inner, "mode", "extend"))
        setattr(cls, "_auto_sync", getattr(meta_inner, "auto_sync", False))
        setattr(cls, "_validate_on_init", getattr(meta_inner, "validate_on_init", True))
        if not cls._validate_on_init:
            fast_init = _build_fast_init(model_fields)
            if fast_init is not None:
                fast_init.__qualname__ = f"{cls.__qualname__}.__init__"
                setattr(cls, "__init__", fast_init)
        setattr(cls, "_superclasses", _normalize_superclasses(superclasses))
        setattr(cls, "_class_metadata", _parse_class_metadata(meta_inner))
        setattr(cls, "_storage", getattr(meta_inner, "storage", None))
        declared_indexes = list(getattr(meta_inner, "indexes", []))
        setattr(cls, "_indexes", _synthesize_indexes(cls.__name__, model_fields, declared_indexes))
        setattr(cls, "_parameters", getattr(meta_inner, "parameters", {}))

        # Pre-compute three save field lists used by save_model for faster writes.
        # _scalar_fast_fields  : primitive (str/int/float/bool) fields — direct set_property, no coerce
        # _scalar_coerce_fields: other scalar non-model fields (e.g. datetime) — coerce then inject
        # _complex_save_fields : collections, related models, readonly fields — full path
        _scalar_fast: list[str] = []
        _scalar_coerce: list[tuple[str, Any]] = []
        _complex_save: list[tuple[str, ModelField]] = []
        for _fname, _mf in model_fields.items():
            if getattr(_mf.field_info, "readonly", False):
                _complex_save.append((_fname, _mf))
            elif _mf._collection_kind is None and not _mf._is_model_field:
                if _mf.declared_type in _PRIMITIVE_TYPES:
                    _scalar_fast.append(_fname)
                else:
                    _scalar_coerce.append((_fname, _mf.declared_type))
            else:
                _complex_save.append((_fname, _mf))
        setattr(cls, "_scalar_fast_fields", _scalar_fast)
        setattr(cls, "_scalar_coerce_fields", _scalar_coerce)
        setattr(cls, "_complex_save_fields", _complex_save)

        # Pre-compute four read field lists used by _build_model_from_iris_obj for faster reads.
        # _read_str_fields      : str fields — getattr direct, normalise None/0 → ""
        # _read_primitive_fields: int/float fields — getattr direct, no coercion
        # _read_bool_fields     : bool fields — bool(int_val or 0) from IRIS 0/1
        # _read_coerce_fields   : other scalar fields (e.g. datetime) — full coerce_value_for_load
        # _read_complex_fields  : percent_list, collections, related models — full runtime path
        _read_str: list[str] = []
        _read_prim: list[str] = []
        _read_bool: list[str] = []
        _read_coerce: list[tuple[str, Any]] = []
        _read_complex: list[tuple[str, ModelField]] = []
        for _fname, _mf in model_fields.items():
            if _mf._is_percent_list or _mf._collection_kind is not None or _mf._is_model_field:
                _read_complex.append((_fname, _mf))
            elif _mf.declared_type is bool:
                _read_bool.append(_fname)
            elif _mf.declared_type is str:
                _read_str.append(_fname)
            elif _mf.declared_type in (int, float):
                _read_prim.append(_fname)
            else:
                _read_coerce.append((_fname, _mf.declared_type))
        setattr(cls, "_read_str_fields", _read_str)
        setattr(cls, "_read_primitive_fields", _read_prim)
        setattr(cls, "_read_bool_fields", _read_bool)
        setattr(cls, "_read_coerce_fields", _read_coerce)
        setattr(cls, "_read_complex_fields", _read_complex)
        # Pre-compute serial-class flag to avoid re-checking per _build_model_from_iris_obj call.
        _superclasses_str = _normalize_superclasses(superclasses) or ""
        _is_serial = "SerialObject" in _superclasses_str
        setattr(cls, "_is_serial_class", _is_serial)

        # Generate per-class _fast_load if possible (only str/int/float/bool scalar fields).
        # None means fall back to the generic _build_model_from_iris_obj loop.
        _fast_load_fn = None
        if not _read_coerce and not _read_complex:
            _fast_load_fn = _build_fast_load(cls, model_fields, _is_serial)
        setattr(cls, "_fast_load", _fast_load_fn)

        # Generate per-class _fast_save if possible (only primitive scalar fields, no coerce/complex).
        # None means fall back to the generic set_property loop in save_model.
        _fast_save_fn = None
        if not _scalar_coerce and not _complex_save:
            _fast_save_fn = _build_fast_save(cls, model_fields, _scalar_fast)
        setattr(cls, "_fast_save", _fast_save_fn)

        # Placeholder for the lazily-cached _New bound method (set on first save).
        setattr(cls, "_fast_new", None)


class Model(metaclass=ModelMeta):
    __model_fields__: dict[str, ModelField]
    _fields: dict[str, FieldInfo]
    _classname: str
    _sync_mode: str
    _auto_sync: bool
    _validate_on_init: bool
    _class_metadata: ClassMetadata | None
    _scalar_fast_fields: list[str]
    _scalar_coerce_fields: list[tuple[str, Any]]
    _complex_save_fields: list[tuple[str, ModelField]]
    _read_str_fields: list[str]
    _read_primitive_fields: list[str]
    _read_bool_fields: list[str]
    _read_coerce_fields: list[tuple[str, Any]]
    _read_complex_fields: list[tuple[str, ModelField]]
    _is_serial_class: bool
    _fast_load: Any  # per-class code-gen loader, or None for generic path
    _fast_save: Any  # per-class code-gen field setter, or None for generic path
    _fast_new: Any  # cached _New bound method, lazily set on first save

    @classmethod
    def __init_subclass__(
        cls,
        *,
        persistent: bool = False,
        serial: bool = False,
        superclasses: Any = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__()

    def _initialize_model_state(self, provided_values: dict[str, Any]) -> None:
        self._pk: Optional[str] = None
        self._iris_obj: Any = None

        unknown = [name for name in provided_values if name not in self.__class__.__model_fields__]
        if unknown:
            unknown_fields = ", ".join(sorted(unknown))
            raise TypeError(f"Unknown field(s) for model {self.__class__.__name__}: {unknown_fields}")

        for name, model_field in self.__class__.__model_fields__.items():
            value = provided_values.get(name, UNSET)
            if value is UNSET:
                value = model_field.get_default_value()
                if value is UNSET:
                    if model_field.required:
                        raise TypeError(
                            f"Missing required field '{name}' for model {self.__class__.__name__}"
                        )
                    continue
            if self.__class__._validate_on_init:
                setattr(self, name, _validate_field_value(model_field, value))
            else:
                setattr(self, name, value)

    def __init__(self, **kwargs):
        self._initialize_model_state(kwargs)

    @classmethod
    def _from_loaded_values(cls: Type[T], values: dict[str, Any]) -> T:
        instance = cls.__new__(cls)
        instance._pk = None
        instance._iris_obj = None
        for name, value in values.items():
            setattr(instance, name, value)
        return instance

    def __repr__(self) -> str:
        fields = [f"pk={repr(self.pk)}"]
        for name in self.__class__.__model_fields__:
            if hasattr(self, name):
                fields.append(f"{name}={repr(getattr(self, name))}")
        return f"<{self.__class__.__name__} {', '.join(fields)}>"

    @property
    def pk(self) -> Optional[str]:
        return self._pk

    def save(self) -> None:
        from iris_orm.query import save_model

        save_model(self)

    @classmethod
    def sync_schema(cls, *, dry_run: bool = False):
        from iris_orm.schema import diff_schema as schema_diff
        from iris_orm.schema import sync_schema as schema_sync

        if dry_run:
            return schema_diff(cls)
        schema_sync(cls)
        return None

    @classmethod
    def diff_schema(cls):
        from iris_orm.schema import diff_schema as schema_diff

        return schema_diff(cls)

    @classmethod
    def get(cls: Type[T], pk: str) -> Optional[T]:
        from iris_orm.query import get_model

        return get_model(cls, pk)

    @classmethod
    def all(cls: Type[T]) -> List[T]:
        from iris_orm.query import QuerySet

        return QuerySet(cls).all()

    @classmethod
    def where(cls: Type[T], **kwargs) -> "QuerySet[T]":
        from iris_orm.query import QuerySet

        return QuerySet(cls).where(**kwargs)

    def _validate_for_save(self) -> None:
        for name, model_field in self.__class__.__model_fields__.items():
            if hasattr(self, name):
                _validate_field_value(model_field, getattr(self, name))
            elif model_field.required:
                raise ValueError(f"Field '{name}' is required")


IRISModel = Model
