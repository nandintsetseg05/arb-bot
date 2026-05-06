# Security policy

## Supported versions

This project is in alpha. Only the latest commit on `main` is supported. There
are no security patch backports.

## Operational security — read this before running

This bot interacts with **real money** when run in live mode. Read all of the
following:

1. **Never commit `.env`.** Only `.env.example` is tracked. The `.gitignore`
   excludes `.env`, `*.pem`, `*.key`, and `secrets/`. Confirm before every push:
   ```bash
   git status
   git ls-files | grep -E "\.env$|\.pem$|\.key$"
   ```
   The second command must print nothing.

2. **Polymarket private key is the master credential.** Anyone with it can
   drain your wallet and place orders on your behalf. Never paste it in chats,
   issues, screenshots, or tickets. If you suspect leakage, immediately move
   funds to a fresh wallet — there is no key rotation.

3. **Kalshi API keys go in a `.pem` file, not in env.** `.env` stores only the
   *path* to the key file. Treat the `.pem` as you would an SSH private key.
   `chmod 600 your_key.pem` after generation.

4. **Run the bot only on machines you fully control.** Not shared machines,
   not corporate-managed laptops with MDM that can read disk, not someone
   else's VPS. The private keys are unencrypted at rest.

5. **Live mode requires intentionality.** The bot refuses to start in live
   mode unless **all** of:
   - `LIVE_TRADING_ENABLED=true` in `.env`
   - `--live` CLI flag
   - both auth checks pass at boot
   - total balance ≤ `MAX_POSITION_USD * 4`

   These gates exist on purpose. Do not remove them in a fork. If you do,
   that is your decision and your risk.

6. **Paper mode is not safe to ignore.** Paper mode uses real prices and
   real API auth. If you enable Polymarket auth keys for paper, those keys
   are still capable of placing real orders if a code path slips. The
   `LIVE_TRADING_ENABLED=false` gate in `Executor` is the only thing
   stopping that. **Do not disable that gate "just for testing."**

## Reporting a vulnerability

If you find a security issue — a missing live-mode gate, a credential being
logged, an API call leaking PII, an injection vector in market matching that
could trigger unintended orders, etc. — please **do not open a public issue.**

Instead:

- Open a private security advisory on GitHub:
  <https://github.com/zostaff/poly-arbitrage-bot/security/advisories/new>
- Or contact the maintainer directly via the email on the GitHub profile.

I aim to respond within 7 days. Critical issues that could cause unintended
trading, fund loss, or credential exposure get priority.

## Out of scope

The following are explicitly **not** considered vulnerabilities of this
repository:

- Losses from prediction-market resolution disputes.
- Losses from Polymarket / Kalshi infrastructure outages.
- Losses from running the bot on misconfigured environments
  (low balance, wrong keys, wrong network).
- Front-running or MEV-style attacks at the chain level.
- Strategy underperformance or unprofitable trades.
- Slippage exceeding the configured buffer.

This is research software. There is no warranty. See `LICENSE`.
