"""Read-only JSON repository for synthetic demo bookings."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class BookingRepository:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir) if data_dir else ROOT / "data"

    def _load(self, filename):
        return json.loads((self.data_dir / filename).read_text(encoding="utf-8"))

    def list_bookings(self):
        return self._load("demo_bookings.json")

    def list_customers(self):
        return self._load("demo_customers.json")

    def get_property(self, property_id):
        return next((x for x in self._load("demo_properties.json") if x["property_id"] == property_id), None)

    def get_policy(self, policy_id):
        return next((x for x in self._load("demo_cancellation_policies.json") if x["policy_id"] == policy_id), None)
