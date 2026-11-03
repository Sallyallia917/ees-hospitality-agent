# MVP 1.3.1 — Conversational Read-only Booking Lookup

## Goal
Connect the existing Streamlit chat input to the MVP 1.3 authenticated booking service so a guest can ask a personal booking question, receive an authorized lookup, and get a grounded natural-language response.

## Request flow
1. Streamlit passes the current message, authenticated Principal, recent intent history, and session context to ConversationOrchestrator.
2. Deterministic rules identify booking references and booking-related questions. LLM classification remains advisory and does not authorize access.
3. The orchestrator checks Principal validity before invoking a booking service method.
4. BookingService performs its own authentication and booking-ownership checks.
5. Only allowlisted fields returned by BookingService are passed to the response generator.
6. The response generator uses the configured LLM when available and falls back to deterministic wording on missing configuration or model errors.
7. The UI displays the answer, structured booking fields, and audit identifier.

## Security and business boundaries
- Booking IDs are identifiers, not credentials.
- No order data is returned before a valid demo Principal is present.
- BookingService remains the authorization boundary and does not trust model output.
- A booking owned by another customer is indistinguishable from a nonexistent booking to the caller.
- PINs and unrelated customer fields are not sent to the LLM.
- Active booking context is cleared when authentication changes.
- The feature is read-only. Cancellation, refunds, date changes, room changes, and service-ticket creation remain unsupported.
- Demo JSON data and demo PIN authentication are not production integrations or production-grade identity controls.

## Current interaction scope
- Explicit DEMO-BOOKING reference + question: direct authorized detail lookup.
- Booking-related question without a reference: search at most three of the authenticated user's bookings.
- Multiple matches: ask the user to identify the booking using its booking reference, date, or room type.
- Follow-up phrasing such as "那早餐包含吗" may reuse the active booking only after that booking was successfully authorized in the current authenticated session.
- Follow-up selection by ordinal (for example, "第二笔") and broad natural-language filter extraction are not included yet.

## Validation
Automated tests cover reference routing, login requirement, owner lookup, cross-customer denial, multi-booking clarification, and authorized follow-up. GitHub Actions status must be checked independently. Browser acceptance is a separate manual activity and is not implied by passing unit tests.
