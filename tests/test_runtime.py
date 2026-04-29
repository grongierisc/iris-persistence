import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

from iris_orm import Field
from iris_orm.runtime import NativeProxyAdapter


class TestNativeProxyAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = NativeProxyAdapter()

        # Mock OREF (the raw intersystems object)
        self.mock_oref = MagicMock()
        self.mock_oref.invoke.return_value = None

        # Mock classMethodValue output for dict/list
        self.mock_db = MagicMock()
        self.mock_dyn_obj = MagicMock()
        self.mock_db.classMethodValue.return_value = self.mock_dyn_obj

        # Mock stream property
        self.mock_stream = MagicMock()
        self.mock_oref.get.return_value = self.mock_stream

        # Mock wrapper object
        self.mock_obj = MagicMock()
        self.mock_obj._oref = self.mock_oref
        self.mock_obj._db = self.mock_db

    def test_inject_bytes(self):
        self.adapter.inject_iris_value(self.mock_obj, "MyStream", b"12345")

        # Should get stream explicitly and write explicitly
        self.mock_oref.get.assert_called_once_with("MyStream")
        self.mock_stream.invoke.assert_any_call("Clear")
        self.mock_stream.invoke.assert_any_call("Write", b"12345")

        # Should not use Python setattr bypass
        self.mock_oref.set.assert_not_called()

    def test_inject_dict(self):
        self.adapter.inject_iris_value(self.mock_obj, "MyDict", {"a": "b"})

        # Should create %DynamicObject via db handle
        self.mock_db.classMethodValue.assert_called_once_with(
            "%Library.DynamicObject", "%FromJSON", '{"a": "b"}'
        )

        # Should set the newly created oref back
        self.mock_oref.set.assert_called_once_with("MyDict", self.mock_dyn_obj)

    def test_inject_list(self):
        self.adapter.inject_iris_value(self.mock_obj, "MyList", [1, 2, 3])

        # Should create %DynamicArray via db handle
        self.mock_db.classMethodValue.assert_called_once_with(
            "%Library.DynamicArray", "%FromJSON", "[1, 2, 3]"
        )

        # Should set the newly created oref back
        self.mock_oref.set.assert_called_once_with("MyList", self.mock_dyn_obj)

    def test_inject_list_without_native_db_uses_base_dispatch(self):
        plain_obj = SimpleNamespace(MyList=None)
        self.adapter.call_classmethod = MagicMock(return_value="dyn-array")

        self.adapter.inject_iris_value(plain_obj, "MyList", [1, 2, 3])

        self.adapter.call_classmethod.assert_called_once_with(
            "%Library.DynamicArray", "_FromJSON", "[1, 2, 3]"
        )
        self.assertEqual(plain_obj.MyList, "dyn-array")

    def test_inject_collection_class_dict_bypasses_dynamic_object(self):
        field = Field(iris_type="%ArrayOfDataTypes")
        calls = []

        class _FakeArrayCollection:
            def Clear(self):
                calls.append(("Clear",))

            def SetAt(self, value, key):
                calls.append(("SetAt", key, value))

        self.mock_obj.MyArray = _FakeArrayCollection()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyArray",
            {"a": "b"},
            field_meta=field,
        )

        self.mock_db.classMethodValue.assert_not_called()
        self.mock_oref.set.assert_not_called()
        self.assertEqual(calls, [("Clear",), ("SetAt", "a", "b")])

    def test_inject_collection_class_list_bypasses_dynamic_array(self):
        field = Field(iris_type="%ListOfDataTypes")
        calls = []

        class _FakeListCollection:
            def Clear(self):
                calls.append(("Clear",))

            def Insert(self, value):
                calls.append(("Insert", value))

        self.mock_obj.MyList = _FakeListCollection()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyList",
            [1, 2, 3],
            field_meta=field,
        )

        self.mock_db.classMethodValue.assert_not_called()
        self.mock_oref.set.assert_not_called()
        self.assertEqual(calls, [("Clear",), ("Insert", 1), ("Insert", 2), ("Insert", 3)])

    def test_inject_collection_class_list_refreshes_insert_per_item(self):
        field = Field(iris_type="%ListOfDataTypes")
        calls = []

        class _TypeSensitiveListCollection:
            def Clear(self):
                calls.append(("Clear",))

            def __getattribute__(self, name):
                if name == "Insert":
                    used = False

                    def _insert(value):
                        nonlocal used
                        if used:
                            raise RuntimeError("stale insert binding")
                        used = True
                        calls.append(("Insert", value))

                    return _insert
                return object.__getattribute__(self, name)

        self.mock_obj.MyList = _TypeSensitiveListCollection()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyList",
            ["a", 1, True],
            field_meta=field,
        )

        self.assertEqual(
            calls,
            [("Clear",), ("Insert", "a"), ("Insert", 1), ("Insert", True)],
        )

    def test_inject_collection_metadata_list_uses_collection_api(self):
        field = Field(iris_type="Demo.ListFixtureItem", collection="list")
        calls = []

        class _FakeListCollection:
            def Clear(self):
                calls.append(("Clear",))

            def Insert(self, value):
                calls.append(("Insert", value))

        self.mock_obj.MyList = _FakeListCollection()
        marker = object()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyList",
            [marker],
            field_meta=field,
        )

        self.mock_db.classMethodValue.assert_not_called()
        self.mock_oref.set.assert_not_called()
        self.assertEqual(calls, [("Clear",), ("Insert", marker)])

    def test_inject_collection_metadata_array_uses_collection_api(self):
        field = Field(iris_type="Demo.ListFixtureItem", collection="array")
        calls = []

        class _FakeArrayCollection:
            def Clear(self):
                calls.append(("Clear",))

            def SetAt(self, value, key):
                calls.append(("SetAt", key, value))

        self.mock_obj.MyArray = _FakeArrayCollection()
        marker = object()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyArray",
            {"one": marker},
            field_meta=field,
        )

        self.mock_db.classMethodValue.assert_not_called()
        self.mock_oref.set.assert_not_called()
        self.assertEqual(calls, [("Clear",), ("SetAt", "one", marker)])

    def test_inject_collection_class_array_refreshes_setat_per_item(self):
        field = Field(iris_type="%ArrayOfDataTypes")
        calls = []

        class _TypeSensitiveArrayCollection:
            def Clear(self):
                calls.append(("Clear",))

            def __getattribute__(self, name):
                if name == "SetAt":
                    used = False

                    def _set_at(value, key):
                        nonlocal used
                        if used:
                            raise RuntimeError("stale setat binding")
                        used = True
                        calls.append(("SetAt", key, value))

                    return _set_at
                return object.__getattribute__(self, name)

        self.mock_obj.MyArray = _TypeSensitiveArrayCollection()

        self.adapter.inject_iris_value(
            self.mock_obj,
            "MyArray",
            {"a": "A", "b": 1},
            field_meta=field,
        )

        self.assertEqual(
            calls,
            [("Clear",), ("SetAt", "a", "A"), ("SetAt", "b", 1)],
        )

    def test_extract_list_collection_value(self):
        class _FakeListCollection:
            def Count(self):
                return 3

            def GetAt(self, index):
                return ["A", "B", "C"][index - 1]

        value = self.adapter.extract_python_value(_FakeListCollection())

        self.assertEqual(value, ["A", "B", "C"])

    def test_extract_list_collection_refreshes_getat_per_item(self):
        class _TypeSensitiveListCollection:
            def Count(self):
                return 3

            def __getattribute__(self, name):
                if name == "GetAt":
                    used = False

                    def _get_at(index):
                        nonlocal used
                        if used:
                            raise RuntimeError("stale getat binding")
                        used = True
                        return ["A", "B", "C"][index - 1]

                    return _get_at
                return object.__getattribute__(self, name)

        value = self.adapter.extract_python_value(_TypeSensitiveListCollection())

        self.assertEqual(value, ["A", "B", "C"])

    def test_inject_percent_list_uses_logical_encoding(self):
        field = Field(iris_type="%List")

        class _PlainObj:
            MyList = ""

        plain_obj = _PlainObj()
        self.adapter.call_classmethod = MagicMock(return_value="encoded-list")

        self.adapter.inject_iris_value(
            plain_obj,
            "MyList",
            ["A", "B"],
            field_meta=field,
        )

        self.adapter.call_classmethod.assert_called_once_with(
            "%Library.List",
            "OdbcToLogical",
            "A,B",
        )
        self.assertEqual(plain_obj.MyList, "encoded-list")

    def test_get_dbapi_connection_uses_explicit_remote_credentials(self):
        fake_dbapi = SimpleNamespace(connect=MagicMock(return_value="dbapi-conn"))
        fake_iris = SimpleNamespace(dbapi=fake_dbapi)
        connection = SimpleNamespace(hostname="localhost", port=1972, namespace="IRISAPP")
        adapter = NativeProxyAdapter(connection)

        with patch.dict(
            "os.environ",
            {"IRISUSERNAME": "SuperUser", "IRISPASSWORD": "SYS"},
            clear=False,
        ):
            with patch.dict("sys.modules", {"iris": fake_iris}):
                result = adapter.get_dbapi_connection()

        fake_dbapi.connect.assert_called_once_with(
            hostname="localhost",
            port=1972,
            namespace="IRISAPP",
            username="SuperUser",
            password="SYS",
        )
        self.assertEqual(result, "dbapi-conn")

    def test_get_dbapi_connection_reuses_native_connection_cursor(self):
        connection = SimpleNamespace(cursor=MagicMock(return_value="cursor"), close=MagicMock())
        adapter = NativeProxyAdapter(connection)

        result = adapter.get_dbapi_connection()

        self.assertEqual(result.cursor(), "cursor")
        result.close()
        connection.close.assert_not_called()

    def test_missing_class_error_is_rewritten_with_context(self):
        fake_iris = SimpleNamespace(
            cls=MagicMock(side_effect=RuntimeError("iris.cls: error finding class"))
        )

        with patch.dict("sys.modules", {"iris": fake_iris}):
            with self.assertRaisesRegex(
                RuntimeError,
                r"IRIS class 'Demo\.Demo' does not exist in the current namespace",
            ) as exc_info:
                self.adapter.create_object("Demo.Demo")

        self.assertIn("Model.sync_schema()", str(exc_info.exception))
        self.assertIn("Meta.classname", str(exc_info.exception))

    def test_format_status_uses_system_status_error_text(self):
        self.adapter.call_classmethod = MagicMock(
            return_value='ERROR #5808: Key not unique: Demo.Demo:TotoIdx:^Demo.DemoI("TotoIdx"," HELLO")'
        )

        message = self.adapter.format_status("0 raw-status")

        self.adapter.call_classmethod.assert_called_once_with(
            "%SYSTEM.Status",
            "GetErrorText",
            "0 raw-status",
        )
        self.assertEqual(
            message,
            'ERROR #5808: Key not unique: Demo.Demo:TotoIdx:^Demo.DemoI("TotoIdx"," HELLO")',
        )

    def test_format_status_falls_back_to_raw_status_text(self):
        self.adapter.call_classmethod = MagicMock(side_effect=RuntimeError("status lookup failed"))

        message = self.adapter.format_status("0 raw-status")

        self.assertEqual(message, "0 raw-status")


if __name__ == "__main__":
    unittest.main()
