# Bank_Balances.xlsx — template

Drop an Excel file with this name in the same folder to populate KPIs
**L01 (Total Cash Position)**, **L02 (INR Operating Cash)**, and
**L03 (Top-Bank Share)**.

## Expected columns (first sheet, headers in any row with ≥3 filled cells)

| bank          | currency | balance_inr_mn | as_of_date |
|---------------|----------|----------------|------------|
| HDFC Bank     | INR      | 654.00         | 2026-04-14 |
| ICICI Bank    | INR      | 320.50         | 2026-04-14 |
| SBI           | USD      | 180.00         | 2026-04-14 |
| Citibank      | USD      | 94.00          | 2026-04-14 |

Column name matching is **case-insensitive / substring**, so `Bank Name`,
`Currency`, `Balance (INR mn)`, and `As of Date` all work.

## Notes

- `balance_inr_mn` must be the **INR-equivalent** value (convert USD/EUR
  balances to INR at the bank's closing rate before putting them in).
- `currency` = original currency of the balance. L02 uses `INR` only.
- Rows containing the word "Total" in the `bank` column are skipped.
- The most recent `as_of_date` found becomes the panel's "As of" header.

## RAG rules

- **L01**: GREEN ≥ INR 800 mn · AMBER ≥ 600 · RED < 600
- **L02**: GREEN ≥ INR 75 mn · RED < 75
- **L03**: GREEN ≤ 35% · AMBER 35–40% · RED > 40%
