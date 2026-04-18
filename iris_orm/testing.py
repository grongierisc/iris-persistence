from typing import Any, Dict, Optional
from iris_orm.runtime import RuntimeAdapter

class FakeAdapter(RuntimeAdapter):
    def __init__(self):
        self.db: Dict[str, Dict[str, Any]] = {}
        self._id_counter = 1

    def call_classmethod(self, class_name: str, method_name: str, *args: Any) -> Any:
        if method_name == "_New":
            class _FakeObj:
                _classname = class_name
                def _Id(self):
                    return getattr(self, "id_val", None)
                def __getattr__(self, name):
                    if name == "_Id":
                        return self._Id
                    raise AttributeError(name)
            obj = _FakeObj()
            obj._is_new = True # tag
            return obj
        elif method_name == "_Id":
            obj = args[0]
            return obj._Id()
        raise NotImplementedError(f"FakeAdapter does not implement {class_name}.{method_name}")

    def save_object(self, obj: Any) -> Any:
        # Assuming obj is our fake proxy or real object we decorated
        class_name = getattr(obj, "_classname", "Demo.Unknown")
        if class_name not in self.db:
            self.db[class_name] = {}
        
        # assign ID
        if not hasattr(obj, "id_val") or obj.id_val is None:
            obj.id_val = str(self._id_counter)
            self._id_counter += 1
            
        data = {}
        for k in dir(obj):
            if not k.startswith("_") and k != "id_val" and not callable(getattr(obj, k)):
                data[k] = getattr(obj, k)
                
        self.db[class_name][obj.id_val] = data
        return obj

    def get_object(self, class_name: str, obj_id: str) -> Any:
        if class_name not in self.db or obj_id not in self.db[class_name]:
            return None
        data = self.db[class_name][obj_id]
        
        class _FakeObj:
            def _Id(self): return obj_id
            
        obj = _FakeObj()
        for k, v in data.items():
            setattr(obj, k, v)
        return obj

    def delete_object(self, class_name: str, obj_id: str) -> bool:
        if class_name in self.db and obj_id in self.db[class_name]:
            del self.db[class_name][obj_id]
            return True
        return False
        
    def get_dbapi_connection(self) -> Any:
        # Basic mocked DBAPI wrapper
        class _Cursor:
            def __init__(self, db):
                self._db = db
                self._rows = []
            def execute(self, sql, params=()):
                # very naive parser relying on our builder syntax 'SELECT ID FROM class_name' 
                table_name = sql.split("FROM ")[1].split(" ")[0].replace("_", ".")
                if table_name in self._db:
                    self._rows = [(k,) for k in self._db[table_name].keys()]
                else:
                    self._rows = []
            def fetchall(self):
                return self._rows
            def __iter__(self):
                return iter(self._rows)
            def close(self): pass
            
        class _Connection:
            def __init__(self, db):
                self._db = db
            def cursor(self):
                return _Cursor(self._db)
            def close(self): pass
            
        return _Connection(self.db)

def preload_schema(*args, **kwargs):
    pass
