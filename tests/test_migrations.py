"""
Unit tests for iris_orm.migrations.

All tests use mocked IRIS — no live connection required.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Fake iris fixture (same pattern as main test suite)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_iris(monkeypatch):
    mock_iris = MagicMock()
    monkeypatch.setitem(sys.modules, "iris", mock_iris)
    yield mock_iris


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_conn(sql_rows=None):
    """Return a MagicMock IRISConnection."""
    from iris_orm.connection import IRISConnection
    conn = MagicMock(spec=IRISConnection)
    conn.sql_exec.return_value = iter(sql_rows or [])
    return conn


# ===========================================================================
# TestOperations
# ===========================================================================

class TestCreateClass:
    def test_creates_when_not_exists(self):
        from iris_orm.migrations.migration import CreateClass
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            CreateClass("Demo.Foo").apply(conn)
        conn.iris_cls.assert_any_call("%Dictionary.ClassDefinition")

    def test_skips_when_already_exists(self):
        from iris_orm.migrations.migration import CreateClass
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=True):
            CreateClass("Demo.Foo").apply(conn)
        for c in conn.iris_cls.call_args_list:
            assert c[0][0] != "%Dictionary.ClassDefinition"

    def test_revert_calls_drop_class(self):
        from iris_orm.migrations.migration import CreateClass
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            CreateClass("Demo.Foo").revert(conn)
        conn.iris_cls.assert_any_call("%Dictionary.ClassDefinition")

    def test_as_code(self):
        from iris_orm.migrations.migration import CreateClass
        code = CreateClass("Demo.Foo").as_code()
        assert "create_class" in code
        assert "Demo.Foo" in code

    def test_revert_code(self):
        from iris_orm.migrations.migration import CreateClass
        code = CreateClass("Demo.Foo").revert_code()
        assert "drop_class" in code


class TestAddProperty:
    def test_apply_creates_property(self):
        from iris_orm.migrations.migration import AddProperty
        conn = _make_conn()
        conn.iris_cls.return_value._OpenId.side_effect = Exception("not found")
        AddProperty("Demo.Foo", "Title", "%String", required=True).apply(conn)
        conn.iris_cls.assert_any_call("%Dictionary.PropertyDefinition")

    def test_apply_recompiles(self):
        from iris_orm.migrations.migration import AddProperty
        conn = _make_conn()
        conn.iris_cls.return_value._OpenId.side_effect = Exception("not found")
        AddProperty("Demo.Foo", "Title", "%String").apply(conn)
        conn.iris_cls.assert_any_call("%SYSTEM.OBJ")

    def test_revert_calls_drop(self):
        from iris_orm.migrations.migration import AddProperty
        conn = _make_conn()
        with pytest.raises(RuntimeError):
            # DropProperty._DeleteId raises — that's expected without real IRIS
            conn.iris_cls.return_value._DeleteId.side_effect = Exception("fail")
            AddProperty("Demo.Foo", "Title", "%String").revert(conn)

    def test_as_code_contains_classname_and_name(self):
        from iris_orm.migrations.migration import AddProperty
        code = AddProperty("Demo.Foo", "Title", "%String", required=True, maxlen=200).as_code()
        assert "add_property" in code
        assert "Demo.Foo" in code
        assert "Title" in code
        assert "required=True" in code
        assert "maxlen=200" in code

    def test_revert_code(self):
        from iris_orm.migrations.migration import AddProperty
        code = AddProperty("Demo.Foo", "Title", "%String").revert_code()
        assert "drop_property" in code


class TestAlterProperty:
    def test_apply_updates_type(self):
        from iris_orm.migrations.migration import AlterProperty
        conn = _make_conn()
        AlterProperty("Demo.Foo", "Score", "%Integer", old_type="%String").apply(conn)
        prop_obj = conn.iris_cls.return_value._OpenId.return_value
        assert prop_obj.Type == "%Integer"

    def test_revert_applies_old_type(self):
        from iris_orm.migrations.migration import AlterProperty
        conn = _make_conn()
        AlterProperty("Demo.Foo", "Score", "%Integer", old_type="%String").revert(conn)
        prop_obj = conn.iris_cls.return_value._OpenId.return_value
        assert prop_obj.Type == "%String"

    def test_revert_raises_without_old_type(self):
        from iris_orm.migrations.migration import AlterProperty
        conn = _make_conn()
        with pytest.raises(NotImplementedError):
            AlterProperty("Demo.Foo", "Score", "%Integer").revert(conn)

    def test_as_code(self):
        from iris_orm.migrations.migration import AlterProperty
        code = AlterProperty("Demo.Foo", "Score", "%Integer").as_code()
        assert "alter_property" in code
        assert "%Integer" in code


class TestDropProperty:
    def test_apply_deletes_and_recompiles(self):
        from iris_orm.migrations.migration import DropProperty
        conn = _make_conn()
        DropProperty("Demo.Foo", "Body").apply(conn)
        conn.iris_cls.return_value._DeleteId.assert_called_once_with("Demo.Foo||Body")
        conn.iris_cls.assert_any_call("%SYSTEM.OBJ")

    def test_apply_raises_on_failure(self):
        from iris_orm.migrations.migration import DropProperty
        conn = _make_conn()
        conn.iris_cls.return_value._DeleteId.side_effect = Exception("fail")
        with pytest.raises(RuntimeError, match="Failed to drop property"):
            DropProperty("Demo.Foo", "Body").apply(conn)

    def test_revert_raises_not_implemented(self):
        from iris_orm.migrations.migration import DropProperty
        conn = _make_conn()
        with pytest.raises(NotImplementedError):
            DropProperty("Demo.Foo", "Body").revert(conn)


class TestAddRelationship:
    def test_apply_creates_relationship(self):
        from iris_orm.migrations.migration import AddRelationship
        conn = _make_conn()
        conn.iris_cls.return_value._OpenId.side_effect = Exception("not found")
        AddRelationship(
            "Demo.Post", "Author", "Demo.Author",
            cardinality="parent", inverse="Posts"
        ).apply(conn)
        conn.iris_cls.assert_any_call("%Dictionary.RelationshipDefinition")

    def test_revert_drops_relationship(self):
        from iris_orm.migrations.migration import AddRelationship
        conn = _make_conn()
        with pytest.raises(RuntimeError):
            conn.iris_cls.return_value._DeleteId.side_effect = Exception("fail")
            AddRelationship(
                "Demo.Post", "Author", "Demo.Author",
                cardinality="parent", inverse="Posts"
            ).revert(conn)

    def test_as_code(self):
        from iris_orm.migrations.migration import AddRelationship
        code = AddRelationship(
            "Demo.Post", "Author", "Demo.Author",
            cardinality="parent", inverse="Posts"
        ).as_code()
        assert "add_relationship" in code
        assert "Demo.Post" in code


class TestDropRelationship:
    def test_apply_deletes_relationship(self):
        from iris_orm.migrations.migration import DropRelationship
        conn = _make_conn()
        DropRelationship("Demo.Post", "Author").apply(conn)
        conn.iris_cls.return_value._DeleteId.assert_called_once_with("Demo.Post||Author")

    def test_revert_raises(self):
        from iris_orm.migrations.migration import DropRelationship
        conn = _make_conn()
        with pytest.raises(NotImplementedError):
            DropRelationship("Demo.Post", "Author").revert(conn)


# ===========================================================================
# TestMigrationConnection
# ===========================================================================

class TestMigrationConnection:
    def test_create_class_delegates(self):
        from iris_orm.migrations.migration import MigrationConnection
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            mc = MigrationConnection(conn)
            mc.create_class("Demo.X")
        conn.iris_cls.assert_any_call("%Dictionary.ClassDefinition")

    def test_add_property_delegates(self):
        from iris_orm.migrations.migration import MigrationConnection
        conn = _make_conn()
        conn.iris_cls.return_value._OpenId.side_effect = Exception("not found")
        mc = MigrationConnection(conn)
        mc.add_property("Demo.X", "Name", "%String")
        conn.iris_cls.assert_any_call("%Dictionary.PropertyDefinition")

    def test_compile_warns_on_failure(self):
        import warnings
        from iris_orm.migrations.migration import MigrationConnection
        conn = _make_conn()
        conn.iris_cls.return_value.Compile.side_effect = Exception("fail")
        mc = MigrationConnection(conn)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            mc.compile("Demo.X")
            assert len(w) == 1


# ===========================================================================
# TestTracker
# ===========================================================================

class TestTracker:
    def test_init_creates_class_when_missing(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            tracker.init(conn)
        conn.iris_cls.assert_any_call("%Dictionary.ClassDefinition")

    def test_init_skips_when_exists(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=True):
            tracker.init(conn)
        for c in conn.iris_cls.call_args_list:
            assert c[0][0] != "%Dictionary.ClassDefinition"

    def test_get_applied_returns_empty_on_error(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        conn.sql_exec.side_effect = Exception("no table")
        result = tracker.get_applied(conn)
        assert result == []

    def test_get_applied_returns_revisions(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        conn.sql_exec.return_value = iter([("0001",), ("0002",)])
        result = tracker.get_applied(conn)
        assert result == ["0001", "0002"]

    def test_mark_applied_saves_record(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        tracker.mark_applied(conn, "0001", "initial migration")
        conn.iris_cls.assert_any_call(tracker._TRACKER_CLASS)
        obj = conn.iris_cls.return_value._New.return_value
        assert obj.Revision == "0001"
        obj._Save.assert_called_once()

    def test_mark_reverted_deletes_record(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        conn.sql_exec.return_value = iter([("42",)])
        tracker.mark_reverted(conn, "0001")
        conn.iris_cls.return_value._DeleteId.assert_called_once_with("42")

    def test_mark_reverted_raises_on_failure(self):
        from iris_orm.migrations import tracker
        conn = _make_conn()
        conn.sql_exec.return_value = iter([("42",)])
        conn.iris_cls.return_value._DeleteId.side_effect = Exception("fail")
        with pytest.raises(RuntimeError, match="Failed to revert"):
            tracker.mark_reverted(conn, "0001")


# ===========================================================================
# TestWriter
# ===========================================================================

class TestWriter:
    def test_next_revision_first(self):
        from iris_orm.migrations.writer import next_revision
        assert next_revision([]) == "0001"

    def test_next_revision_increments(self):
        from iris_orm.migrations.writer import next_revision
        assert next_revision(["0001", "0002"]) == "0003"

    def test_render_migration_has_revision(self):
        from iris_orm.migrations.writer import render_migration
        src = render_migration("0001", None, "initial", [])
        assert "revision = '0001'" in src
        assert "down_revision = None" in src

    def test_render_migration_has_upgrade_downgrade(self):
        from iris_orm.migrations.writer import render_migration
        src = render_migration("0001", None, "initial", [])
        assert "def upgrade" in src
        assert "def downgrade" in src

    def test_render_migration_includes_op_code(self):
        from iris_orm.migrations.migration import AddProperty
        from iris_orm.migrations.writer import render_migration
        op = AddProperty("Demo.Foo", "Title", "%String")
        src = render_migration("0001", None, "add title", [op])
        assert "add_property" in src
        assert "drop_property" in src  # revert_code in downgrade

    def test_write_migration_file_creates_file(self, tmp_path):
        from iris_orm.migrations.writer import write_migration_file
        path = write_migration_file(tmp_path, "0001", None, "initial migration", [])
        assert path.exists()
        assert path.suffix == ".py"
        content = path.read_text()
        assert "revision = '0001'" in content

    def test_write_migration_file_slug_in_name(self, tmp_path):
        from iris_orm.migrations.writer import write_migration_file
        path = write_migration_file(tmp_path, "0001", None, "Add Views Field", [])
        assert "add_views_field" in path.name


# ===========================================================================
# TestAutogenerate
# ===========================================================================

class TestAutogenerate:
    @pytest.fixture(autouse=True)
    def setup_model(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Mig.Article", None)
        from iris_orm import IRISModel, field

        class MigArticle(IRISModel):
            _iris_classname = "Mig.Article"
            Title: str = field(required=True, maxlen=500)
            Views: int = field(default=0)

        self.Article = MigArticle

    def test_diff_detects_new_class(self):
        from iris_orm.migrations.autogenerate import diff_models
        from iris_orm.migrations.migration import CreateClass
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            ops = diff_models([self.Article], {}, conn)
        assert any(isinstance(op, CreateClass) for op in ops)

    def test_diff_detects_new_properties(self):
        from iris_orm.migrations.autogenerate import diff_models
        from iris_orm.migrations.migration import AddProperty
        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=True):
            ops = diff_models([self.Article], {}, conn)
        assert any(isinstance(op, AddProperty) and op.name == "Title" for op in ops)
        assert any(isinstance(op, AddProperty) and op.name == "Views" for op in ops)

    def test_diff_detects_type_change(self):
        from iris_orm.migrations.autogenerate import diff_models
        from iris_orm.migrations.migration import AlterProperty
        conn = _make_conn()
        applied_state = {
            "Mig.Article": {
                "properties": {"Title": "%Integer", "Views": "%Integer"},
                "relationships": {},
            }
        }
        with patch("iris_orm.schema._class_exists_in_iris", return_value=True):
            ops = diff_models([self.Article], applied_state, conn)
        alter_ops = [op for op in ops if isinstance(op, AlterProperty)]
        assert any(op.name == "Title" for op in alter_ops)

    def test_diff_no_ops_when_in_sync(self):
        from iris_orm.migrations.autogenerate import diff_models
        conn = _make_conn()
        applied_state = {
            "Mig.Article": {
                "properties": {"Title": "%String", "Views": "%Integer"},
                "relationships": {},
            }
        }
        with patch("iris_orm.schema._class_exists_in_iris", return_value=True):
            ops = diff_models([self.Article], applied_state, conn)
        assert ops == []

    def test_diff_skips_existing_binding_models(self, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Mig.Bound", None)
        from iris_orm import IRISModel
        from iris_orm.migrations.autogenerate import diff_models

        rows = [("X", "%String", 0, "", "")]
        fake_iris.sql.exec.return_value = iter(rows)

        class MigExistingBinding(IRISModel):
            _iris_classname = "Mig.Bound"

        conn = _make_conn()
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            ops = diff_models([MigExistingBinding], {}, conn)
        assert ops == []

    def test_load_state_from_migrations_replay(self):
        from iris_orm.migrations.autogenerate import load_state_from_migrations
        from iris_orm.migrations import MigrationFile

        # Fake a migration module that adds a class + property
        mod = types.ModuleType("mig_0001")
        def upgrade(conn):
            conn.create_class("Demo.X")
            conn.add_property("Demo.X", "Name", "%String")
        mod.upgrade = upgrade

        mf = MigrationFile(
            path=Path("0001_initial.py"),
            revision="0001",
            down_revision=None,
            description="initial",
            module=mod,
        )
        state = load_state_from_migrations([mf])
        assert "Demo.X" in state
        assert state["Demo.X"]["properties"]["Name"] == "%String"

    def test_load_state_drop_class_removes_it(self):
        from iris_orm.migrations.autogenerate import load_state_from_migrations
        from iris_orm.migrations import MigrationFile

        mod1 = types.ModuleType("mig_0001")
        def upgrade1(conn):
            conn.create_class("Demo.X")
            conn.add_property("Demo.X", "Name", "%String")
        mod1.upgrade = upgrade1

        mod2 = types.ModuleType("mig_0002")
        def upgrade2(conn):
            conn.drop_class("Demo.X")
        mod2.upgrade = upgrade2

        files = [
            MigrationFile(Path("0001.py"), "0001", None, "create", mod1),
            MigrationFile(Path("0002.py"), "0002", "0001", "drop", mod2),
        ]
        state = load_state_from_migrations(files)
        assert "Demo.X" not in state


# ===========================================================================
# TestMigrationRunner
# ===========================================================================

class TestMigrationRunner:
    def test_init_calls_tracker_init(self, tmp_path):
        from iris_orm.migrations import MigrationRunner
        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.init") as mock_init:
            runner.init()
            mock_init.assert_called_once_with(conn)

    def test_upgrade_applies_pending(self, tmp_path):
        from iris_orm.migrations import MigrationRunner
        from iris_orm.migrations.writer import write_migration_file
        write_migration_file(tmp_path, "0001", None, "initial", [])

        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=[]), \
             patch("iris_orm.migrations.mark_applied") as mock_mark:
            runner.upgrade()
            mock_mark.assert_called_once_with(conn, "0001", "initial")

    def test_upgrade_already_up_to_date(self, tmp_path, capsys):
        from iris_orm.migrations import MigrationRunner
        from iris_orm.migrations.writer import write_migration_file
        write_migration_file(tmp_path, "0001", None, "initial", [])

        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=["0001"]):
            runner.upgrade()
        captured = capsys.readouterr()
        assert "up to date" in captured.out

    def test_downgrade_reverts_applied(self, tmp_path):
        from iris_orm.migrations import MigrationRunner
        from iris_orm.migrations.writer import write_migration_file
        write_migration_file(tmp_path, "0001", None, "initial", [])
        write_migration_file(tmp_path, "0002", "0001", "second", [])

        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=["0001", "0002"]), \
             patch("iris_orm.migrations.mark_reverted") as mock_revert:
            runner.downgrade("0001")
            mock_revert.assert_called_once_with(conn, "0002")

    def test_history_prints_table(self, tmp_path, capsys):
        from iris_orm.migrations import MigrationRunner
        from iris_orm.migrations.writer import write_migration_file
        write_migration_file(tmp_path, "0001", None, "initial", [])

        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=["0001"]):
            runner.history()
        captured = capsys.readouterr()
        assert "0001" in captured.out
        assert "applied" in captured.out

    def test_current_returns_last_applied(self, tmp_path):
        from iris_orm.migrations import MigrationRunner
        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=["0001", "0002"]):
            rev = runner.current()
        assert rev == "0002"

    def test_current_returns_none_when_empty(self, tmp_path):
        from iris_orm.migrations import MigrationRunner
        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.migrations.get_applied", return_value=[]):
            rev = runner.current()
        assert rev is None

    def test_generate_writes_file(self, tmp_path, fake_iris):
        from iris_orm.metaclass import _MODEL_REGISTRY
        _MODEL_REGISTRY.pop("Mig.Gen", None)
        from iris_orm import IRISModel, field
        from iris_orm.migrations import MigrationRunner

        class MigGen(IRISModel):
            _iris_classname = "Mig.Gen"
            Name: str = field()

        conn = _make_conn()
        runner = MigrationRunner(tmp_path, conn=conn)
        with patch("iris_orm.schema._class_exists_in_iris", return_value=False):
            path = runner.generate("create mig gen", models=[MigGen])
        assert path.exists()
        content = path.read_text()
        assert "create_class" in content or "add_property" in content
