import unittest
from unittest.mock import MagicMock
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
        self.mock_db.classMethodValue.assert_called_once_with("%Library.DynamicObject", "%FromJSON", '{"a": "b"}')
        
        # Should set the newly created oref back
        self.mock_oref.set.assert_called_once_with("MyDict", self.mock_dyn_obj)

    def test_inject_list(self):
        self.adapter.inject_iris_value(self.mock_obj, "MyList", [1, 2, 3])
        
        # Should create %DynamicArray via db handle
        self.mock_db.classMethodValue.assert_called_once_with("%Library.DynamicArray", "%FromJSON", '[1, 2, 3]')
        
        # Should set the newly created oref back
        self.mock_oref.set.assert_called_once_with("MyList", self.mock_dyn_obj)

if __name__ == "__main__":
    unittest.main()
