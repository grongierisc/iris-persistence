"""
Connection abstraction for IRIS ORM.

Supports embedded (iris module) and remote (SQLAlchemy engine) connections.
"""
from __future__ import annotations

import re
from typing import Any


class IRISConnection:
    """Wraps an iris connection — either embedded (iris module) or remote (SQLAlchemy engine).

    Usage:
        conn = IRISConnection()                    # embedded
        conn = IRISConnection(engine)              # SQLAlchemy engine

    Context manager:
        with IRISConnection(engine) as conn:
            conn.sql_exec(sql, params)
            conn.iris_cls(classname)
    """

    def __init__(self, engine: Any = None) -> None:
        self._engine = engine
        self._sa_conn: Any = None

    # ------------------------------------------------------------------
    def sql_exec(self, sql: str, params: list | None = None) -> Any:
        """Execute *sql* and return an iterable of rows.

        Embedded: delegates to ``iris.sql.exec``.
        Remote:   delegates to ``engine.connect().execute(text(sql), params)``.
        """
        if self._engine is None:
            import iris  # noqa: PLC0415
            return iris.sql.exec(sql, params) if params else iris.sql.exec(sql)

        from sqlalchemy import text  # noqa: PLC0415
        params_list = list(params or [])
        # Convert ? positional placeholders → :p0, :p1, … for SQLAlchemy
        idx = [0]
        param_dict: dict[str, Any] = {}

        def _sub(m: re.Match) -> str:  # noqa: ARG001
            k = f"p{idx[0]}"
            if idx[0] < len(params_list):
                param_dict[k] = params_list[idx[0]]
            idx[0] += 1
            return f":{k}"

        sa_sql = re.sub(r"\?", _sub, sql)
        active_conn = self._sa_conn if self._sa_conn is not None else self._engine.connect()
        return active_conn.execute(text(sa_sql), param_dict)

    # ------------------------------------------------------------------
    def iris_cls(self, classname: str) -> Any:
        """Return the IRIS class proxy for *classname*.

        Raises NotImplementedError for remote connections — use sql_exec instead.
        """
        if self._engine is None:
            import iris  # noqa: PLC0415
            return iris.cls(classname)
        raise NotImplementedError(
            "Direct Object API not supported over remote connection; use sql_exec instead"
        )

    # ------------------------------------------------------------------
    def __enter__(self) -> "IRISConnection":
        if self._engine is not None:
            self._sa_conn = self._engine.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._sa_conn is not None:
            self._sa_conn.close()
            self._sa_conn = None
