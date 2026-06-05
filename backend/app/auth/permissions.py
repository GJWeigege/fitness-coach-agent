ROLE_PERMISSIONS: dict[str, set[str]] = {
    "user": {
        "chat:send",
        "profile:read",
        "profile:write",
        "session:read:own",
        "session:manage:own",
        "feedback:write",
    },
    "kb_editor": {
        "chat:send",
        "profile:read",
        "profile:write",
        "session:read:own",
        "session:manage:own",
        "feedback:write",
        "knowledge:read",
        "knowledge:write",
        "knowledge:reindex",
    },
    "admin": {
        "chat:send",
        "profile:read",
        "profile:write",
        "session:read:own",
        "session:manage:own",
        "session:read:all",
        "session:manage:all",
        "feedback:write",
        "knowledge:read",
        "knowledge:write",
        "knowledge:reindex",
        "user:manage",
        "observability:read",
        "benchmark:run",
        "benchmark:read",
    },
}


ALL_PERMISSIONS: frozenset[str] = frozenset(
    permission for permissions in ROLE_PERMISSIONS.values() for permission in permissions
)


def list_roles() -> list[str]:
    return sorted(ROLE_PERMISSIONS.keys())


def get_permissions_for_role(role: str) -> set[str]:
    return ROLE_PERMISSIONS.get(role, set()).copy()


def resolve_user_permissions(role: str, custom_permissions: list[str] | None = None) -> set[str]:
    permissions = get_permissions_for_role(role)
    if custom_permissions:
        permissions.update(custom_permissions)
    return permissions


def validate_custom_permissions(custom_permissions: list[str] | None) -> list[str] | None:
    if custom_permissions is None:
        return None
    invalid = [item for item in custom_permissions if item not in ALL_PERMISSIONS]
    if invalid:
        raise ValueError(f"未知权限: {', '.join(sorted(set(invalid)))}")
    return sorted(set(custom_permissions))
