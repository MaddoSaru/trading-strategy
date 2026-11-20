# Day-trading journal + learning loop

Inspired by https://github.com/Jakeschincariol/day-trader-skill (MIT, stdlib Python, 11 Claude skills).
Goal: paper-trade intraday setups, save every trade with its full context in a local DB, and learn from each one.

Status: **draft, to review together** (written 2026-11-17)

## Open decisions (review first)
- [ ] **Broker:** keep our own simulated engine (`paper_trading/engine.py`) or add an Alpaca paper account?
  - TradingView cannot be the broker: `tradingview_ta` is read-only and TradingView's paper account has no public order API.
  - Recommendation: our own engine for the journal first, Alpaca as an optional later step for realistic fills / bracket orders.
- [ ] **Universe:** only QQQ/SPY, a fixed watchlist, or the skill's full ~5,900-stock scanner?
- [ ] **Autonomy:** propose trades only (I say yes in chat) vs. auto-execute on paper within risk limits.
- [ ] **Account settings:** paper capital, max loss per trade, daily loss limit, max trades per day.

## Phase 1 — Intraday data + setups
- [ ] Fetch 5m/15m bars via yfinance (about 60 days of history) into storage (MySQL / parquet)
- [ ] Port the setup detectors from the skill: opening-range breakout, flags, oversold bounce
- [ ] Port the entry timer (waiting / triggered / expired) and exit planner (stop, target in R, flat by 15:55 ET)
- [ ] Port the time machine (10,000 replays plus every past day the setup fired)
- [ ] Keep the TradingView rating + indicators as an extra input to every setup

## Phase 2 — Trade journal (local DB)
- [ ] New `trade_journal` table, one row per trade:
  - setup, symbol, timestamps (signal / entry / exit), side, shares, entry / exit price
  - planned stop, target, R, time machine odds (target-first / stop-first / open at close)
  - TradingView recommendation + indicator snapshot (JSON), strategy votes
  - news headlines at entry (JSON)
  - outcome: exit reason (stop / target / end-of-day / manual), P&L, R multiple
  - best and worst price while open (MFE / MAE), holding time
  - free-text notes / lesson
- [ ] Link to existing `paper_trades` / `paper_positions` or replace them for intraday trades
- [ ] Migration that works on both MySQL and the parquet backend

## Phase 3 — Execution + monitoring
- [ ] Position sizing (from max loss per trade) and risk check (PASS / BLOCK with the reason)
- [ ] Order path: simulated engine (+ Alpaca adapter if chosen), never without approval unless auto mode is on
- [ ] Kuro scheduled job during US market hours (15:30–22:00 Madrid): check stops / targets, close everything by the end of the day, Telegram alerts

## Phase 4 — MCP tools
- [ ] `scan_setups`, `plan_trade`, `simulate_trade` (time machine), `place_paper_trade`, `get_journal`, `journal_stats`
- [ ] Update `CLAUDE.md` / `README.md` tool table

## Phase 5 — Learning loop
- [ ] Statistics: win rate, average R and expectancy by setup, time of day, TradingView rating, symbol
- [ ] Calibration: time machine odds vs. actual outcomes
- [ ] Feed results into `optimizer.py` (re-tune intraday parameters, switch off setups that keep losing)
- [ ] Weekly Kuro review job (e.g. Sat morning): read the journal, write up what works and what doesn't, propose changes to approve

## Verification
- [ ] Unit tests for setups, sizing, risk check and journal writes
- [ ] One full dry-run day on paper end to end before leaving it running

## Review
_(fill in after implementation)_
