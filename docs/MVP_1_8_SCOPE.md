# MVP 1.8 — Conversation-triggered Service Ticket Creation

## Product objective
When a guest reports a booking error and requests a refund, the AI resolves the booking identity, explains the request boundary, asks for explicit confirmation, and automatically creates a traceable human-review ticket from the conversation. Guests must not fill a separate ticket form.

## Supported vertical slice
1. Detect a booking-error/refund request (e.g. “我订错日期了，想退款”).
2. Authenticate the guest and retrieve only bookings owned by that guest.
3. If multiple bookings exist, ask the guest to select one.
4. Re-read the selected booking and its bound cancellation policy.
5. Ask the guest to confirm the specific booking and refund-request intent.
6. Only after explicit confirmation, create one REFUND_REQUEST ticket automatically.
7. Persist booking snapshot, policy snapshot, original request, recent dialogue context, confirmation flag, and operation ID as ticket metadata.
8. Return the ticket ID in the conversation and expose it in the ticket tracking view.
9. Ticket creation is idempotent per guest + operation ID.

## State and safety rules
- No ticket is created before explicit confirmation.
- Rejection creates no ticket.
- A ticket means “refund request submitted for human review”; it does not mean cancellation or refund executed.
- No refund amount or eligibility is promised unless verified by an authoritative transaction system.
- Guest ticket reads are ownership-scoped.
- SQLite stores synthetic demo tickets; real PMS/OTA/payment/staff systems are not connected.

## Ticket schema
The tickets table includes ticket identity, guest ID, booking ID, category, description, priority, status, assignee, idempotency key, timestamps, status history, metadata_json, and operation_id. Metadata contains source, intent, user_confirmed, booking snapshot, cancellation-policy snapshot, recent conversation history, operation ID, human-review requirement, and execution boundary.

## Status lifecycle
SUBMITTED -> ASSIGNED -> PROCESSING -> PENDING_USER -> RESOLVED -> CLOSED; escalation and controlled reopening are supported.

## Out of scope
- Real PMS/OTA booking mutations, cancellation, refund execution, payment operations.
- Production staff authentication/RBAC, external notifications, dispatch and SLA.
- Automatic ticket creation for every generic complaint or on-site service request; these require separate intent-specific confirmation and workflow definitions.

## Acceptance scenarios
1. “我订错日期了，想退款” enters booking/refund flow, not generic booking issue.
2. Multiple owned bookings require explicit selection.
3. Selected booking and bound policy are re-read before confirmation.
4. No ticket exists before confirmation.
5. “确认退款” creates exactly one REFUND_REQUEST ticket.
6. Ticket stores correct guest, booking, operation, request and policy/context metadata.
7. Repeated create with same idempotency key returns the same ticket.
8. “算了” creates no ticket.
9. Guest A cannot read Guest B's ticket.
10. Ticket status transition and audit history are persisted.

## Evidence policy
Synthetic data only. Tests demonstrate application behavior, not actual refund execution, production integration, employee authorization, or real customer service completion.
