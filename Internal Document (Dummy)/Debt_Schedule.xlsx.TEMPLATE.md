# Debt_Schedule.xlsx — template

Populates KPIs **D01 (Net Debt / EBITDA)** and **D02 (Working Capital Utilisation)**.

## Expected columns

| facility       | type       | sanctioned_inr_mn | outstanding_inr_mn | ebitda_ttm_inr_mn | covenant                |
|----------------|------------|-------------------|--------------------|-------------------|-------------------------|
| ECB Tranche 1  | Term Loan  | 2500              | 1800               | 1800              | Net Debt/EBITDA ≤ 2.50x |
| CC Facility    | Fund       | 800               | 550                |                   |                         |
| LC/BG Limit    | Non-Fund   | 600               | 380                |                   |                         |

- `type` = one of: `Term Loan`, `Fund`, `Non-Fund`. Only non-term rows
  count toward D02's Working Capital utilisation.
- `ebitda_ttm_inr_mn` is needed on at least one row (the max is used for D01).
- `covenant` is free-text displayed in narratives.

## RAG rules

- **D01**: GREEN ≤ 2.50x · AMBER ≤ 3.00x · RED > 3.00x
- **D02**: GREEN ≤ 80% · AMBER ≤ 95% · RED > 95%
