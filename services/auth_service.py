"""Demo-only authentication adapter. Never use these credentials in production."""
import json
import hmac
from datetime import datetime, timedelta, timezone
from pathlib import Path
from services.identity import Principal

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TTL_MINUTES = 20

def authenticate_demo_user(account_id: str, demo_pin: str, data_dir: Path = None, now=None):
    if not account_id or not demo_pin:
        return {"ok": False, "principal": None, "error": "invalid_credentials"}
    base = data_dir or ROOT / "data"
    customers = json.loads((base / "demo_customers.json").read_text(encoding="utf-8"))
    record = next((x for x in customers if hmac.compare_digest(str(x.get("demo_account_id","")), str(account_id))), None)
    if not record or not hmac.compare_digest(str(record.get("demo_pin","")), str(demo_pin)):
        return {"ok": False, "principal": None, "error": "invalid_credentials"}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    principal = Principal(
        principal_id=f"DEMO-PRINCIPAL-{record['customer_id']}",
        customer_id=record["customer_id"],
        auth_method="demo_pin",
        authenticated_at=current.isoformat(),
        expires_at=(current + timedelta(minutes=DEFAULT_TTL_MINUTES)).isoformat(),
    )
    return {"ok": True, "principal": principal, "error": None}
