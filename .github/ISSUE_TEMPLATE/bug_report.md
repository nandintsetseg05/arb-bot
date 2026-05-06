---
name: Bug report
about: Report a bug — something that doesn't behave as documented.
title: "[bug] "
labels: bug
assignees: ''
---

**Do NOT include private keys, API secrets, or `.env` contents in this report.**
If your bug requires showing those values, redact them with `<REDACTED>`.

## Summary

One line: what's broken?

## Reproduction

```bash
# Exact commands you ran.
```

## Expected behaviour

What you thought would happen.

## Actual behaviour

What actually happened. Paste the relevant log lines (JSON-formatted output
from `setup_logging`). Redact any wallet addresses, market IDs you don't want
public, and **always** redact credentials.

## Environment

- OS:
- Python version (`python --version`):
- Bot version / commit (`git rev-parse HEAD`):
- Mode: paper / live
- Kalshi env: demo / prod

## Additional context

Did this happen during a specific market? At a specific time? After how many
scan cycles? Any screenshots of the Streamlit dashboard?
