from typing import Any, Type, get_type_hints
import datetime

from iris_orm.runtime import get_runtime
from iris_orm.types import Field

def _map_python_type_to_iris(py_type: Any, field_meta: Field) -> str:
    if getattr(field_meta, "sql_type", None):
        return field_meta.sql_type
        
    if hasattr(py_type, "__origin__"):
        py_type = py_type.__origin__
        
    if py_type is str:
        return "%Library.String"
    if py_type is int:
        return "%Library.Integer"
    if py_type is float:
        return "%Library.Float"
    if py_type is bool:
        return "%Library.Boolean"
    if py_type is bytes or py_type is bytearray:
        return "%Stream.GlobalBinary"
    if py_type is dict or str(py_type).startswith("dict"):
        return "%Library.DynamicObject"
    if py_type is list or str(py_type).startswith("list"):
        return "%Library.DynamicArray"
    if str(py_type) == "<class 'datetime.datetime'>":
        return "%Library.TimeStamp"
    if str(py_type) == "<class 'datetime.date'>":
        return "%Library.Date"
    if str(py_type) == "<class 'datetime.time'>":
        return "%Library.Time"
        
    return "%Library.String"

def sync_schema(model_cls: Type[Any]) -> None:
    mode = getattr(model_cls, "_sync_mode", "extend")
    if mode == "observe":
        return
        
    runtime = get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    superclasses = getattr(model_cls, "_superclasses", "%Persistent")
    
    exists = runtime.call_classmethod("%Dictionary.ClassDefinition", "%ExistsId", classname)
    cd = None
    
    if mode == "replace" and exists:
        status = runtime.call_classmethod("%SYSTEM.OBJ", "Delete", classname, "-d")
        exists = False
        
    if exists:
        cd = runtime.get_object("%Dictionary.ClassDefinition", classname)
    else:
        cd = runtime.create_object("%Dictionary.ClassDefinition")
        runtime.set_property(cd, "Name", classname)
        
    runtime.set_property(cd, "Super", superclasses)
        
    props_oref_list = runtime.get_property(cd, "Properties")
    existing_props = {}
    
    count = runtime.invoke_method(props_oref_list, "Count")
    for i in range(1, count + 1):
        prop = runtime.invoke_method(props_oref_list, "GetAt", i)
        prop_name = runtime.get_property(prop, "Name")
        existing_props[prop_name] = prop
            
    fields = getattr(model_cls, "_fields", {})
    hints = get_type_hints(model_cls, include_extras=True)
    
    for field_name, hint in hints.items():
        if field_name.startswith('_'):
            continue
            
        field_meta = fields.get(field_name, Field())
        iris_type = _map_python_type_to_iris(hint, field_meta)
        
        if field_name in existing_props and mode == "extend":
            continue
            
        prop_id = f"{classname}:{field_name}"    
        prop = runtime.create_object("%Dictionary.PropertyDefinition")
        runtime.set_property(prop, "Name", field_name)
        runtime.set_property(prop, "parent", classname)
            
        runtime.set_property(prop, "Type", iris_type)
        if getattr(field_meta, "required", False):
            runtime.set_property(prop, "Required", True)
            
        runtime.invoke_method(props_oref_list, "Insert", prop)
            
    st = runtime.save_object(cd)
    print("SAVE STATUS:", st)
        
    st_comp = runtime.call_classmethod("%SYSTEM.OBJ", "Compile", classname, "fc")
