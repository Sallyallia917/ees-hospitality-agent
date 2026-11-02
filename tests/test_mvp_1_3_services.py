import json
from datetime import datetime, timedelta, timezone
import pytest

from services.identity import Principal, principal_is_valid
from services.auth_service import authenticate_demo_user
from services.booking_service import BookingService

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

def principal(customer_id="CUST-001", minutes=20):
    return Principal(
        principal_id=f"DEMO-PRINCIPAL-{customer_id}",
        customer_id=customer_id,
        auth_method="demo_pin",
        authenticated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=minutes)).isoformat(),
    )

def test_demo_auth_success_and_failure():
    ok = authenticate_demo_user("demo_linda", "246810", now=NOW)
    assert ok["ok"] is True
    assert ok["principal"].customer_id == "CUST-001"
    bad = authenticate_demo_user("demo_linda", "000000", now=NOW)
    assert bad["ok"] is False
    assert bad["principal"] is None

def test_expired_or_forged_principal_is_rejected():
    expired = principal(minutes=-1)
    assert principal_is_valid(expired, now=NOW) is False
    assert principal_is_valid({"customer_id":"CUST-001","is_authenticated":True}, now=NOW) is False

def test_unauthenticated_user_cannot_search_or_read():
    service = BookingService()
    assert service.search_my_bookings(None)["status"] == "unauthenticated"
    assert service.get_my_booking(None, "DEMO-BOOKING-1001")["status"] == "unauthenticated"

def test_customer_can_only_read_owned_booking():
    service = BookingService()
    own = service.get_my_booking(principal(), "DEMO-BOOKING-1001")
    other = service.get_my_booking(principal(), "DEMO-BOOKING-2001")
    assert own["status"] == "ok"
    assert own["booking"]["room_type"] == "山景大床房"
    assert other["status"] == "not_found"
    assert other["booking"] is None

def test_search_defaults_to_at_most_three_owned_bookings():
    service = BookingService()
    result = service.search_my_bookings(principal())
    assert result["status"] == "ok"
    assert len(result["matched_bookings"]) == 3
    assert all(x["booking_id"] != "DEMO-BOOKING-2001" for x in result["matched_bookings"])

def test_search_can_filter_by_room_type_and_date():
    service = BookingService()
    result = service.search_my_bookings(principal(), {"room_type":"双床"})
    assert len(result["matched_bookings"]) == 1
    assert result["matched_bookings"][0]["booking_id"] == "DEMO-BOOKING-1003"

def test_unknown_filter_is_rejected():
    result = BookingService().search_my_bookings(principal(), {"sql":"select *"})
    assert result["status"] == "invalid_filters"
    assert result["matched_bookings"] == []

def test_order_detail_includes_booking_time_bound_policy_version():
    service = BookingService()
    result = service.get_my_booking(principal(), "DEMO-BOOKING-1001")
    assert result["cancellation_policy"]["policy_id"] == "POLICY-REFUND-001-V1"
    assert result["cancellation_policy"]["version"] == 1
    assert result["cancellation_policy"]["timezone"] == "Asia/Shanghai"
    assert len(result["cancellation_policy"]["windows"]) == 3

def test_booking_detail_includes_related_property():
    result = BookingService().get_my_booking(principal(), "DEMO-BOOKING-1002")
    assert result["property"]["property_name"] == "示例城市酒店"
    assert "早餐厅" in result["property"]["facilities"]

def test_sensitive_customer_fields_are_not_returned():
    result = BookingService().get_my_booking(principal(), "DEMO-BOOKING-1001")
    serialized = json.dumps(result, ensure_ascii=False)
    assert "demo_pin" not in serialized
    assert "138****1001" not in serialized

def test_audit_event_does_not_contain_credentials():
    service = BookingService()
    service.get_my_booking(principal(), "DEMO-BOOKING-1001")
    event = service.audit_events[-1]
    assert "demo_pin" not in event
    assert event["result_status"] == "ok"

def test_search_result_does_not_expose_customer_id():
    result = BookingService().search_my_bookings(principal())
    assert all("customer_id" not in x for x in result["matched_bookings"])

class BrokenRepository:
    def list_bookings(self):
        raise RuntimeError("storage unavailable")

def test_repository_error_fails_closed():
    service = BookingService(repository=BrokenRepository())
    result = service.get_my_booking(principal(), "DEMO-BOOKING-1001")
    assert result["status"] == "tool_error"
    assert result["booking"] is None
