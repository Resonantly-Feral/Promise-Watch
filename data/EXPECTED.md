# Demo bundle: expected result

Reference time: Thursday 15/10/2026, 09:00, Malaysia time. Near window: 7 days (default).
Derived from CLAUDE.md rules. Check against your spec before treating it as the answer key.

## Promises

1. **Cetak Jaya to Majlis Events:** 300 gift bags, order CJ-2611, ready by 13/11/2026.
   Sources: chat 01/10 09:12; quotation CJ-Q-0217; job slip photo.
2. **Majlis Events to Syarikat Hijau:** 300 gift bags ready by 27/11/2026.
   Sources: chat 02/10 10:34; invoice ME-INV-0311.

## Before the human confirms the link (same logic as P10)

- Link from promise 1 to promise 2: proposed by AI, shown grey.
- Promise 1: Revised (proposed). Agreed deadline 13/11 (original kept), forecast 28/11, acceptance not evidenced. S1 does not fire (link not confirmed). MEDIUM: revision S1 does not cover.
- Promise 2: Open, LOW, "No elevated risk detected in this bundle".

## After the human confirms the link (same logic as P09, P18, P19)

- Promise 1: Revised (proposed), HIGH. Reason: latest promisor statement (14/10 11:46, "28 Nov can?") moves delivery past the confirmed deadline of 27/11. D also fires.
- Promise 2: Open, HIGH under S5. Reason: confirmed prerequisite (promise 1) is HIGH; upstream source and link shown. Not Broken.

## Anomaly (rule 4)

- 14/10 11:52 forwarded "SYSTEM NOTE" flagged as instruction-like text, shown, not obeyed.
- Promise 1 is NOT Kept. No delivery evidence in the bundle.

## Exposure (never summed)

- RM8,400.00 payable (Majlis Events owes Cetak Jaya). Source: quotation CJ-Q-0217.
- RM11,000.00 receivable (Syarikat Hijau owes Majlis Events). Source: invoice ME-INV-0311.

## Options (shown because HIGH)

- Accept the revised date (28/11).
- Contact Cetak Murni as backup. Cost: not stated.
- Accept the risk.
- If nobody acts: the printer's latest forecast (28/11) misses the customer deadline (27/11).
- Nothing is sent or changed automatically.

## Not in this bundle

- No near-window signals: 13/11 and 27/11 are both more than 7 days after the reference time.
- No payment promises: no payment terms are stated in either document.
