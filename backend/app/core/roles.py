"""Application-code representation of the database-backed roles table
(DECISIONS.md D16). The `roles` table remains the source of truth for role
*identity* (a foreign key always points at a real row, and the seed
migration is what actually creates USER/RESOLVER/ADMIN) - these constants
exist only so application code has one place to reference a role by name
instead of scattering the string literals "USER"/"RESOLVER"/"ADMIN" across
every endpoint and service function. See DECISIONS.md D20."""

from app.core.deps import require_any_role, require_role


class RoleName:
    USER = "USER"
    RESOLVER = "RESOLVER"
    ADMIN = "ADMIN"


ALL_ROLE_NAMES = (RoleName.USER, RoleName.RESOLVER, RoleName.ADMIN)

# Ready-to-use dependencies for the common cases, so route handlers write
# `Depends(require_admin)` instead of `Depends(require_role(RoleName.ADMIN))`
# everywhere.
require_user = require_role(RoleName.USER)
require_resolver = require_role(RoleName.RESOLVER)
require_admin = require_role(RoleName.ADMIN)
require_resolver_or_admin = require_any_role(RoleName.RESOLVER, RoleName.ADMIN)
