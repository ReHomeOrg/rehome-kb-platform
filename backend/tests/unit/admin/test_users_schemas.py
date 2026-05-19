"""Unit tests для KbUser Pydantic schemas (#230)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.api.admin.users_schemas import (
    KbUserCreate,
    KbUserPatch,
)

# ---------------------------------------------------------------------------
# Email validation


def test_email_lowercased_and_stripped() -> None:
    u = KbUserCreate(
        email="  Admin@Example.COM ",
        full_name="Иван",
        role="staff_admin",
    )
    assert u.email == "admin@example.com"


def test_email_invalid_format_raises() -> None:
    with pytest.raises(ValueError, match="Invalid email"):
        KbUserCreate(email="not-an-email", full_name="x", role="staff_admin")


def test_email_too_long_raises() -> None:
    long_email = "a" * 250 + "@x.com"
    with pytest.raises(ValueError, match="255"):
        KbUserCreate(email=long_email, full_name="x", role="staff_admin")


# ---------------------------------------------------------------------------
# Full name validation


def test_full_name_whitespace_only_raises() -> None:
    with pytest.raises(ValueError, match="full_name"):
        KbUserCreate(email="a@b.com", full_name="   ", role="staff_admin")


def test_full_name_stripped() -> None:
    u = KbUserCreate(email="a@b.com", full_name="  Иван  ", role="staff_admin")
    assert u.full_name == "Иван"


# ---------------------------------------------------------------------------
# Permissions validation


def test_permissions_default_empty() -> None:
    u = KbUserCreate(email="a@b.com", full_name="x", role="staff_admin")
    assert u.permissions == []


def test_permissions_dedup_and_strip() -> None:
    u = KbUserCreate(
        email="a@b.com",
        full_name="x",
        role="staff_admin",
        permissions=["  export ", "export", "  ", "review"],
    )
    assert u.permissions == ["export", "review"]


def test_permissions_too_many_raises() -> None:
    with pytest.raises(ValueError, match="Too many"):
        KbUserCreate(
            email="a@b.com",
            full_name="x",
            role="staff_admin",
            permissions=[f"perm{i}" for i in range(60)],
        )


def test_permissions_per_item_too_long_raises() -> None:
    with pytest.raises(ValueError, match="64 chars"):
        KbUserCreate(
            email="a@b.com",
            full_name="x",
            role="staff_admin",
            permissions=["x" * 65],
        )


# ---------------------------------------------------------------------------
# Role / status enums


def test_invalid_role_raises() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        KbUserCreate(email="a@b.com", full_name="x", role="superadmin")  # type: ignore[arg-type]


def test_patch_optional_fields() -> None:
    """Empty PATCH body — все поля None."""
    p = KbUserPatch()
    assert p.role is None
    assert p.status is None
    assert p.permissions is None
    assert p.mfa_enabled is None


def test_patch_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="Input should be"):
        KbUserPatch(status="DELETED")  # type: ignore[arg-type]


def test_patch_permissions_dedup() -> None:
    p = KbUserPatch(permissions=["a", "a", "b"])
    assert p.permissions == ["a", "b"]


# ---------------------------------------------------------------------------
# View schema


def test_view_from_attrs_minimal() -> None:
    """from_attributes=True — ORM-like object → KbUserView."""
    from typing import ClassVar

    from src.api.admin.users_schemas import KbUserView

    class FakeUser:
        id: ClassVar = uuid4()
        email: ClassVar = "a@b.com"
        full_name: ClassVar = "x"
        role: ClassVar = "staff_admin"
        permissions: ClassVar[list[str]] = []
        status: ClassVar = "ACTIVE"
        created_at: ClassVar = "2026-05-19T00:00:00Z"
        last_login_at: ClassVar = None
        mfa_enabled: ClassVar = False

    view = KbUserView.model_validate(FakeUser())
    assert view.email == "a@b.com"
    assert view.role == "staff_admin"
