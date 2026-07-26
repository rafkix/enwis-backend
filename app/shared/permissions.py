"""Role-based access control (RBAC) utilities.

This module provides helpers for checking whether a ``User`` has the
required role(s) to perform an action.  It is intentionally kept
separate from the auth-dependency layer so that service code and
background tasks can also enforce permissions without requesting
injection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.exceptions import PermissionDeniedException

if TYPE_CHECKING:
    from app.modules.auth.models import User


def user_has_role(user: User, role_name: str) -> bool:
    """Return True if *user* carries the given role."""
    return any(r.name.upper() == role_name.upper() for r in (user.roles or []))


def user_has_any_role(user: User, *role_names: str) -> bool:
    """Return True if *user* carries at least one of the listed roles."""
    return any(user_has_role(user, name) for name in role_names)


def require_role(user: User, role_name: str) -> None:
    """Raise ``PermissionDeniedException`` unless *user* has *role_name*."""
    if not user_has_role(user, role_name):
        raise PermissionDeniedException(
            detail=f"Role '{role_name}' is required",
        )


def require_any_role(user: User, *role_names: str) -> None:
    """Raise ``PermissionDeniedException`` unless *user* has at least one role."""
    if not user_has_any_role(user, *role_names):
        raise PermissionDeniedException(
            detail=f"One of the following roles is required: {', '.join(role_names)}",
        )


def is_admin(user: User) -> bool:
    """Shortcut: does the user have the ADMIN role?"""
    return user_has_role(user, "ADMIN")


def is_teacher_or_admin(user: User) -> bool:
    """Shortcut: does the user have TEACHER or ADMIN role?"""
    return user_has_any_role(user, "TEACHER", "ADMIN")


def require_teacher_or_admin(user: User) -> None:
    """Raise unless the user is a teacher or admin."""
    if not is_teacher_or_admin(user):
        raise PermissionDeniedException(
            detail="Teacher or admin role is required",
        )


def require_admin(user: User) -> None:
    """Raise unless the user is an admin."""
    require_role(user, "ADMIN")


def validate_ownership(
    owner_id,
    current_user_id,
    resource_name: str = "Resource",
) -> None:
    """Raise ``PermissionDeniedException`` if IDs do not match."""
    if str(owner_id) != str(current_user_id):
        raise PermissionDeniedException(
            detail=f"You do not own this {resource_name.lower()}",
        )
