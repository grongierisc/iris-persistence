from __future__ import annotations

from typing import Any, List, Optional, Type, TypeVar, Dict

from iris_orm.runtime import get_runtime
import iris_orm.models

TModel = TypeVar('TModel', bound='iris_orm.models.IRISModel')

class QuerySet:
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
                
        # Return DBAPI results
        return results

def save_model(instance: TModel) -> None:
    runtime = get_runtime()
    classname = instance._classname
    
    if instance._pk:
        iris_obj = runtime.get_object(classname, instance._pk)
    else:
        iris_obj = runtime.call_classmethod(classname, "_New")
        
    for field_name in instance._fields:
        if hasattr(instance, field_name):
            val = getattr(instance, field_name)
            
            # Handle structured data for native embedded execution or un-wrapped proxy
            if isinstance(val, (bytes, bytearray)):
                current_prop = getattr(iris_obj, field_name, None)
                if hasattr(current_prop, "Write"):
                    current_prop.Clear()
                    current_prop.Write(val)
                else:
                    setattr(iris_obj, field_name, val)
            elif isinstance(val, dict):
                import json
                try:
                    dyn_obj = runtime.call_classmethod("%Library.DynamicObject", "_FromJSON", json.dumps(val))
                    setattr(iris_obj, field_name, dyn_obj)
                except Exception:
                    setattr(iris_obj, field_name, val)
            elif isinstance(val, list):
                import json
                try:
                    dyn_arr = runtime.call_classmethod("%Library.DynamicArray", "_FromJSON", json.dumps(val))
                    setattr(iris_obj, field_name, dyn_arr)
                except Exception:
                    setattr(iris_obj, field_name, val)
            else:
                setattr(iris_obj, field_name, val)
            
    st = runtime.save_object(iris_obj)
    
    # In native python, successful save returns 1, failure returns 0 and error msg
    if isinstance(st, int) and st == 0:
        raise RuntimeError(f"Save failed")
    elif isinstance(st, str) and st.startswith("0 "):
        raise RuntimeError(f"Save failed: {st}")
    elif hasattr(st, "IsOK") and not st.IsOK():
        raise RuntimeError(f"Save failed: {st}")
    
    # After save, we should get the ID
    try:
        pk = iris_obj._Id()
    except AttributeError:
        # Fallback
        try:
            pk = iris_obj.Id()
        except AttributeError:
            pk = getattr(iris_obj, "%Id")() if hasattr(iris_obj, "%Id") else None
            
    if pk:
        instance._pk = str(pk)

def get_model(cls: Type[TModel], pk: str) -> Optional[TModel]:
    runtime = get_runtime()
    iris_obj = runtime.get_object(cls._classname, pk)
    
    if iris_obj is None:
        return None
        
    params = {}
    for field_name in cls._fields:
        if hasattr(iris_obj, field_name):
            val = getattr(iris_obj, field_name)
            
            # Fallback for embedded python: Detect IRIS DynamicObjects or Streams.
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
                    s = runtime.call_classmethod("%Stream.GlobalCharacter", "_New")
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
                        content = content.encode('latin1')
                        
                    val = content
                except Exception:
                    pass
            params[field_name] = val
            
    instance = cls(**params)
    instance._pk = pk
    return instance

def delete_model(instance: TModel) -> bool:
    if not instance._pk:
        return False
    runtime = get_runtime()
    return runtime.delete_object(instance._classname, instance._pk)
