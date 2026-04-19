from typing import Any, Type, get_type_hints
import datetime

from iris_orm.runtime import get_runtime
from iris_orm.types import Field

def _map_python_type_to_iris(py_type: Any, field_meta: Field) -> str:
    if getattr(field_meta, "sql_type", None):
        return field_meta.sql_type
        
    if hasattr(py_type, "__origin__"):
        py_type = py_type.__origin__
        
    if hasattr(py_type, "__args__"):
        args = py_type.__args__
        has_none = type(None) in args
        if has_none and len(args) == 2:
            py_type = args[0] if args[1] is type(None) else args[1]
        
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
    
    exists = runtime.call_classmethod("%Dictionary.ClassDefinition", "_ExistsId", classname)
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
            runtime.set_property(prop, "Required", 1)
            
        if getattr(field_meta, "default", None) is not None:
            val = field_meta.default
            if isinstance(val, str):
                runtime.set_property(prop, "InitialExpression", f'"{val}"')
            elif isinstance(val, bool):
                runtime.set_property(prop, "InitialExpression", "1" if val else "0")
            else:
                runtime.set_property(prop, "InitialExpression", str(val))
                
        if getattr(field_meta, "maxlen", None) is not None:
            params = runtime.get_property(prop, "Parameters")
            if params is not None:
                runtime.invoke_method(params, "SetAt", str(field_meta.maxlen), "MAXLEN")
            
        runtime.invoke_method(props_oref_list, "Insert", prop)
            
    indexes = getattr(model_cls, "_indexes", [])
    if isinstance(indexes, list) and mode == "replace":
        idx_list = runtime.get_property(cd, "Indices")
        for index_meta in indexes:
            idx_def = runtime.create_object("%Dictionary.IndexDefinition")
            runtime.set_property(idx_def, "Name", index_meta.name)
            runtime.set_property(idx_def, "parent", classname)
            runtime.set_property(idx_def, "Properties", index_meta.properties)
            if getattr(index_meta, "unique", False):
                runtime.set_property(idx_def, "Unique", 1)
            runtime.invoke_method(idx_list, "Insert", idx_def)
            
    storage_meta = getattr(model_cls, "_storage", None)
    if storage_meta and mode == "replace":
        stor_list = runtime.get_property(cd, "Storages")
        stor_def = runtime.create_object("%Dictionary.StorageDefinition")
        stor_def_name = "CustomStorage"
        runtime.set_property(stor_def, "Name", stor_def_name)
        runtime.set_property(stor_def, "parent", classname)
        runtime.set_property(cd, "StorageStrategy", stor_def_name)
        
        if getattr(storage_meta, "type", None): runtime.set_property(stor_def, "Type", storage_meta.type)
        if getattr(storage_meta, "data_location", None): runtime.set_property(stor_def, "DataLocation", storage_meta.data_location)
        if getattr(storage_meta, "default_data", None): runtime.set_property(stor_def, "DefaultData", storage_meta.default_data)
        if getattr(storage_meta, "id_location", None): runtime.set_property(stor_def, "IdLocation", storage_meta.id_location)
        if getattr(storage_meta, "index_location", None): runtime.set_property(stor_def, "IndexLocation", storage_meta.index_location)
        if getattr(storage_meta, "stream_location", None): runtime.set_property(stor_def, "StreamLocation", storage_meta.stream_location)
        
        # Add StorageData items
        data_list = runtime.get_property(stor_def, "Data")
        for sd_meta in getattr(storage_meta, "data", []):
            sd = runtime.create_object("%Dictionary.StorageDataDefinition")
            runtime.set_property(sd, "Name", sd_meta.name)
            runtime.set_property(sd, "parent", f"{classname}||{stor_def_name}")
            if getattr(sd_meta, "structure", None):
                runtime.set_property(sd, "Structure", sd_meta.structure)
                
            val_list = runtime.get_property(sd, "Values")
            if getattr(sd_meta, "values", None):
                for k, v in sd_meta.values.items():
                    sdv = runtime.create_object("%Dictionary.StorageDataValueDefinition")
                    runtime.set_property(sdv, "Name", str(k))
                    runtime.set_property(sdv, "parent", f"{classname}||{stor_def_name}||{sd_meta.name}")
                    runtime.set_property(sdv, "Value", str(v))
                    runtime.invoke_method(val_list, "Insert", sdv)
                
            runtime.invoke_method(data_list, "Insert", sd)
            
        runtime.invoke_method(stor_list, "Insert", stor_def)

    st = runtime.save_object(cd)
    print("SAVE STATUS:", st)
        
    st_comp = runtime.call_classmethod("%SYSTEM.OBJ", "Compile", classname, "fc")
