from __future__ import annotations

from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.ext.compiler import compiles

_INSTALLED = False


def install_sqlite_shims() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "JSON"

    @compiles(PGUUID, "sqlite")
    def _compile_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001
        return "CHAR(36)"

    _INSTALLED = True
