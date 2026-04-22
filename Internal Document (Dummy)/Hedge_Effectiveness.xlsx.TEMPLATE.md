# Hedge_Effectiveness.xlsx — template

Populates KPI **C03 (Hedge Effectiveness Test Pass Rate)** — Ind AS 109
cash-flow-hedge effectiveness testing.

## Expected columns

| designation_id | test_date  | dollar_offset_pct | pass_fail |
|----------------|------------|-------------------|-----------|
| CFH-USD-2025-01 | 2026-03-31 | 98.4              | PASS      |
| CFH-USD-2025-02 | 2026-03-31 | 102.7             | PASS      |
| CFH-EUR-2025-01 | 2026-03-31 | 89.3              | PASS      |

- `dollar_offset_pct` = (Δ hedging instrument FV) / (Δ hedged item FV), as a
  percentage. Ind AS 109 band: **80% — 125%**.
- If you leave `pass_fail` blank, the parser auto-classifies rows inside
  the 80–125% band as PASS.
- `pass_fail` accepts: `PASS`, `FAIL`, `YES`, `NO`, `Y`, `N`.

## RAG rules

- **C03**: GREEN 100% pass · AMBER ≥ 90% · RED < 90%
