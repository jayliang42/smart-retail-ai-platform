# Retail Incident Playbook

## Initial triage

Confirm the affected store, device or SKU, start time, customer impact, and most recent known-good
state. Preserve raw events and request identifiers. Separate facts from hypotheses in the ticket.

## Retry safety

Read operations may be retried after a transient timeout. A write operation may be retried only when
it has an idempotency key and the previous outcome can be checked. Never retry an approval-gated
action by creating a new request identifier.

## Escalation

Escalate when food safety, payment availability, or multiple stores are affected. Include the exact
error, timestamps, relevant event IDs, actions already attempted, and links to supporting evidence.
