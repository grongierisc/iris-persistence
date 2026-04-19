from __future__ import annotations

from typing import Any, List, Optional, Type, TypeVar, Dict, Generic

from iris_orm.runtime import get_runtime
import iris_orm.models

TModel = TypeVar('TModel', bound='iris_orm.models.IRISModel')

class QuerySet(Generic[TModel]):
    def __init__(self, model_cls: Type[TModel], filter_kwargs: Optional[Dict[str, Any]] = None, order_by_keys: Optional[List[str]] = None):
        self.model_cls = model_cls
        self.filter_kwargs = filter_kwargs or {}
        self.order_by_keys = order_by_keys or []
        
    def where(self, **kwargs) -> QuerySet[TModel]:
        new_kwargs = self.filter_kwargs.copy()
        new_kwargs.update(kwargs)
        return QuerySet(self.model_cls, new_kwargs, self.order_by_keys)
        
    def order_by(self, *keys: str) -> QuerySet[TModel]:
        new_keys = self.order_by_keys.copy()
        new_keys.extend(keys)
        return QuerySet(self.model_cls, self.filter_kwargs, new_keys)
        
    def all(self) -> List[TModel]:
        runtime = get_runtime()
        
        table_name = self.model_cls._classname # Schema.Table
        sql = f"SELECT ID FROM {table_name}"
        params = []
        if self.filter_kwargs:
            conditions = []
            for k, v in self.filter_kwargs.items():
                conditions.append(f"{k} = ?")
                params.append(v)
            sql += " WHERE " + " AND ".join(conditions)
            
        if self.order_by_keys:
            sql += " ORDER BY " + ", ".join(self.order_by_keys)
            
        conn = runtime.get_dbapi_connection()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        
        results = []
        for row in cursor:
            row_id = row[0]
            obj = self.model_cls.get(str(row_id))
            if obj is not None:
                results.append(obj)
                
        return results

def save_model(instance: TModel) -> None:
    runtime = get_runtime()
    classname = instance._classname
    
    if instance._pk:
        iris_obj = runtime.get_object(classname, instance._pk)
    else:
        iris_obj = runtime.create_object(classname)
        
    for field_name in instance._fields:
        if hasattr(instance, field_name):
            val = getattr(instance, field_name)
            # Delegate wrapping/setting to the adapter
            runtime.inject_iris_value(iris_obj, field_name, val)
            
    st = runtime.save_object(iris_obj)
    
    if not runtime.is_ok(st):
        raise RuntimeError(f"Save failed: {st}")
    
    pk = runtime.get_object_id(iris_obj)
    if pk:
        instance._pk = str(pk)

def get_model(cls: Type[TModel], pk: str) -> Optional[TModel]:
    runtime = get_runtime()
    iris_obj = runtime.get_object(cls._classname, pk)
    
    if iris_obj is None:
        return None
        
    params = {}
    for field_name in cls._fields:
        val = runtime.get_property(iris_obj, field_name)
        params[field_name] = runtime.extract_python_value(val)
            
    instance = cls(**params)
    instance._pk = pk
    return instance

def delete_model(instance: TModel) -> bool:
    if not instance._pk:
        return False
    runtime = get_runtime()
    return runtime.delete_object(instance._classname, instance._pk)
