"""Covers `app.domains.workflows.models` (spec 0003).

The models are the single source of truth for the migration feature 5 will ship.
These tests lock the shape (columns, nullability, defaults), the FK policies
(AC-3, AC-4, AC-10), the lifecycle CHECK constraints (AC-12), the audit fields
(AC-9), and the indexes the admin reads depend on (AC-14), including the
partial unique on `(website_id, name) WHERE deleted_at IS NULL`.
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint

from app.core.database import Base
from app.domains.workflows.models import ScrapingWorkflow, WorkflowVersion


def _check(table: object, suffix: str) -> CheckConstraint:
    """Find a CHECK by the short `name=...` the model declares.

    The naming convention in `app.core.database`
    (`ck_%(table_name)s_%(constraint_name)s`) renames `.name` at attach time,
    and the table name itself can contain underscores, so a split-based strip
    is fragile. Match on endswith instead.
    """
    for c in table.constraints:  # type: ignore[attr-defined]
        if isinstance(c, CheckConstraint) and c.name and c.name.endswith("_" + suffix):
            return c
    raise AssertionError(
        f"CHECK ending in `_{suffix}` not found on {getattr(table, 'name', table)}"
    )


def _is_uuid_v7_default(col) -> bool:  # type: ignore[no-untyped-def]
    """A column's default produces a UUIDv7.

    SQLAlchemy wraps a callable default; depending on version, the wrapper
    takes a `ctx` argument. Try both signatures.
    """
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
    assert "scraping_workflows" in Base.metadata.tables
    assert "workflow_versions" in Base.metadata.tables


# ---------- scraping_workflows ----------


def test_scraping_workflows_columns() -> None:
    # covers: AC-2, AC-9
    cols = {c.name for c in ScrapingWorkflow.__table__.columns}
    assert cols == {
        "id",
        "website_id",
        "name",
        "description",
        "current_version_id",
        "status",
        "created_at",
        "updated_at",
        "deleted_at",
    }


def test_scraping_workflows_nullability() -> None:
    # covers: AC-3 (website_id NOT NULL), AC-4 (current_version_id nullable), AC-9 (deleted_at nullable)
    cols = {c.name: c for c in ScrapingWorkflow.__table__.columns}
    assert cols["website_id"].nullable is False
    assert cols["name"].nullable is False
    assert cols["description"].nullable is True
    assert cols["current_version_id"].nullable is True
    assert cols["status"].nullable is False
    assert cols["created_at"].nullable is False
    assert cols["updated_at"].nullable is False
    assert cols["deleted_at"].nullable is True


def test_scraping_workflows_id_default_is_uuid_v7() -> None:
    # covers: AC-8
    assert _is_uuid_v7_default(ScrapingWorkflow.__table__.columns["id"]) is True


def test_scraping_workflows_status_default_is_active() -> None:
    # covers: AC-12
    status = ScrapingWorkflow.__table__.columns["status"]
    assert status.default is not None
    assert status.default.arg == "active"
    assert status.server_default is not None
    assert status.server_default.arg == "active"


def test_scraping_workflows_website_id_fk_is_restrict() -> None:
    # covers: AC-3, AC-10
    fks = list(ScrapingWorkflow.__table__.columns["website_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "websites.id"
    assert fks[0].ondelete == "RESTRICT"


def test_scraping_workflows_current_version_fk_is_restrict_and_use_alter() -> None:
    # covers: AC-4, AC-10 (and the Follow-up on breaking the FK cycle at migration time)
    fks = list(ScrapingWorkflow.__table__.columns["current_version_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "workflow_versions.id"
    assert fks[0].ondelete == "RESTRICT"
    assert fks[0].use_alter is True


def test_scraping_workflows_check_constraints_present() -> None:
    # covers: AC-5 (name/description length), AC-12 (status values)
    for suffix in ("name_length", "description_length", "status_values"):
        _check(ScrapingWorkflow.__table__, suffix)


def test_scraping_workflows_name_length_check_literal() -> None:
    # covers: AC-5 (length 1..200)
    assert "1 AND 200" in str(_check(ScrapingWorkflow.__table__, "name_length").sqltext)


def test_scraping_workflows_status_check_literal_matches_enum_values() -> None:
    # covers: AC-12
    sql = str(_check(ScrapingWorkflow.__table__, "status_values").sqltext)
    assert "'active'" in sql
    assert "'inactive'" in sql


def test_scraping_workflows_index_on_website_id() -> None:
    # covers: AC-14
    idx = {i.name for i in ScrapingWorkflow.__table__.indexes}
    assert "ix_scraping_workflows_website_id" in idx


def test_scraping_workflows_partial_unique_on_website_id_name() -> None:
    # covers: AC-14 (one workflow name per website while the row is live; re-registrable after soft delete)
    uq_name = "uq_scraping_workflows_website_id_name_active"
    idx = {i.name: i for i in ScrapingWorkflow.__table__.indexes}
    assert uq_name in idx
    where = (idx[uq_name].dialect_options.get("postgresql") or {}).get("where")
    assert idx[uq_name].unique is True
    assert where is not None
    assert "deleted_at IS NULL" in str(where)


def test_scraping_workflows_audit_fields_server_defaults_and_onupdate() -> None:
    # covers: AC-9
    cols = {c.name: c for c in ScrapingWorkflow.__table__.columns}
    assert cols["created_at"].server_default is not None
    assert cols["updated_at"].server_default is not None
    assert cols["updated_at"].onupdate is not None


# ---------- workflow_versions ----------


def test_workflow_versions_columns() -> None:
    # covers: AC-2
    cols = {c.name for c in WorkflowVersion.__table__.columns}
    assert cols == {
        "id",
        "workflow_id",
        "version_number",
        "status",
        "config",
        "published_at",
        "archived_at",
        "created_at",
        "updated_at",
    }


def test_workflow_versions_config_is_jsonb_not_null() -> None:
    # covers: AC-5 (one JSONB document, no separate extraction_rules table)
    col = WorkflowVersion.__table__.columns["config"]
    assert col.nullable is False
    assert col.type.__class__.__name__ == "JSONB"


def test_workflow_versions_workflow_fk_is_restrict() -> None:
    # covers: AC-10
    fks = list(WorkflowVersion.__table__.columns["workflow_id"].foreign_keys)
    assert len(fks) == 1
    assert fks[0]._colspec == "scraping_workflows.id"
    assert fks[0].ondelete == "RESTRICT"


def test_workflow_versions_status_default_is_draft() -> None:
    # covers: AC-12
    status = WorkflowVersion.__table__.columns["status"]
    assert status.default is not None
    assert status.default.arg == "draft"
    assert status.server_default is not None
    assert status.server_default.arg == "draft"


def test_workflow_versions_status_check_literal_matches_enum_values() -> None:
    # covers: AC-12
    sql = str(_check(WorkflowVersion.__table__, "status_values").sqltext)
    for v in ("'draft'", "'published'", "'archived'"):
        assert v in sql


def test_workflow_versions_version_number_check_literal() -> None:
    # covers: AC-14 (version numbers start at 1 and increase)
    assert ">= 1" in str(_check(WorkflowVersion.__table__, "version_number_positive").sqltext)


def test_workflow_versions_unique_on_workflow_id_version_number() -> None:
    # covers: AC-14, AC-16 (the concurrency rule depends on this constraint)
    uqs = [c for c in WorkflowVersion.__table__.constraints if isinstance(c, UniqueConstraint)]
    assert any([col.name for col in uq.columns] == ["workflow_id", "version_number"] for uq in uqs)


def test_workflow_versions_index_on_workflow_id_status() -> None:
    # covers: AC-14 (the "published versions of this workflow" lookup)
    idx = {i.name for i in WorkflowVersion.__table__.indexes}
    assert "ix_workflow_versions_workflow_id_status" in idx


def test_workflow_versions_id_default_is_uuid_v7() -> None:
    # covers: AC-8
    assert _is_uuid_v7_default(WorkflowVersion.__table__.columns["id"]) is True


def test_workflow_versions_audit_fields() -> None:
    # covers: AC-9
    cols = {c.name: c for c in WorkflowVersion.__table__.columns}
    assert cols["created_at"].server_default is not None
    assert cols["updated_at"].server_default is not None
    assert cols["updated_at"].onupdate is not None


def test_workflow_version_has_no_soft_delete_column() -> None:
    # covers: AC-9 (immutable records are not soft-deletable; soft delete lives only on the aggregate root)
    assert "deleted_at" not in {c.name for c in WorkflowVersion.__table__.columns}


# ---------- relationships ----------


def test_scraping_workflows_versions_relationship_is_raise_on_sql() -> None:
    # covers: project convention: no lazy I/O, every load is explicit
    rel = ScrapingWorkflow.__mapper__.relationships["versions"]
    assert rel.lazy == "raise_on_sql"


def test_workflow_version_workflow_relationship_is_raise_on_sql() -> None:
    rel = WorkflowVersion.__mapper__.relationships["workflow"]
    assert rel.lazy == "raise_on_sql"


# ---------- FK targets (bare existence of foreign_keys attribute) ----------


def test_all_foreign_keys_declared_as_sqlalchemy_fks() -> None:
    # covers: AC-10 (every cross-row link is a declared FK, not an app-level pointer)
    for tbl in (ScrapingWorkflow.__table__, WorkflowVersion.__table__):
        for col in tbl.columns:
            for fk in col.foreign_keys:
                assert isinstance(fk, ForeignKey)
