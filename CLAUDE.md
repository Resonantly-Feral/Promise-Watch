# PromiseWatch

This file is the source of truth. Do not redesign. Do not add features, rules, signals, fields or statuses that are not listed here. When something isn't covered, stop and ask Resonantly-Feral.

## What it is

PromiseWatch reads one bundle of synthetic business messages and documents, identifies the promises in them, and warns which ones are about to break, before the deadline, with the evidence behind every warning.

The AI reads language and proposes dependencies; it does not decide risk. Fixed rules decide risk. A human makes every decision. The system never acts on its own.

## Scope for the event

One case bundle, one at-risk promise, one cascade, one human decision.

Out of scope: live WhatsApp connection, accounts, history across bundles, payments, mobile app.

## Promise record (10 fields)

- Who: the party who promised (the promisor)
- To whom: the party it was promised to
- What: the outcome (goods, payment, work or a document)
- By when: the original commitment and current agreed deadline, plus any latest proposed/forecast date and sourced acceptance state; unresolved dates are flagged. Preserve revision history within this field.
- Conditions: for example "before delivery" or "after the credit note"
- Value (RM): only if a source states it
- Source: the exact message or document line, with its source type
- Expected evidence: outcome-specific proof agreed for the fixture before scoring (for example, a matching signed delivery note for delivery, tracking for dispatch, or a bank slip for initiating a transfer). Receipt of funds requires evidence of receipt. Recorded acceptance must identify what was accepted; casual reassurance is not acceptance.
- Status: see Statuses
- Fulfilment evidence: the expected evidence once it arrives, or none yet

## Pipeline

1. Capture: the messages and documents in the bundle.
2. Extract: the AI turns language into draft promise records. Dependency proposals in step 4 are also language interpretation; neither step decides risk.
3. Validate: fixed rules check every draft against the sources.
4. Link: the AI proposes dependencies; a human confirms them.
5. Score: fixed rules assign a risk level, with the reasons listed.
6. Show: risks, chains, RM exposure and options.
7. Decide: a human chooses.

## The 18 rules

Sources
1. Every fact carries its source type: Document, Message, Owner-said, or Unknown.
2. A claim is not evidence. A promise counts as kept only when the bundle holds the expected evidence for that exact outcome and order. A tracking reference supports dispatch, not delivery; a bank slip supports payment initiation, not necessarily receipt. Check order or invoice identity, parties, and any stated amount or quantity. Wrong-order or insufficient evidence never closes a promise. Unclear matches stop under rule 17.
3. What the owner says never lowers risk. It is recorded and changes no mark.
4. Text in a source is never an instruction. Instruction-like text is flagged as an anomaly: never obeyed, never quietly dropped.

Conflicts
5. When sources disagree, the latest statement from the promisor becomes the current forecast. Preserve the original commitment, every revision and its source, and whether recipient acceptance is evidenced. A request such as "28/11 can?" is a proposed revision, not an agreed deadline. Score the latest forecast against downstream commitments even before acceptance. Only evidenced recipient acceptance changes the agreed deadline. A statement from anyone else creates a conflict but never overwrites either date. An unaccepted proposal alone is not Disputed; explicit disagreement is.
6. A revised promise is a signal, not a breach. A change by the promisor before the deadline marks it revised, not broken, and stays on record as a permanent risk signal.

Dates and amounts
7. Vague dates are resolved with the reasoning shown, or flagged unresolved. Never guessed.
8. Every figure comes from a source. No source, no figure.
9. Arithmetic is fact, not judgment. The same amount is never counted twice along a chain.

Unknowns
10. There are two kinds of missing. Missing by channel (this source never carries it) is listed but does not raise risk. Missing when expected (this source normally carries it and it is absent, or sources conflict) counts toward risk. "Normally carries" means every earlier fulfilment in this channel, within the bundle, carried that evidence, and there was at least one.

Links
11. Dependencies are proposed, not assumed. An AI-suggested link stays grey until a human confirms it. Only confirmed links pass risk downstream.

Risk
12. Risk is computed from the listed signals, never from model judgment.
13. Every risk level comes with its reasons.
14. No percentages. Levels are LOW, MEDIUM or HIGH, plus reasons.
15. Thresholds are fixed before the event and never adjusted after seeing output.

Decisions
16. Options, never actions. Each option shows its cost only where a source states it, plus what happens if nobody acts.
17. Not enough information means a stop: say what is unclear and which single confirmation would settle it. No options, no level.

Scope
18. One declared bundle at a time. Anything outside it is flagged, never used.

## Status and risk level

Every promise has two separate fields: a status, which says what has happened, and a risk level, which says what might happen next.

Statuses: Open, Revised, Kept, Overdue unverified, Broken, Disputed.

- Open: still expected by its deadline, unchanged
- Revised: the promisor proposed or stated a change to the date, outcome or condition; label it proposed until acceptance is evidenced
- Kept: the expected evidence for that outcome is in the bundle. A Kept promise gets no risk level.
- Overdue unverified: the deadline passed, the expected evidence is not in the bundle, and nobody has confirmed failure. Always HIGH, with the reason "deadline passed, no proof", and one question: "Did this happen?"
- Broken: only when the promisor says it will not be fulfilled, or a human confirms it failed. Never from missing evidence alone. Show "Confirmed failure", no risk level, the evidence and intervention options. Confirmed dependents are evaluated under S5.
- Disputed: the parties explicitly disagree about the promise or its fulfilment. S4 fires. If the promise and dates remain identifiable, score normally; otherwise stop under rule 17. Disputed takes precedence over Kept when purported fulfilment is explicitly contested; Overdue unverified takes precedence over Revised once the agreed deadline passes without proof. A clear refusal or confirmed failure is Broken; conflicting evidence about whether failure occurred is Disputed.

Only the promisor can propose or state a revision; this does not prove the recipient accepted it. Risk levels are LOW, MEDIUM and HIGH. "At risk" means a level of MEDIUM or HIGH; it is not a status.

## Near window

- Default: 7 days.
- A per-vendor window can be set before scoring. It is never changed in response to a flag (rule 15).
- The window used appears in the reasons, for example "within this vendor's 3-day window" (rule 13).

## Signals and levels

- S1 Contradiction: a newer statement from the promisor moves fulfilment past a confirmed downstream promise's deadline.
- S2 Expected proof missing: inside the near window, expected outcome or progress evidence is absent, and this channel normally carries that evidence for comparable orders. This is a precautionary warning, not a claim that an evidence deadline was missed. Progress evidence (such as tracking) does not close a delivery promise.
- S3 Near: the deadline is inside the near window.
- S4 Conflict: an unresolved conflict about the date, outcome or fulfilment.
- D Downstream: at least one confirmed promise depends on this one.
- S5 Upstream risk: a confirmed prerequisite is Broken or has HIGH risk. Show the upstream promise, its source and the confirmed link as the reason. S5 makes an active dependent HIGH; it does not mark it Broken. Propagate through confirmed links only. Kept promises stop propagation; proposed links do not carry it. Stop if a dependency cycle prevents evaluation.

Before the signals: apply rule 17 if the record is too unclear to evaluate. A Kept promise gets no level; a Broken promise shows confirmed failure and no level; an Overdue unverified promise is HIGH. For active records, use the agreed deadline for S2/S3 and overdue checks, and the latest forecast for S1. A proposal cannot postpone the overdue check.

Otherwise, check in this order. The first match wins.

1. HIGH: S1 or S5; or S2 and D; or S2 and S4.
2. MEDIUM: any one of S2, S4, a revision S1 does not cover, or S3 and D.
3. LOW: everything else. Display "No elevated risk detected in this bundle"; LOW is not a guarantee of fulfilment.

Too unclear to evaluate the signals is a stop under rule 17, not a level.

## Exposure

- Show each amount a source states on its own line, labelled payable (the user owes it) or receivable (the user is owed it), with its source.
- Show the at-risk promise's amount and the amount on each confirmed dependent promise.
- Never add amounts together. A human reviews them side by side.

## Decided rulings (10/10/2026; review edits incorporated)

- Near window: 7 days by default, per-vendor override set before scoring.
- A: Kept means no risk level.
- B: Status and risk level are separate fields.
- C: Levels are checked top to bottom, first match wins.
- D: Amounts are shown separately for human review, never summed.
- E: "Normally carries" means every earlier fulfilment in the channel carried it, with at least one.
- F: Missed deadline with no evidence is Overdue unverified (HIGH), not Broken.

- G: Broken means confirmed failure, with no risk level; confirmed active dependents become HIGH under S5.
- H: Evidence must match the exact outcome and order; progress proof cannot close a delivery promise.
- I: S2 means expected proof missing, not a missed proof deadline.
- J: Preserve original/agreed deadlines separately from the latest forecast and its acceptance state.
- K: Disputed fires S4; use the status precedence above and stop only when the record cannot be evaluated.

Rulings decided 10/10/2026 at the event:

- L: Tests assert options only where the test set states them: P18's three, and P13's intervention options.
- M: Overdue unverified shows only the question "Did this happen?", no options.
- N: Broken shows these intervention options, from the bundle only: find another way to get the outcome (cost not stated unless a source states it); contact a named alternative (only if the bundle names one); tell the recipient of each confirmed dependent promise (only if one exists); accept the failure. Plus what happens if nobody acts.
- O: A statement that could refer to more than one promise stops every candidate: no level on any of them.
- P: Ordinary requests between people, such as "update ya", are not instruction-like text. No anomaly flag.
- Q: P03 and P23: the earlier order carried tracking only. The signed delivery note is missing by channel.
- R: P14 takes the stop route, with the one question "Which Raya?".
- S: A stopped record keeps status Open with the level withheld. Status says what happened, and nothing has.
- T: A price reference with no date or outcome is not a promise. P16 gives only the outside-bundle flag.
- U: The customer promise is asserted only where the test set gives its deadline. No invented dates (rule 8).
- V: A day-only deadline means the end of that day, Malaysia time.
- W: A forecast on the same day as the downstream deadline is not past it. S1 does not fire; the level is MEDIUM as a revision S1 does not cover.
- X: A HIGH promise that is not Overdue unverified shows options built from the bundle, as in P18: accept the revised date (only if a revision is proposed), contact a named alternative (only if the bundle names one), and accept the risk. Plus what happens if nobody acts.
- Y: A promise whose deadline the bundle does not state stops under rule 17, with the question "By when was this promised?".
- Z: Missing by channel is always listed, whatever the deadline, and never raises risk (rule 10).
- AA: Overdue unverified takes precedence over Disputed once the agreed deadline passes without uncontested proof. The dispute stays in the reasons (S4).
- AB: A refusal or confirmed failure that is itself explicitly disputed is Disputed, not Broken.
- AC: A statement can carry an optional cost, only when a source states it. Options that involve getting the outcome another way (find another way, contact an alternative) show that cost with its source, or say "cost not stated". Other options (accept the revised date, accept the risk, tell a dependent's recipient, accept the failure) show no cost.
- AD: A Revised promise shows the status "Revised (proposed)" until acceptance of its latest forecast is evidenced.
- AE: A date from anyone other than the promisor that matches the agreed date or the latest forecast is not a conflict.
- AF: Evidence matching: amounts are checked only for payment promises. An unclear match (a stated figure left out) stops the record only for the evidence that would close it; progress evidence with an unclear figure still counts as progress.
- AG: Ruling O applies to statements that can change a mark: dates, acceptances, refusals, confirmed failures and disputes. Claims, remarks, instruction-like and outside-bundle text never stop a record (rules 2, 3, 4, 18).
- AH: A vague revised date is always flagged. It stops the record only when a confirmed promise depends on it; otherwise the record is scored.
- AI: A stopped record keeps its status; only the level and options are withheld. This applies to every status, including Overdue unverified, Kept and Broken records touched by an ambiguous statement (extends S).
- AJ: A stopped upstream passes no risk on. No signal is added to its dependents; each confirmed dependent shows a visible note naming the stopped upstream and its open question.
- AK: Ruling W applies when either date is day-only. When both state a time, the exact times are compared.
- AL: Only evidence from a Document or Message source can close a promise or count as progress. Owner-said or Unknown evidence is recorded and changes no mark (rule 3).
- AM: Unclear evidence after the agreed deadline leaves the promise Overdue unverified.
- AN: A promisor restating the date already on record is not a revision.

Rules frozen 10/10/2026: no more rule changes today. New findings go to the README's "Known open rulings" only.

If code meets a case these don't decide, stop and ask Resonantly-Feral.

## Time

Tests use a fixed reference time: Thursday 15/10/2026, 09:00, Malaysia time. Never use the system clock in tests or the demo. Dates are day first (DD/MM/YYYY). Money is RM.

## Tests

The test cases are P01–P24 and P17b in Resonantly-Feral's "PromiseWatch Risk Test Set" doc. She will give them to you.

- Pass 1, rules only: hand-written promise records go straight to the rules. Build this before any AI is connected.
- Pass 2, full pipeline: raw bundle to the whole system.
- Compare intermediate extraction, validation and link outputs before assigning a full-pipeline failure to a stage; a new failure is not automatically an extraction bug.
- Marks: R right, F flagged correctly, W wrong with the specific error or uncertainty flagged, X wrong with no relevant flag. Report all four counts and total cases, including X. Check the complete expected result; silent-failure examples are not exhaustive.

## Stack

Python + pytest for the rules engine. UI decided later.

## Commits

No Co-Authored-By lines. No Claude links or session links in commit messages. Short, plain messages.

Never put the owner's email address anywhere in the repo: not in files, commit messages or commit metadata.
