# Compliance_Log.xlsx — template

Populates KPI **C01 (Reg Filings On-Time %)**.

## Expected columns

| filing_type   | due_date   | filed_date | days_late | penalty |
|---------------|------------|------------|-----------|---------|
| ECB-2 Return  | 2025-08-07 | 2025-08-10 | 3         | None    |
| FLA Return    | 2025-07-15 | 2025-07-14 | 0         | None    |
| APR           | 2025-09-30 | 2025-09-28 | 0         | None    |

- `days_late` ≤ 0 is treated as on-time. Positive integer = days late.
- Keep the last 12 months of filings — older rows can be pruned.
- `filing_type` and `penalty` are free-text.

## RAG rules

- **C01**: GREEN ≥ 95% on-time · AMBER ≥ 90% · RED < 90%
