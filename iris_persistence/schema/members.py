from __future__ import annotations

from typing import Any

from iris_persistence.catalog import dictionary_rows as _dictionary_rows
from iris_persistence.catalog import item_belongs_to_class
from iris_persistence.catalog import safe_get_property as _safe_get_property


def _item_belongs_to_class(runtime: Any, item: Any, classname: str) -> bool:
    return item_belongs_to_class(runtime, item, classname, unknown_is_owned=True)


def _row_value(row: dict[str, Any], name: str) -> Any:
    for key, value in row.items():
        if key.lower() == name.lower():
            return value
        if name == "%ID" and key.lower() == "id":
            return value
    return None


def _iter_runtime_list(runtime: Any, list_obj: Any) -> list[Any]:
    return [item for _index, item in _iter_runtime_list_with_indices(runtime, list_obj)]


def _iter_runtime_list_with_indices(runtime: Any, list_obj: Any) -> list[tuple[int, Any]]:
    if list_obj is None:
        return []
    try:
        count = runtime.invoke_method(list_obj, "Count")
    except Exception:
        return []
    items = []
    for index in range(1, count + 1):
        try:
            items.append((index, runtime.invoke_method(list_obj, "GetAt", index)))
        except Exception:
            continue
    return items


def _remove_runtime_list_indices(
    runtime: Any,
    list_obj: Any,
    indices: list[int],
    *,
    context: str,
) -> None:
    for index in sorted(indices, reverse=True):
        last_error: Exception | None = None
        for method_name in ("RemoveAt", "DeleteAt", "Remove"):
            try:
                runtime.invoke_method(list_obj, method_name, index)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Could not remove schema member from {context}") from last_error


def _is_system_member_name(name: str) -> bool:
    return name.startswith("%") or name == "GUID"


def _owned_schema_member_entries(
    runtime: Any,
    list_obj: Any,
    classname: str,
    *,
    dictionary_class_name: str | None = None,
    skip_system_names: bool = True,
) -> dict[str, tuple[int, Any, str | None]]:
    entries: dict[str, tuple[int, Any, str | None]] = {}
    for index, item in _iter_runtime_list_with_indices(runtime, list_obj):
        name = _safe_get_property(runtime, item, "Name")
        if not name:
            continue
        name = str(name)
        if skip_system_names and _is_system_member_name(name):
            continue
        if not _item_belongs_to_class(runtime, item, classname):
            continue
        entries[name] = (index, item, None)
    if dictionary_class_name is None:
        return entries
    _merge_dictionary_entries(runtime, entries, classname, dictionary_class_name, skip_system_names)
    return entries


def _merge_dictionary_entries(
    runtime: Any,
    entries: dict[str, tuple[int, Any, str | None]],
    classname: str,
    dictionary_class_name: str,
    skip_system_names: bool,
) -> None:
    rows = _dictionary_rows(
        runtime,
        f"SELECT %ID, Name FROM {dictionary_class_name} WHERE parent = ?",
        (classname,),
    )
    for row in rows:
        name = _row_value(row, "Name")
        object_id = _row_value(row, "%ID")
        if not name or not object_id:
            continue
        name = str(name)
        if skip_system_names and _is_system_member_name(name):
            continue
        try:
            obj = runtime.get_object(dictionary_class_name, str(object_id))
        except Exception:
            continue
        existing = entries.get(name)
        if existing is None:
            entries[name] = (0, obj, str(object_id))
        else:
            entries[name] = (existing[0], existing[1], str(object_id))


def _remove_owned_schema_member_entries(
    runtime: Any,
    list_obj: Any,
    entries: list[tuple[int, Any, str | None]],
    *,
    dictionary_class_name: str,
    context: str,
) -> None:
    _remove_runtime_list_indices(
        runtime,
        list_obj,
        [index for index, _item, _object_id in entries if index > 0],
        context=context,
    )
    for _index, _item, object_id in entries:
        if object_id is None:
            continue
        try:
            runtime.delete_object(dictionary_class_name, object_id)
        except Exception:
            pass
