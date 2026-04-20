from __future__ import annotations

from typing import Any, Type, get_args, get_origin, get_type_hints

import iris_orm.models
from iris_orm.runtime import get_runtime
from iris_orm.types import Field


def _resolve_model_type(py_type: Any) -> Any:
    origin = get_origin(py_type)
    if origin is not None:
        args = [arg for arg in get_args(py_type) if arg is not type(None)]
        if len(args) == 1:
            return _resolve_model_type(args[0])
    return py_type


def _map_python_type_to_iris(py_type: Any, field_meta: Field) -> str:
    if getattr(field_meta, "iris_type", None):
        return field_meta.iris_type

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
    if isinstance(py_type, type) and issubclass(py_type, iris_orm.models.IRISModel):
        return py_type._classname

    return "%Library.String"


def sync_schema(model_cls: Type[Any], _seen: set[str] | None = None) -> None:
    mode = getattr(model_cls, "_sync_mode", "extend")
    if mode == "observe":
        return

    if _seen is None:
        _seen = set()

    runtime = get_runtime()
    classname = getattr(model_cls, "_classname", model_cls.__name__)
    superclasses = getattr(model_cls, "_superclasses", "%Persistent")
    if classname in _seen:
        return
    _seen.add(classname)

    exists = runtime.call_classmethod("%Dictionary.ClassDefinition", "_ExistsId", classname)
    cd = None

    if mode == "replace" and exists:
        runtime.call_classmethod("%SYSTEM.OBJ", "Delete", classname, "-d")
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
        if field_name.startswith("_"):
            continue
        resolved = _resolve_model_type(hint)
        if (
            isinstance(resolved, type)
            and issubclass(resolved, iris_orm.models.IRISModel)
            and resolved is not model_cls
        ):
            sync_schema(resolved, _seen)

    for field_name, hint in hints.items():
        if field_name.startswith("_"):
            continue

        field_meta = fields.get(field_name, Field())
        iris_type = _map_python_type_to_iris(_resolve_model_type(hint), field_meta)

        if field_name in existing_props and mode == "extend":
            continue

        prop = runtime.create_object("%Dictionary.PropertyDefinition")
        runtime.set_property(prop, "Name", field_name)
        runtime.set_property(prop, "parent", classname)

        runtime.set_property(prop, "Type", iris_type)
        if getattr(field_meta, "required", False):
            runtime.set_property(prop, "Required", 1)
        if getattr(field_meta, "readonly", False):
            runtime.set_property(prop, "ReadOnly", 1)
        if getattr(field_meta, "collection", None):
            runtime.set_property(prop, "Collection", field_meta.collection)
        if getattr(field_meta, "sql_field_name", None):
            runtime.set_property(prop, "SqlFieldName", field_meta.sql_field_name)

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
            if getattr(index_meta, "type", None):
                runtime.set_property(idx_def, "Type", index_meta.type)
            if getattr(index_meta, "primary_key", False):
                runtime.set_property(idx_def, "PrimaryKey", 1)
            runtime.invoke_method(idx_list, "Insert", idx_def)

    storage_meta = getattr(model_cls, "_storage", None)
    if storage_meta and mode == "replace":
        stor_list = runtime.get_property(cd, "Storages")
        stor_def = runtime.create_object("%Dictionary.StorageDefinition")
        stor_def_name = "CustomStorage"
        runtime.set_property(stor_def, "Name", stor_def_name)
        runtime.set_property(stor_def, "parent", classname)
        runtime.set_property(cd, "StorageStrategy", stor_def_name)

        if getattr(storage_meta, "type", None):
            runtime.set_property(stor_def, "Type", storage_meta.type)
        if getattr(storage_meta, "data_location", None):
            runtime.set_property(stor_def, "DataLocation", storage_meta.data_location)
        if getattr(storage_meta, "default_data", None):
            runtime.set_property(stor_def, "DefaultData", storage_meta.default_data)
        if getattr(storage_meta, "id_location", None):
            runtime.set_property(stor_def, "IdLocation", storage_meta.id_location)
        if getattr(storage_meta, "index_location", None):
            runtime.set_property(stor_def, "IndexLocation", storage_meta.index_location)
        if getattr(storage_meta, "stream_location", None):
            runtime.set_property(stor_def, "StreamLocation", storage_meta.stream_location)

        # Add StorageData items
        data_list = runtime.get_property(stor_def, "Data")
        for sd_meta in getattr(storage_meta, "data", []):
            sd = runtime.create_object("%Dictionary.StorageDataDefinition")
            runtime.set_property(sd, "Name", sd_meta.name)
            runtime.set_property(sd, "parent", f"{classname}||{stor_def_name}")
            if getattr(sd_meta, "structure", None):
                runtime.set_property(sd, "Structure", sd_meta.structure)
            if getattr(sd_meta, "attribute", None) is not None:
                runtime.set_property(sd, "Attribute", sd_meta.attribute)
            if getattr(sd_meta, "subscript", None) is not None:
                runtime.set_property(sd, "Subscript", sd_meta.subscript)

            val_list = runtime.get_property(sd, "Values")
            if getattr(sd_meta, "values", None):
                for k, v in sd_meta.values.items():
                    sdv = runtime.create_object("%Dictionary.StorageDataValueDefinition")
                    runtime.set_property(sdv, "Name", str(k))
                    runtime.set_property(
                        sdv, "parent", f"{classname}||{stor_def_name}||{sd_meta.name}"
                    )
                    runtime.set_property(sdv, "Value", str(v))
                    runtime.invoke_method(val_list, "Insert", sdv)

            runtime.invoke_method(data_list, "Insert", sd)

        properties_list = runtime.get_property(stor_def, "Properties")
        for property_meta in getattr(storage_meta, "properties", []):
            storage_property = runtime.create_object("%Dictionary.StoragePropertyDefinition")
            runtime.set_property(storage_property, "Name", property_meta.name)
            runtime.set_property(storage_property, "parent", f"{classname}||{stor_def_name}")
            if getattr(property_meta, "average_field_size", None) is not None:
                runtime.set_property(
                    storage_property, "AverageFieldSize", property_meta.average_field_size
                )
            if getattr(property_meta, "selectivity", None) is not None:
                runtime.set_property(storage_property, "Selectivity", property_meta.selectivity)
            runtime.invoke_method(properties_list, "Insert", storage_property)

        sql_maps_list = runtime.get_property(stor_def, "SQLMaps")
        for sql_map_meta in getattr(storage_meta, "sql_maps", []):
            sql_map = runtime.create_object("%Dictionary.StorageSQLMapDefinition")
            runtime.set_property(sql_map, "Name", sql_map_meta.name)
            runtime.set_property(sql_map, "parent", f"{classname}||{stor_def_name}")
            if getattr(sql_map_meta, "block_count", None) is not None:
                runtime.set_property(sql_map, "BlockCount", sql_map_meta.block_count)
            if getattr(sql_map_meta, "condition", None) is not None:
                runtime.set_property(sql_map, "Condition", sql_map_meta.condition)
            if getattr(sql_map_meta, "condition_fields", None) is not None:
                runtime.set_property(sql_map, "ConditionFields", sql_map_meta.condition_fields)
            if getattr(sql_map_meta, "conditional_with_host_vars", None) is not None:
                runtime.set_property(
                    sql_map,
                    "ConditionalWithHostVars",
                    1 if sql_map_meta.conditional_with_host_vars else 0,
                )
            if getattr(sql_map_meta, "global_name", None) is not None:
                runtime.set_property(sql_map, "Global", sql_map_meta.global_name)
            if getattr(sql_map_meta, "population_pct", None) is not None:
                runtime.set_property(sql_map, "PopulationPct", sql_map_meta.population_pct)
            if getattr(sql_map_meta, "population_type", None) is not None:
                runtime.set_property(sql_map, "PopulationType", sql_map_meta.population_type)
            if getattr(sql_map_meta, "row_reference", None) is not None:
                runtime.set_property(sql_map, "RowReference", sql_map_meta.row_reference)
            if getattr(sql_map_meta, "structure", None) is not None:
                runtime.set_property(sql_map, "Structure", sql_map_meta.structure)
            if getattr(sql_map_meta, "type", None) is not None:
                runtime.set_property(sql_map, "Type", sql_map_meta.type)

            sql_map_data_list = runtime.get_property(sql_map, "Data")
            for data_meta in getattr(sql_map_meta, "data", ()) or ():
                sql_map_data = runtime.create_object("%Dictionary.StorageSQLMapDataDefinition")
                runtime.set_property(sql_map_data, "Name", data_meta.name)
                runtime.set_property(
                    sql_map_data, "parent", f"{classname}||{stor_def_name}||{sql_map_meta.name}"
                )
                if getattr(data_meta, "node", None) is not None:
                    runtime.set_property(sql_map_data, "Node", data_meta.node)
                if getattr(data_meta, "piece", None) is not None:
                    runtime.set_property(sql_map_data, "Piece", data_meta.piece)
                if getattr(data_meta, "delimiter", None) is not None:
                    runtime.set_property(sql_map_data, "Delimiter", data_meta.delimiter)
                if getattr(data_meta, "retrieval_code", None) is not None:
                    runtime.set_property(
                        sql_map_data, "RetrievalCode", data_meta.retrieval_code
                    )
                runtime.invoke_method(sql_map_data_list, "Insert", sql_map_data)

            row_id_spec_list = runtime.get_property(sql_map, "RowIdSpecs")
            for row_id_spec_meta in getattr(sql_map_meta, "row_id_specs", ()) or ():
                row_id_spec = runtime.create_object("%Dictionary.StorageSQLMapRowIdSpecDefinition")
                runtime.set_property(row_id_spec, "Name", row_id_spec_meta.name)
                runtime.set_property(
                    row_id_spec, "parent", f"{classname}||{stor_def_name}||{sql_map_meta.name}"
                )
                if getattr(row_id_spec_meta, "field", None) is not None:
                    runtime.set_property(row_id_spec, "Field", row_id_spec_meta.field)
                if getattr(row_id_spec_meta, "expression", None) is not None:
                    runtime.set_property(row_id_spec, "Expression", row_id_spec_meta.expression)
                runtime.invoke_method(row_id_spec_list, "Insert", row_id_spec)

            subscript_list = runtime.get_property(sql_map, "Subscripts")
            for sub_meta in getattr(sql_map_meta, "subscripts", ()) or ():
                subscript = runtime.create_object("%Dictionary.StorageSQLMapSubDefinition")
                runtime.set_property(subscript, "Name", sub_meta.name)
                runtime.set_property(
                    subscript, "parent", f"{classname}||{stor_def_name}||{sql_map_meta.name}"
                )
                if getattr(sub_meta, "access_type", None) is not None:
                    runtime.set_property(subscript, "AccessType", sub_meta.access_type)
                if getattr(sub_meta, "data_access", None) is not None:
                    runtime.set_property(subscript, "DataAccess", sub_meta.data_access)
                if getattr(sub_meta, "delimiter", None) is not None:
                    runtime.set_property(subscript, "Delimiter", sub_meta.delimiter)
                if getattr(sub_meta, "expression", None) is not None:
                    runtime.set_property(subscript, "Expression", sub_meta.expression)
                if getattr(sub_meta, "loop_init_value", None) is not None:
                    runtime.set_property(subscript, "LoopInitValue", sub_meta.loop_init_value)
                if getattr(sub_meta, "next_code", None) is not None:
                    runtime.set_property(subscript, "NextCode", sub_meta.next_code)
                if getattr(sub_meta, "null_marker", None) is not None:
                    runtime.set_property(subscript, "NullMarker", sub_meta.null_marker)
                if getattr(sub_meta, "start_value", None) is not None:
                    runtime.set_property(subscript, "StartValue", sub_meta.start_value)
                if getattr(sub_meta, "stop_expression", None) is not None:
                    runtime.set_property(subscript, "StopExpression", sub_meta.stop_expression)
                if getattr(sub_meta, "stop_value", None) is not None:
                    runtime.set_property(subscript, "StopValue", sub_meta.stop_value)

                access_var_list = runtime.get_property(subscript, "Accessvars")
                for access_var_meta in getattr(sub_meta, "access_vars", ()) or ():
                    access_var = runtime.create_object(
                        "%Dictionary.StorageSQLMapSubAccessvarDefinition"
                    )
                    runtime.set_property(access_var, "Name", access_var_meta.name)
                    runtime.set_property(
                        access_var,
                        "parent",
                        f"{classname}||{stor_def_name}||{sql_map_meta.name}||{sub_meta.name}",
                    )
                    if getattr(access_var_meta, "variable", None) is not None:
                        runtime.set_property(access_var, "Variable", access_var_meta.variable)
                    if getattr(access_var_meta, "code", None) is not None:
                        runtime.set_property(access_var, "Code", access_var_meta.code)
                    runtime.invoke_method(access_var_list, "Insert", access_var)

                invalid_condition_list = runtime.get_property(subscript, "Invalidconditions")
                for invalid_condition_meta in getattr(sub_meta, "invalid_conditions", ()) or ():
                    invalid_condition = runtime.create_object(
                        "%Dictionary.StorageSQLMapSubInvalidconditionDefinition"
                    )
                    runtime.set_property(invalid_condition, "Name", invalid_condition_meta.name)
                    runtime.set_property(
                        invalid_condition,
                        "parent",
                        f"{classname}||{stor_def_name}||{sql_map_meta.name}||{sub_meta.name}",
                    )
                    if getattr(invalid_condition_meta, "expression", None) is not None:
                        runtime.set_property(
                            invalid_condition, "Expression", invalid_condition_meta.expression
                        )
                    runtime.invoke_method(
                        invalid_condition_list, "Insert", invalid_condition
                    )

                runtime.invoke_method(subscript_list, "Insert", subscript)

            runtime.invoke_method(sql_maps_list, "Insert", sql_map)

        runtime.invoke_method(stor_list, "Insert", stor_def)

    st = runtime.save_object(cd)
    print("SAVE STATUS:", st)

    runtime.call_classmethod("%SYSTEM.OBJ", "Compile", classname, "fc")
