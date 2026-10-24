<!-- Title: start with the package and task, e.g. "F1: glance card". Shared-file changes start with "contract:" or "config:". -->

## What this PR does

<!-- One or two sentences, in your own words. -->

**Work package and task:** <!-- e.g. Frontend A, F1 (see docs/WORK_PACKAGES.md) -->
**Demo story it helps:** <!-- Durham walnuts / Kern pistachios / both / proof / setup -->

## How it works

<!-- Walk through the main change as if explaining it to a teammate. Write this yourself, even if Claude helped write the code. If you can't explain a part, ask Claude to walk you through it before opening the PR. -->

## Files changed

<!-- List them. Flag any file you don't own (see CLAUDE.md) and say why you touched it. -->

## Does this change what other people rely on?

- [ ] No
- [ ] Yes, the **API contract** (`schemas.py` or an endpoint's fields). What changed and who is affected:
- [ ] Yes, **shared settings** (`config.py`). Which values, and their source:
- [ ] Yes, the **data contract** (columns or a new `source` value). Agreed at standup on:

## How I tested it

<!-- Paste what you ran and what you saw. Screenshots for anything on screen; for the glance card, include one at phone width. -->

- [ ] `cd backend && python -m pytest -q` passes (number of tests: )
- [ ] Ran the app on synthetic data and clicked both demo buttons, no red errors
- [ ] Checked with real CIMIS data (if it touches data or math)

## Checklist

- [ ] I can explain every change in this PR to a judge
- [ ] Small and focused on one task
- [ ] Missing or flagged data is handled, not silently skipped (if this touches data)
- [ ] Settings, targets and thresholds live in `backend/app/config.py`, not hardcoded
- [ ] Anything a grower sees follows the plain-language rules in CLAUDE.md (crop names, numbers with meaning, color with a word)
- [ ] Decision text never names product rates, mixes, application steps or an "apply on" date
- [ ] No API keys, `.env` files or large cache files committed
- [ ] New packages added to a requirements file and listed here:
- [ ] New data sources credited in `README.md`

## Risks or follow-ups

<!-- Anything that might break, or that you left for later. -->

## Questions for the reviewer

<!-- Anything you're unsure about? Point to the exact lines. -->
