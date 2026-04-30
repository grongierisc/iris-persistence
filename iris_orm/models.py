from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Type, TypeVar, get_type_hints

from iris_orm.types import ClassMetadata
from iris_orm.types import Field

if TYPE_CHECKING:
    from iris_orm.query import QuerySet

T = TypeVar("T", bound="IRISModel")


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

    IRIS objects have a 2-3x penalty when property access goes through Python's getattr()
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

        # Don't parse base classes
        if name == "IRISModel":
            return cls

        # We must resolve annotations after class creation because we need the class object
        return cls

    def __init__(cls, name: str, bases: tuple, namespace: dict):
        super().__init__(name, bases, namespace)
        if name == "IRISModel":
            return

        fields: dict[str, Field] = {}
        try:
            hints = get_type_hints(cls, include_extras=True)
            for field_name, hint in hints.items():
                if field_name.startswith("_"):
                    continue
                found_field = False
                if hasattr(hint, "__metadata__"):
                    for meta in hint.__metadata__:
                        if isinstance(meta, Field):
                            fields[field_name] = meta
                            found_field = True
                            break
                if not found_field:
                    fields[field_name] = Field()
        except Exception:
            pass

        setattr(cls, "_fields", fields)

        # Parse inner Meta class
        meta_inner = namespace.get("Meta", None)
        setattr(cls, "_classname", getattr(meta_inner, "classname", name))
        setattr(cls, "_sync_mode", getattr(meta_inner, "mode", "extend"))
        setattr(cls, "_auto_sync", getattr(meta_inner, "auto_sync", False))
        setattr(cls, "_superclasses", getattr(meta_inner, "superclasses", "%Persistent"))
        setattr(cls, "_class_metadata", _parse_class_metadata(meta_inner))
        setattr(cls, "_storage", getattr(meta_inner, "storage", None))
        setattr(cls, "_indexes", getattr(meta_inner, "indexes", []))
        setattr(cls, "_parameters", getattr(meta_inner, "parameters", {}))


class IRISModel(metaclass=ModelMeta):
    _fields: dict[str, Field]
    _classname: str
    _sync_mode: str
    _auto_sync: bool
    _class_metadata: ClassMetadata | None

    def __init__(self, **kwargs):
        self._pk: Optional[str] = None
        self._iris_obj: Any = None

        # Set defaults
        for name, field in self.__class__._fields.items():
            if field.default is not None:
                setattr(self, name, field.default)

        # Set explicitly provided values
        for k, v in kwargs.items():
            if k in self.__class__._fields:
                setattr(self, k, v)
            else:
                raise ValueError(f"Unknown field {k} for model {self.__class__.__name__}")

    def __repr__(self) -> str:
        fields = [f"pk={repr(self.pk)}"]
        for name in self.__class__._fields:
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
    def sync_schema(cls) -> None:
        from iris_orm.schema import sync_schema as schema_sync

        schema_sync(cls)

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
