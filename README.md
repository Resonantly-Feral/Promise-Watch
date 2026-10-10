PromiseWatch, built at DORMATHON 2026, 10–11/10/2026.

## Running

    pip install -e ".[test]"
    pytest                                  # Pass 1 and the pipeline checks
    python -m promisewatch.pipeline.run     # Pass 2 on the bundle in data/
    python -m promisewatch.page data/runs/<file>.json   # one demo page, in docs/demo/
    python -m promisewatch.site             # every demo page and docs/scorecard.html

Pass 2 calls the model set in `promisewatch.toml` (one line: `model = ...`)
and reads the key from the variable named by `api_key_env` there
(`PROMISEWATCH_ANTHROPIC_KEY`). Each live run is saved in
`data/runs/`; re-check one without calling the model with
`python -m promisewatch.pipeline.run --replay data/runs/<file>.json`.

## Known open rulings

The rules were frozen on 10/10/2026. These cases are not decided by
CLAUDE.md. Each entry says what the engine does now, which is not a ruling.
New findings are added here, not to CLAUDE.md.

1. **Owner-said acceptance.** Can an acceptance said by the owner (the user,
   as the promise's recipient) move the agreed deadline? Rule 3 says the owner
   never lowers risk; accepting a new date is also a real business act.
   Now: the engine accepts it.
2. **S2 "comparable orders".** S2 says the channel normally carries the
   evidence "for comparable orders"; Ruling E says "every earlier fulfilment in
   the channel". Now: every earlier fulfilment in the channel counts.
3. **A reason for LOW.** Should a LOW with no signals show its own reason,
   such as the window used? Now: only "No elevated risk detected in this
   bundle".
4. **Exposure scope.** Amounts where the user is neither payer nor payee, and
   whether every stated amount is shown or only the at-risk chain. Now: lines
   only for at-risk promises and their confirmed dependents; amounts between
   two other parties are left out without a flag.
5. **Disputes about the date or outcome.** Now: every dispute gets the reason
   "Fulfilment is explicitly disputed".
6. **Revisions to the outcome or a condition.** Only date revisions exist.
   Now: a change to the outcome or a condition cannot be represented.
7. **Who counts as "a human" confirming failure.** Now: only the bundle's
   user. A failure reported by anyone else is a conflict (S4).
8. **Accepting a vague forecast.** Can "Accept the revised date" be offered
   when the forecast is an unresolved date such as "next week"? Now: it can be,
   when the record is HIGH and not stopped.
9. **Ruling N, "each confirmed dependent".** Direct dependents only, or the
   whole chain? Now: direct only. Ruling AJ's note is also direct only.
10. **"Latest" statement in rule 5.** Statements carry no timestamp. Now: the
    order they arrive in the bundle is taken as time order, so extraction must
    keep them in order.
11. **Receipt of funds.** There is no evidence kind for receipt; a bank slip
    only supports initiation. Now: a receipt promise could only close on a
    bank slip.
12. **Cost for "find another way" (Ruling N).** No statement can feed it a
    stated cost. Now: always "cost not stated"; a stated cost belongs to a
    named alternative instead.
13. **Rule 7, "reasoning shown".** A date that extraction resolves has nowhere
    to keep its reasoning in the rules' records. Now: extraction writes the
    reasoning for every date into its saved run (data/runs/), and the rules'
    records carry only the date.
14. **Rule 1, source type on results.** Results carry source ids; the type is
    looked up from the bundle. Now: whether that counts as "carries" is for
    the UI to settle.
15. **Expected evidence for work and document promises.** Only goods
    (signed delivery note, tracking as progress) and payment (bank slip) have
    expected evidence agreed. Now: validation rejects a work or document
    promise and lists it as an issue, so it is never scored.

Resolved by Ruling AI (10/10/2026): dependency cycles and settled promises.
A stopped record keeps its status and its level is withheld.
