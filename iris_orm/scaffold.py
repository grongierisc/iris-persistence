from pathlib import Path
from typing import List, Any

from iris_orm.runtime import get_runtime
from iris_orm.types import StorageDefinition, StorageData, StorageProperty, StorageSQLMap

def _map_iris_type_to_python(iris_type: str) -> str:
    """Map an IRIS type to a Python type string for the generated class."""
    if not iris_type:
        return "Any"
    
    mapping = {
        "%Library.String": "str",
        "%Library.Integer": "int",
        "%Library.Float": "float",
        "%Library.Double": "float",
        "%Library.Decimal": "float",
        "%Library.Boolean": "bool",
        "%Stream.GlobalBinary": "bytes",
        "%Stream.FileBinary": "bytes",
        "%Stream.GlobalCharacter": "str",
        "%Stream.FileCharacter": "str",
        "%Library.DynamicObject": "dict",
        "%Library.DynamicArray": "list",
        "%Library.Date": "datetime.date",
        "%Library.Time": "datetime.time",
        "%Library.TimeStamp": "datetime.datetime",
    }
    
    return mapping.get(iris_type, "str")

def _parse_iris_list(s: Any) -> List[Any]:
    if not isinstance(s, (bytes, str)): 
        return []
    i = 0
    res = []
    while i < len(s):
        l = s[i] if isinstance(s, bytes) else ord(s[i])
        if l == 0: 
            break
        val = s[i+2:i+l]
        res.append(val)
        i += l
    return res

def _parse_iris_dict(s: Any) -> dict:
    res = {}
    for item in _parse_iris_list(s):
        kv = _parse_iris_list(item)
        if len(kv) == 2:
            key = kv[0].decode('utf-8') if isinstance(kv[0], bytes) else str(kv[0])
            val = kv[1].decode('utf-8') if isinstance(kv[1], bytes) else str(kv[1])
            res[key] = val
    return res

def scaffold_from_iris(pattern: str, output_dir: str, mode: str = "observe", extract_meta: bool = False) -> List[str]:
    """Scaffold typed models from live IRIS classes."""
    runtime = get_runtime()
    conn = runtime.get_dbapi_connection()

    if "*" in pattern:
        pattern = pattern.replace("*", "%")

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    generated_files = []
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT Name, Super FROM %Dictionary.CompiledClass WHERE Name LIKE ?", [pattern])
        classes = cursor.fetchall()

        for cls_name, super_cls in classes:
            cursor.execute(
                "SELECT Name, Type, Required, InitialExpression, Parameters FROM %Dictionary.CompiledProperty WHERE parent = ?",
                [cls_name]
            )

            props = []
            for prop_name, prop_type, required, init_exp, params_raw in cursor:
                if prop_name.startswith("%"):
                    continue

                parsed_params = _parse_iris_dict(params_raw) if params_raw else {}

                props.append({
                    "name": prop_name,
                    "type": _map_iris_type_to_python(prop_type),
                    "required": bool(required) and str(required) != "0",
                    "default": init_exp if init_exp != '""' and init_exp else None,
                    "maxlen": parsed_params.get("MAXLEN", None)
                })

            file_name = cls_name.split(".")[-1].lower() + ".py"
            file_path = out_path / file_name

            with open(file_path, "w", encoding="utf-8") as f:
                f.write("from __future__ import annotations\n\n")
                f.write("import datetime\n")
                f.write("from typing import Annotated, Any\n\n")
                f.write("from iris_orm import Field, IRISModel, Index, StorageDefinition, StorageData, StorageProperty, StorageSQLMap\n\n")

                f.write(f"class {cls_name.split('.')[-1]}(IRISModel):\n")
                if not props:
                    f.write("    pass\n")
                else:
                    for prop in props:
                        req_str = "True" if prop["required"] else "False"
                        field_args = [f"required={req_str}"]
                        if prop.get("maxlen"):
                            field_args.append(f"maxlen={prop['maxlen']}")

                        default_python_value = None
                        if prop.get("default") is not None:
                            if prop["default"] == "1":
                                field_args.append("default=True")
                                default_python_value = "True"
                            elif prop["default"] == "0":
                                field_args.append("default=False")
                                default_python_value = "False"
                            elif prop["default"].startswith('"') and prop["default"].endswith('"'):
                                field_args.append(f"default={prop['default']}")
                                default_python_value = prop["default"]
                            else:
                                field_args.append(f"default={prop['default']}")
                                default_python_value = prop["default"]

                        field_str = ", ".join(field_args)

                        if not prop["required"]:
                            assignment = f" = {default_python_value}" if default_python_value is not None else " = None"
                            f.write(f"    {prop['name']}: Annotated[{prop['type']} | None, Field({field_str})]{assignment}\n")
                        else:
                            assignment = f" = {default_python_value}" if default_python_value is not None else ""
                            f.write(f"    {prop['name']}: Annotated[{prop['type']}, Field({field_str})]{assignment}\n")

                f.write("\n    class Meta:\n")
                f.write(f"        classname = \"{cls_name}\"\n")
                f.write(f"        mode = \"{mode}\"\n")
                if super_cls:
                    f.write(f"        superclasses = \"{super_cls}\"\n")

                if extract_meta:
                    try:
                        cursor.execute("SELECT Name, Default FROM %Dictionary.CompiledParameter WHERE parent = ?", [cls_name])
                        params = cursor.fetchall()
                        if params:
                            p_filtered = [(n, d) for n, d in params if not n.startswith("%") and n != "GUID"]
                            if p_filtered:
                                f.write("        parameters = {\n")
                                for p_name, p_default in p_filtered:
                                    f.write(f"            \"{p_name}\": \"{p_default}\",\n")
                                f.write("        }\n")

                        cursor.execute("SELECT Name, Properties, _Unique FROM %Dictionary.CompiledIndex WHERE parent = ?", [cls_name])
                        indexes = cursor.fetchall()
                        if indexes:
                            i_filtered = [(n, p, u) for n, p, u in indexes if not str(n).startswith("%") and n not in ("IDKEY", "$Product")]
                            if i_filtered:
                                f.write("        indexes = [\n")
                                for idx_name, idx_props, idx_unique in i_filtered:
                                    uniq_val = idx_unique == 1 or idx_unique == "1" or str(idx_unique).lower() == "true"
                                    uniq_str = "True" if uniq_val else "False"
                                    f.write(f"            Index(\"{idx_name}\", properties=\"{idx_props}\", unique={uniq_str}),\n")
                                f.write("        ]\n")

                        cursor.execute("SELECT Name, DataLocation, DefaultData, Type FROM %Dictionary.CompiledStorage WHERE parent = ?", [cls_name])
                        storage_def = cursor.fetchone()
                        if storage_def:
                            s_name, s_data_loc, s_def_data, s_type = storage_def
                            s_parent = f"{cls_name}||{s_name}"

                            f.write("        storage = StorageDefinition(\n")
                            if s_data_loc:
                                f.write(f"            data_location=\"{s_data_loc}\",\n")
                            if s_def_data:
                                f.write(f"            default_data=\"{s_def_data}\",\n")
                            if s_type:
                                f.write(f"            type=\"{s_type}\",\n")

                            cursor.execute("SELECT Name, Structure FROM %Dictionary.CompiledStorageData WHERE parent = ?", [s_parent])
                            storage_datas = cursor.fetchall()
                            if storage_datas:
                                f.write("            data=(\n")
                                for sd_name, sd_struct in storage_datas:
                                    sd_parent = f"{s_parent}||{sd_name}"
                                    cursor.execute("SELECT Name, Value FROM %Dictionary.CompiledStorageDataValue WHERE parent = ?", [sd_parent])
                                    sd_vals = {str(n): str(v) for n, v in cursor.fetchall()}
                                    f.write("                StorageData(\n")
                                    f.write(f"                    name=\"{sd_name}\",\n")
                                    if sd_struct:
                                        f.write(f"                    structure=\"{sd_struct}\",\n")
                                    f.write(f"                    values={sd_vals!r},\n")
                                    f.write("                ),\n")
                                f.write("            ),\n")

                            cursor.execute("SELECT Name, AverageFieldSize FROM %Dictionary.CompiledStorageProperty WHERE parent = ?", [s_parent])
                            storage_props = cursor.fetchall()
                            if storage_props:
                                sp_filtered = [(n, a) for n, a in storage_props if not str(n).startswith("%")]
                                if sp_filtered:
                                    f.write("            properties=(\n")
                                    for sp_name, sp_avg in sp_filtered:
                                        f.write(f"                StorageProperty(name=\"{sp_name}\", average_field_size=\"{sp_avg}\"),\n")
                                    f.write("            ),\n")

                            cursor.execute("SELECT Name, BlockCount FROM %Dictionary.CompiledStorageSQLMap WHERE parent = ?", [s_parent])
                            sql_maps = cursor.fetchall()
                            if sql_maps:
                                f.write("            sql_maps=(\n")
                                for sm_name, sm_block in sql_maps:
                                    f.write(f"                StorageSQLMap(name=\"{sm_name}\", block_count=\"{sm_block}\"),\n")
                                f.write("            ),\n")

                            f.write("        )\n")

                    except Exception:
                        pass

            generated_files.append(str(file_path))
    finally:
        cursor.close()
        conn.close()

    return generated_files

def scaffold_from_cls(cls_dir: str, output_dir: str, mode: str = "observe") -> None:
    """Scaffold from exported .cls files."""
    raise NotImplementedError("File scaffolding is not fully implemented yet.")
