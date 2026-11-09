# MVP 1.9 — MECE Unified Service Ticket Orchestration

## Product goal
Extend the MVP 1.8 conversation-triggered refund ticket into a reusable, order-linked service ticket workflow for booking issues, on-site stay services, complaints/experience feedback, and invoice requests. The guest describes the issue in conversation; the system identifies the booking, collects necessary details, repeats the request, and creates a local demo ticket only after explicit confirmation.

## Primary category taxonomy (MECE)

The primary category describes the **business responsibility / nature of the request**, not the physical location or the team that eventually handles it.

| Primary category | Inclusion boundary | Exclusion / routing boundary | Examples |
|---|---|---|---|
| TRANSACTION_ORDER (交易与订单) | Booking facts, booking errors, cancellation/refund and other order lifecycle matters | Do not use for in-stay repair/cleaning or dissatisfaction without an order mutation request | Wrong dates/room type, booking error, refund request |
| STAY_SERVICE (住宿服务) | A guest asks the property to perform or arrange a concrete service during the stay | A report of poor experience, dissatisfaction, or demand for accountability goes to COMPLAINT_EXPERIENCE | Clean room now, repair AC, deliver towels, add bedding |
| COMPLAINT_EXPERIENCE (投诉与体验) | The guest reports dissatisfaction, poor service/conditions, or requests investigation/accountability | A neutral request for cleaning/repair without dissatisfaction goes to STAY_SERVICE | Dirty room complaint, noisy room complaint, merchant attitude complaint, facility impact complaint |
| BILLING_DOCUMENT (票据与财务) | Invoice, receipt, billing and payment-document requests | Do not use for refund/cancellation eligibility; those remain TRANSACTION_ORDER | Invoice title/tax ID, receipt |
| CONSULTATION_OTHER (咨询与其他) | Information requests and residual cases that do not require an operational ticket | Normal FAQ questions should remain in knowledge retrieval and normally do not create a ticket | Is there an elevator? Check-in policy question |

### Classification dimensions kept separate
- category: exactly one primary business category above.
- issue_type: specific problem, e.g. BOOKING_ERROR, CANCELLATION_REFUND, ROOM_CLEANING, ROOM_MAINTENANCE, ROOM_AMENITY, NOISE, HYGIENE_COMPLAINT, MERCHANT_COMPLAINT, INVOICE.
- handling_channel: downstream handling route, e.g. ON_SITE, MANAGER_REVIEW, BACK_OFFICE, MULTI_TEAM. This is not a primary category.
- issue_location: where the problem occurs, e.g. GUEST_ROOM, BATHROOM, PUBLIC_AREA, FRONT_DESK, UNKNOWN. It is not a category.
- booking_id: the booking the ticket refers to. Booking identity must be selected and revalidated.
- priority: operational urgency, independent of category.

This resolves the dimension collision: cleaning, AC repair, and towel delivery are STAY_SERVICE; a dirty-room complaint is COMPLAINT_EXPERIENCE with issue_type=HYGIENE_COMPLAINT and may be routed to on-site staff plus a manager; a neutral elevator availability question is consultation, not a ticket. “客房” is a location (issue_location=GUEST_ROOM), not a primary category. “现场服务” is a handling channel, not a primary category. “没有电梯” without context is ambiguous, so the assistant asks whether the guest is asking about a facility or reporting an impact.

## Conversation workflows
1. Refund request: preserve MVP 1.8 explicit confirmation and create TRANSACTION_ORDER / CANCELLATION_REFUND. No actual cancellation or refund.
2. Booking issue: identify and revalidate booking, collect/correct issue details, confirm, create TRANSACTION_ORDER / BOOKING_ERROR. No booking mutation.
3. Stay service: identify booking, confirm the requested work, create STAY_SERVICE with an issue subtype such as ROOM_MAINTENANCE or ROOM_CLEANING. Ticket creation does not dispatch staff.
4. Complaint: identify booking, capture complaint details, confirm, create COMPLAINT_EXPERIENCE. Human investigation remains required.
5. Invoice: identify booking, collect invoice title and applicable tax ID/email details, confirm, create BILLING_DOCUMENT / INVOICE. The system does not issue an invoice.

## Safety and data boundaries
- No booking lookup or ticket creation before demo identity authentication.
- The selected booking is re-read before ticket creation.
- No ticket is created before explicit confirmation; rejection creates none.
- Ticket creation is idempotent and ownership-scoped.
- Tickets are SQLite demo records, not production CRM/PMS/OTA tickets.
- No actual refund, booking change, room repair, cleaning dispatch, or invoice issuance is performed.
- “没有电梯” is not automatically treated as complaint or service request; the assistant clarifies context.

## Compatibility
Legacy ticket labels are normalized on creation:
- REFUND_REQUEST / BOOKING_ISSUE -> TRANSACTION_ORDER
- CLEANING / ROOM_SERVICE / MAINTENANCE -> STAY_SERVICE
- COMPLAINT -> COMPLAINT_EXPERIENCE
- OTHER -> CONSULTATION_OTHER

The original input label is converted into an issue_type so old call sites do not lose semantic detail.

## Acceptance coverage
- Primary categories are mutually exclusive and exhaustive for supported ticket scenarios.
- Complaint vs. neutral service request is separated.
- Facility question vs. facility-impact complaint is clarified.
- Multi-booking selection remains explicit.
- No ticket before confirmation; rejection creates no ticket.
- Invoice details are collected before confirmation.
- Ticket metadata stores category, issue type, issue location, handling channel, booking snapshot, confirmation and execution boundary.
