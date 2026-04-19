from __future__ import annotations

from typing import Any, Dict, Optional, Type, cast, get_type_hints, TypeVar, List, TYPE_CHECKING
from iris_orm.types import Field, Index, StorageDefinition

if TYPE_CHECKING:
    from iris_orm.query import QuerySet

T = TypeVar("T", bound="IRISModel")

class ModelMeta(type):
    def __new__(mcs, name: str, bases: tuple, namespace: dict):
        cls = super().__new__(mcs, name, bases, namespace)
        
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
                if field_name.startswith('_'):
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
        setattr(cls, "_superclasses", getattr(meta_inner, "superclasses", "%Persistent"))
        setattr(cls, "_storage", getattr(meta_inner, "storage", None))
        setattr(cls, "_indexes", getattr(meta_inner, "indexes", []))
        setattr(cls, "_parameters", getattr(meta_inner, "parameters", {}))


class IRISModel(metaclass=ModelMeta):
    _fields: dict[str, Field]
    _classname: str
    _sync_mode: str
    
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
    def where(cls: Type[T], **kwargs) -> 'QuerySet[T]':
        from iris_orm.query import QuerySet
        return QuerySet(cls).where(**kwargs)

