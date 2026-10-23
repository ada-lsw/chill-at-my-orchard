## What this PR does

<!-- One or two sentences, in your own words. -->

## How it works

<!-- Walk through the main change as if explaining it to a teammate. Write this yourself, even if Claude helped write the code. If you can't explain a part, ask Claude to walk you through it before opening the PR. -->

## How I tested it

<!-- What did you run, and what did you see? Screenshots welcome for UI changes. -->

## Checklist

- [ ] I can explain every change in this PR to a judge
- [ ] Small and focused on one task
- [ ] Missing or flagged data is handled, not silently skipped (if this touches data)
- [ ] Settings (start dates, thresholds, crops) changed in `backend/app/config.py`, not hardcoded (if this touches calculations)
- [ ] Tests pass: `cd backend && python -m pytest -q`
- [ ] No API keys or `.env` files committed
- [ ] New packages added to `backend/requirements.txt` or `frontend/requirements.txt`

## Questions for the reviewer

<!-- Anything you're unsure about? -->
