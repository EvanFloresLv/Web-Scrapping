"""Covers `app.domains.executions.models` (spec 0003).

The `executions` and `execution_results` shape is the contract feature 7's
migration conforms to. These tests pin the columns, nullability, FK ondelete
policies (AC-10), lifecycle CHECK literals (AC-12), the three composite indexes
with `created_at DESC` the execution browser filters on (AC-14), and the
append-only `execution_results` shape (AC-7).
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint

from app.core.database import Base
from app.domains.executions.models import Execution, ExecutionResult


def _check(table: object, suffix: str) -> CheckConstraint:
    """Find a CHECK by its short `name=...`. Naming convention renames it; table
    names can contain underscores, so match on endswith instead of splitting."""
    for c in table.constraints:  # type: ignore[attr-defined]
        if isinstance(c, CheckConstraint) and c.name and c.name.endswith("_" + suffix):
            return c
    raise AssertionError(
        f"CHECK ending in `_{suffix}` not found on {getattr(table, 'name', table)}"
    )


def _is_uuid_v7_default(col) -> bool:  # type: ignore[no-untyped-def]
    from uuid import UUID as _UUID

    default = col.default
    arg = getattr(default, "arg", None)
    if default is None or not callable(arg):
        return False
    try:
        produced = arg()
    except TypeError:
        produced = arg(None)
    return isinstance(produced, _UUID) and produced.version == 7


# ---------- registration ----------


def test_both_tables_registered_on_base_metadata() -> None:
    # covers: AC-1
    assert "executions" in Base.metadata.tables
    assert "execution_results" in Base.metadata.tables


# ---------- executions ----------


def test_executions_columns() -> None:
    # covers: AC-6
    cols = {c.name for c in Execution.__table__.columns}
    assert cols == {
        "id",
        "workflow_version_id",
        "target_url_id",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "items_extracted",
        "error_code",
        "error_message",
        "correlation_id",
        "created_at",
        "updated_at",
    }


def test_executions_nullability() -> None:
    # covers: AC-6 (every lifecycle column is nullable until the row reaches terminal;
    # `correlation_id` is NEVER nullable per the spec text)
    cols = {c.name: c for c in Execution.__table__.columns}
    assert cols["workflow_version_id"].nullable is False
    assert cols["target_url_id"].nullable is False
    assert cols["status"].nullable is False
    assert cols["started_at"].nullable is True
    assert cols["finished_at"].nullable is True
    assert cols["duration_ms"].nullable is True
    assert cols["items_extracted"].nullable is False
    assert cols["error_code"].nullable is True
    assert cols["error_message"].nullable is True
    assert cols["correlation_id"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False


def test_executions_id_default_is_uuid_v7() -> None:
    # covers: AC-8
    assert _is_uuid_v7_default(Execution.__table__.columns["id"]) is True


def test_executions_status_default_is_pending() -> None:
    # covers: AC-6, AC-12
    status = Execution.__table__.columns["status"]
    assert status.default is not None
    assert status.default.arg == "pending"
    assert status.server_default is not None
    assert status.server_default.arg == "pending"


def test_executions_items_extracted_defaults_to_zero() -> None:
    # covers: AC-6
    col = Execution.__table__.columns["items_extracted"]
    assert col.default is not None
    assert col.default.arg == 0
    assert col.server_default is not None
    assert col.server_default.arg == "0"


def test_executions_workflow_version_fk_is_restrict() -> None:
    # covers: AC-10 (history unbreakable)
    fks = list(Execution.__table__.columns["workflow_version_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "workflow_versions.id"
    assert fks[0].ondelete == "RESTRICT"


def test_executions_target_url_fk_is_restrict() -> None:
    # covers: AC-10
    fks = list(Execution.__table__.columns["target_url_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "target_urls.id"
    assert fks[0].ondelete == "RESTRICT"


def test_executions_status_check_literal_matches_enum_values() -> None:
    # covers: AC-12
    sql = str(_check(Execution.__table__, "status_values").sqltext)
    for v in ("'pending'", "'running'", "'completed'", "'failed'"):
        assert v in sql


def test_executions_items_extracted_non_negative_check() -> None:
    # covers: AC-6
    assert ">= 0" in str(_check(Execution.__table__, "items_extracted_non_negative").sqltext)


def test_executions_error_message_length_check() -> None:
    # covers: AC-6 (truncate at the service layer, enforce at the DB too)
    assert "4000" in str(_check(Execution.__table__, "error_message_length").sqltext)


def test_executions_has_three_composite_indexes() -> None:
    # covers: AC-14 (the three filter axes the execution browser needs)
    idx = {i.name for i in Execution.__table__.indexes}
    assert {
        "ix_executions_workflow_version_id_created_at",
        "ix_executions_target_url_id_created_at",
        "ix_executions_status_created_at",
    } <= idx


def test_executions_composite_indexes_sort_created_at_desc() -> None:
    # covers: AC-14 (newest-first scans are what the admin reads do)
    for name in (
        "ix_executions_workflow_version_id_created_at",
        "ix_executions_target_url_id_created_at",
        "ix_executions_status_created_at",
    ):
        idx = next(i for i in Execution.__table__.indexes if i.name == name)
        ops = (idx.dialect_options.get("postgresql") or {}).get("ops") or {}
        assert ops.get("created_at") == "DESC", f"{name}: created_at is not DESC"


def test_executions_audit_fields() -> None:
    # covers: AC-9
    cols = {c.name: c for c in Execution.__table__.columns}
    assert cols["created_at"].server_default is not None
    assert cols["updated_at"].server_default is not None
    assert cols["updated_at"].onupdate is not None


def test_execution_has_no_soft_delete_column() -> None:
    # covers: AC-9 (append-only history: no soft delete here)
    assert "deleted_at" not in {c.name for c in Execution.__table__.columns}


# ---------- execution_results ----------


def test_execution_results_columns() -> None:
    # covers: AC-7
    cols = {c.name for c in ExecutionResult.__table__.columns}
    assert cols == {"id", "execution_id", "item_index", "payload", "created_at"}


def test_execution_results_payload_is_jsonb_not_null() -> None:
    # covers: AC-7
    col = ExecutionResult.__table__.columns["payload"]
    assert col.nullable is False
    assert col.type.__class__.__name__ == "JSONB"


def test_execution_results_execution_fk_is_cascade() -> None:
    # covers: AC-10 (the one place CASCADE is correct: results die with their execution)
    fks = list(ExecutionResult.__table__.columns["execution_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "executions.id"
    assert fks[0].ondelete == "CASCADE"


def test_execution_results_item_index_non_negative_check() -> None:
    # covers: AC-7
    assert ">= 0" in str(_check(ExecutionResult.__table__, "item_index_non_negative").sqltext)


def test_execution_results_unique_on_execution_and_item_index() -> None:
    # covers: AC-14 (dense per-execution ordering; also the "list results in order" read path)
    uqs = [c for c in ExecutionResult.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any([col.name for col in uq.columns] == ["execution_id", "item_index"] for uq in uqs)


def test_execution_results_id_default_is_uuid_v7() -> None:
    # covers: AC-8 (stable id for feature 18 provenance joins)
    assert _is_uuid_v7_default(ExecutionResult.__table__.columns["id"]) is True


def test_execution_results_has_no_updated_at_or_soft_delete() -> None:
    # covers: AC-7, AC-9 (append-only, never updated, never soft-deleted)
    cols = {c.name for c in ExecutionResult.__table__.columns}
    assert "updated_at" not in cols
    assert "deleted_at" not in cols


# ---------- relationships ----------


def test_execution_results_cascade_delete_orphan() -> None:
    # covers: AC-10 (ORM cascade mirrors the DB CASCADE)
    rel = Execution.__mapper__.relationships["results"]
    assert "delete-orphan" in rel.cascade
    assert rel.passive_deletes is True


def test_execution_relationships_are_raise_on_sql() -> None:
    # covers: project convention (no lazy I/O)
    assert Execution.__mapper__.relationships["results"].lazy == "raise_on_sql"
    assert ExecutionResult.__mapper__.relationships["execution"].lazy == "raise_on_sql"


def test_all_foreign_keys_declared_as_sqlalchemy_fks() -> None:
    # covers: AC-10
    for tbl in (Execution.__table__, ExecutionResult.__table__):
        for col in tbl.columns:
            for fk in col.foreign_keys:
                assert isinstance(fk, ForeignKey)
