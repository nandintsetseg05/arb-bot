-- poly-arbitrage-bot SQLite schema
-- All amounts in USD. Timestamps are ISO-8601 strings (UTC).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at     TEXT NOT NULL,
    arb_type        TEXT NOT NULL CHECK (arb_type IN ('cross_exchange', 'bundle')),
    poly_market_id  TEXT,
    poly_question   TEXT,
    kalshi_ticker   TEXT,
    kalshi_question TEXT,
    similarity      REAL,                       -- NULL for bundle
    leg_a_side      TEXT NOT NULL,              -- BUY/SELL + YES/NO
    leg_a_price     REAL NOT NULL,
    leg_a_venue     TEXT NOT NULL,
    leg_b_side      TEXT,
    leg_b_price     REAL,
    leg_b_venue     TEXT,
    gross_edge_usd  REAL NOT NULL,
    fees_usd        REAL NOT NULL,
    slippage_usd    REAL NOT NULL,
    net_edge_usd    REAL NOT NULL,
    edge_bps        INTEGER NOT NULL,
    sized_usd       REAL,                       -- NULL if not sized
    decision        TEXT NOT NULL,              -- traded / skipped_edge / skipped_risk / review_required
    decision_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_opps_detected ON opportunities(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_opps_decision ON opportunities(decision);

CREATE TABLE IF NOT EXISTS trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id  INTEGER NOT NULL REFERENCES opportunities(id),
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    mode            TEXT NOT NULL CHECK (mode IN ('paper', 'live')),
    status          TEXT NOT NULL,              -- pending / filled / partial / failed / unwound
    realized_pnl    REAL,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_opp ON trades(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_trades_started ON trades(started_at DESC);

CREATE TABLE IF NOT EXISTS legs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id        INTEGER NOT NULL REFERENCES trades(id),
    venue           TEXT NOT NULL,              -- polymarket / kalshi
    market_id       TEXT NOT NULL,
    side            TEXT NOT NULL,              -- BUY/SELL + YES/NO
    requested_size  REAL NOT NULL,              -- contracts (Kalshi) or shares (Polymarket)
    requested_price REAL NOT NULL,
    filled_size     REAL,
    avg_fill_price  REAL,
    fee_usd         REAL,
    venue_order_id  TEXT,
    status          TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    settled_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_legs_trade ON legs(trade_id);

CREATE TABLE IF NOT EXISTS balance_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at     TEXT NOT NULL,
    venue           TEXT NOT NULL,
    balance_usd     REAL NOT NULL,
    note            TEXT
);

CREATE INDEX IF NOT EXISTS idx_balance_captured ON balance_snapshots(captured_at DESC);
