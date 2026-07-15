from __future__ import annotations

from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Optional,
    Type,
    TypeVar,
    cast,
)

from iris_persistence.advanced_storage import StorageDefinition
from iris_persistence.model.meta import (
    DEFAULT_SYNC_MODE as DEFAULT_SYNC_MODE,
)
from iris_persistence.model.meta import (
    SYNC_POLICIES as SYNC_POLICIES,
)
from iris_persistence.model.meta import (
    ModelMeta,
    _FieldPlan,
)
from iris_persistence.model.values import (
    _convert_recursive_value,
    _model_value_to_dict,
    _validate_field_value,
)
from iris_persistence.model.values import (
    _is_object_reference_field as _is_object_reference_field,
)
from iris_persistence.types import (
    UNSET,
    ClassMetadata,
    FieldInfo,
    ModelField,
    StorageTuning,
)

if TYPE_CHECKING:
    from iris_persistence.query import QuerySet

T = TypeVar("T", bound="Model")
TDataclass = TypeVar("TDataclass")


def _validate_provided_field_names(model_cls: Any, provided_values: dict[str, Any]) -> None:
    unknown = [name for name in provided_values if name not in model_cls.__model_fields__]
    if not unknown:
        return
    unknown_fields = ", ".join(sorted(unknown))
    raise TypeError(f"Unknown field(s) for model {model_cls.__name__}: {unknown_fields}")


def _resolve_initial_field_value(
    model_cls: Any,
    name: str,
    model_field: ModelField,
    provided_values: dict[str, Any],
) -> tuple[bool, Any]:
    value = provided_values.get(name, UNSET)
    if value is UNSET:
        value = model_field.get_default_value()
    if value is UNSET and model_field.required:
        raise TypeError(f"Missing required field '{name}' for model {model_cls.__name__}")
    if value is UNSET:
        return (False, value)
    if model_cls._validate_on_init:
        value = _validate_field_value(model_field, value)
    return (True, value)


class Model(metaclass=ModelMeta):
    __model_fields__: dict[str, ModelField]
    _fields: dict[str, FieldInfo]
    _classname: str
    _sync_mode: str
    _auto_sync: bool
    _validate_on_init: bool
    _class_metadata: ClassMetadata | None
    _storage_tuning: StorageTuning | None
    _custom_storage: StorageDefinition | None
    _field_plans: tuple[_FieldPlan, ...]
    _read_fields: dict[str, tuple[_FieldPlan, ...]]
    _save_fields: dict[str, tuple[_FieldPlan, ...]]
    _is_serial_class: bool

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
        model_cls = self.__class__
        _validate_provided_field_names(model_cls, provided_values)
        for name, model_field in model_cls.__model_fields__.items():
            should_assign, value = _resolve_initial_field_value(
                model_cls, name, model_field, provided_values
            )
            if should_assign:
                setattr(self, name, value)

    def __init__(self, **kwargs):
        self._initialize_model_state(kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Return declared model fields as plain Python values."""
        values: dict[str, Any] = {}
        for name in self.__class__.__model_fields__:
            if hasattr(self, name):
                values[name] = _model_value_to_dict(getattr(self, name))
        return values

    @classmethod
    def from_dict(cls: Type[T], values: dict[str, Any]) -> T:
        """Build a model from a mapping of declared field names to Python values."""
        if not isinstance(values, dict):
            raise TypeError(f"{cls.__name__}.from_dict() expects a dict")

        converted = {
            name: value
            if (model_field := cls.__model_fields__.get(name)) is None
            else _convert_recursive_value(
                value,
                model_field.declared_type,
                "mapping_to_model",
            )
            for name, value in values.items()
        }
        return cls(**converted)

    def to_dataclass(self, dataclass_type: Type[TDataclass]) -> TDataclass:
        """Build a dataclass DTO from matching model field names."""
        if not (isinstance(dataclass_type, type) and is_dataclass(dataclass_type)):
            raise TypeError("to_dataclass() expects a dataclass type")

        values: dict[str, Any] = {}
        for dataclass_field in dataclass_fields(cast(Any, dataclass_type)):
            if not dataclass_field.init:
                continue
            name = dataclass_field.name
            if name in self.__class__.__model_fields__ and hasattr(self, name):
                values[name] = _convert_recursive_value(
                    getattr(self, name),
                    dataclass_field.type,
                    "model_to_dataclass",
                )
        return dataclass_type(**values)

    @classmethod
    def from_dataclass(cls: Type[T], value: Any) -> T:
        """Build a model from a dataclass DTO with matching field names."""
        if isinstance(value, type) or not is_dataclass(value):
            raise TypeError(f"{cls.__name__}.from_dataclass() expects a dataclass instance")

        values = {
            dataclass_field.name: _convert_recursive_value(
                getattr(value, dataclass_field.name),
                model_field.declared_type,
                "dataclass_to_model",
            )
            for dataclass_field in dataclass_fields(value)
            if (model_field := cls.__model_fields__.get(dataclass_field.name)) is not None
        }
        return cls.from_dict(values)

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
        from iris_persistence.query import save_model

        save_model(self)

    def delete(self) -> bool:
        """Delete this persistent object from IRIS; return whether it existed."""
        from iris_persistence.query import delete_model

        deleted = delete_model(self)
        if deleted:
            self._iris_obj = None
        return deleted

    def to_iris(self, *, auto_sync: bool = True, validate: bool = True) -> Any:
        """Return a populated IRIS object handle without calling %Save()."""

        from iris_persistence.query import materialize

        return materialize(self, auto_sync=auto_sync, validate=validate)

    @classmethod
    def from_iris(
        cls: Type[T],
        iris_obj: Any,
        *,
        known_pk: Optional[str] = None,
    ) -> Optional[T]:
        """Build a model instance around an existing IRIS object handle."""

        from iris_persistence.query import from_iris

        return from_iris(cls, iris_obj, known_pk=known_pk)

    @classmethod
    def sync_schema(cls, *, dry_run: bool = False):
        from iris_persistence.schema import diff_schema as schema_diff
        from iris_persistence.schema import sync_schema as schema_sync

        if dry_run:
            return schema_diff(cls)
        schema_sync(cls)
        return None

    @classmethod
    def diff_schema(cls):
        from iris_persistence.schema import diff_schema as schema_diff

        return schema_diff(cls)

    @classmethod
    def get(cls: Type[T], pk: str) -> Optional[T]:
        from iris_persistence.query import get_model

        return get_model(cls, pk)

    @classmethod
    def all(cls: Type[T]) -> List[T]:
        from iris_persistence.query import QuerySet

        return QuerySet(cls).all()

    @classmethod
    def where(cls: Type[T], **kwargs) -> "QuerySet[T]":
        from iris_persistence.query import QuerySet

        return QuerySet(cls).where(**kwargs)

    def _validate_for_save(self) -> None:
        for name, model_field in self.__class__.__model_fields__.items():
            if hasattr(self, name):
                _validate_field_value(model_field, getattr(self, name))
            elif model_field.required:
                raise ValueError(f"Field '{name}' is required")
