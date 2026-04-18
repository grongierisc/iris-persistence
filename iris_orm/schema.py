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
        cd = runtime.call_classmethod("%Dictionary.ClassDefinition", "_New", classname)
        
    if hasattr(cd, "_oref"):
        cd._oref.set("Super", superclasses)
    else:
        cd.Super = superclasses
        
    props_oref_list = getattr(cd, "_oref", cd).get("Properties") if hasattr(cd, "_oref") else cd.Properties
    existing_props = {}
    
    if hasattr(props_oref_list, "invoke"):
        count = props_oref_list.invoke("Count")
        for i in range(1, count + 1):
            prop = props_oref_list.invoke("GetAt", i)
            prop_name = prop._oref.get("Name") if hasattr(prop, "_oref") else prop.Name
            existing_props[prop_name] = prop
    else:
        for i in range(1, props_oref_list.Count() + 1):
            prop = props_oref_list.GetAt(i)
            existing_props[prop.Name] = prop
            
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
        prop = runtime.call_classmethod("%Dictionary.PropertyDefinition", "_New", prop_id)
        
        if hasattr(prop, "_oref"):
            prop._oref.set("Type", iris_type)
            if getattr(field_meta, "required", False):
                prop._oref.set("Required", 1)
            props_oref_list.invoke("Insert", prop._oref)
        else:
            prop.Type = iris_type
            if getattr(field_meta, "required", False):
                prop.Required = 1
            props_oref_list.Insert(prop)
            
    if hasattr(cd, "_oref"):
        st = cd._oref.invoke("%Save")
    else:
        st = cd._Save()
        print("SAVE STATUS:", st)
        
    st_comp = runtime.call_classmethod("%SYSTEM.OBJ", "Compile", classname, "fc")
