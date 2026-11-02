"""Identity primitives for the demo-only EES MVP 1.3 flow."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

@dataclass(frozen=True)
class Principal:
    principal_id: str
    customer_id: str
    auth_method: str
    authenticated_at: str
    expires_at: str

def principal_is_valid(principal: Optional[Principal], now: Optional[datetime] = None) -> bool:
    if not isinstance(principal, Principal):
        return False
    try:
        expiry = datetime.fromisoformat(principal.expires_at)
        current = now or datetime.now(timezone.utc)
        if expiry.tzinfo is None:
            return False
        return current < expiry
    except (TypeError, ValueError):
        return False
