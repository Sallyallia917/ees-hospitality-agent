# MVP 1.8 — Context-aware Service Ticket Agent

## Product objective
Move from a read-only booking assistant to a demonstrable service-request workflow: understand conversational follow-ups, create a traceable ticket, and support controlled status updates.

## In scope for this slice
- Dialogue-act recognition: new request, supplement, correction, confirmation/rejection, status query, history reference, complaint, clarification.
- SQLite persistence for synthetic service tickets.
- Ticket ownership checks for guest reads; staff-only list/read path is explicit in the service API.
- Idempotent ticket creation using a caller-supplied message key.
- Deterministic status transition validation and append-only status history.
- Reopen a resolved/closed ticket to PROCESSING when a guest reports the issue is unresolved.

## Booking status display
- Show the current synthetic booking status (`confirmed`, `completed`, `cancelled`) in the authenticated booking detail view.
- Booking status is read-only in MVP 1.8; no cancellation, refund, check-in or booking mutation is performed.

## Status model
SUBMITTED -> ASSIGNED -> PROCESSING -> PENDING_USER -> RESOLVED -> CLOSED
Escalation is available from active workflow states. RESOLVED/CLOSED can return to PROCESSING for a verified follow-up.

## Explicitly out of scope
- Real hotel PMS/OTA/CRM/ticketing integrations.
- Real staff identity, production RBAC, external notifications or dispatch. The demo workbench is gated by a local PIN only.
- Automated cancellation, refund, room change or inventory mutation.
- Production SLA commitments, analytics dashboards, multi-property tenancy.

## Acceptance scenarios
1. New maintenance/cleaning/room-service request can be stored.
2. Same message idempotency key does not create a duplicate.
3. Guest A cannot read Guest B's ticket.
4. Staff path can list tickets and update status.
5. Illegal status transition is rejected.
6. Status history records actor, timestamp and note.
7. Resolved issue can be reopened after guest says it remains unresolved.
8. Dialogue act classifier distinguishes history reference, correction, supplement and status query.

## Evidence policy
All data is synthetic. Automated tests prove module behavior only; they do not prove real hotel integration, real employee authorization, production availability, or actual service resolution.
