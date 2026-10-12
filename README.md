# Pocket Ledger

A read-only monthly expense and budget report, built with the [Salam Programming Language](https://github.com/SalamLang/Salam). It turns local CSV files into a deterministic text or JSON summary. Amounts are calculated in integer minor units, so `0.10 + 0.20` is exactly `0.30`.

The application makes no network requests and does not modify input files. It is intended for one currency with two decimal places. It does not perform currency conversion, move money, or replace accounting software.

## Build and run

Install the official Salam **0.5.3** compiler release and a C compiler. Keep Salam's bundled standard library beside its executable. Python 3 is needed only to run the integration tests.

```sh
make build SALAM=/path/to/salam CC=clang
./build/pocket-ledger examples/expenses.csv --month 2026-10 --budgets examples/budgets.csv
./build/pocket-ledger examples/expenses.csv --month 2026-10 --budgets examples/budgets.csv --json
```

The example text output is:

```text
Pocket Ledger - 2026-10
TOTAL 14.94 (3 records)
books: 0.00 / 30.00
food: 12.44 / 10.00 OVER
transport: 2.50 / 20.00
```

`--month` and the expense file are required; `--budgets` and `--json` are optional. Use `--help` for usage. Paths beginning with a dash can be passed with a `./` prefix. The command exits 0 on success and 2 on invalid input or an I/O error. Spending over budget is reported in the output and is not a command failure.

## Input contract

Expense CSV columns, in order:

```csv
date,category,amount,description
2026-10-01,food,12.34,"Lunch, tea"
```

Optional budget CSV columns:

```csv
category,limit
food,100.00
```

- Files must be seekable UTF-8 files without NUL bytes or a byte-order mark, at most 1 MiB each.
- CSV supports LF/CRLF, quoted commas, doubled quotes and quoted multiline descriptions. Malformed quotes, blank records, wrong column counts and wrong headers are rejected.
- Dates must be real Gregorian `YYYY-MM-DD` dates, from year 1900 through 9999. A report covers exactly the requested `YYYY-MM`.
- Categories use 1–40 lowercase ASCII letters, digits, underscores or hyphens. At most 200 distinct report categories and 200 budget categories are accepted.
- Amounts are non-negative decimal strings with zero, one or two fractional digits, at most `999999999.99`. Signs, exponent notation, whitespace and extra precision are rejected rather than rounded. Negative refunds are not supported.
- At most 10,000 expense records; descriptions may contain at most 1,000 Unicode characters. All records are validated, including records outside the selected month.
- Duplicate expense rows count separately. Duplicate budget categories are errors. An unused budget still appears with zero spending; an expense category without a budget appears with `null` in JSON.
- A budget is a limit for the selected month. Categories are sorted by name. Input order does not change totals.

JSON uses integer `total_cents`, `spent_cents` and `budget_cents` values; `budget_cents` is nullable. Each category also reports `records` and `over_budget`. The supported maximum total is below JavaScript's exact integer limit.

## Validation

```sh
make test format-check SALAM=/path/to/salam CC=clang
git diff --check
```

The Salam unit program checks date/amount parsing, CSV, ledger schemas, budget validation and aggregation. The Python suite executes the compiled application; it checks malformed files, limits, invalid UTF-8, exact arithmetic, budget boundaries, CLI errors and unchanged input files. Twenty deterministic generated CSV datasets are compared with Python's CSV writer and Decimal arithmetic as independent oracles. A separate case exercises 10,000 records at the maximum amount.

Verified locally on macOS arm64 using Salam 0.5.3 and Apple Clang: native application and unit program build successfully, unit checks pass, all 16 Python test methods pass, and all 13 Salam files pass the compiler's formatting check. Linux, Windows, Docker and hosted CI have not been tested. The local sandbox prints harmless `sysctl` CPU-detection warnings during compilation; builds exit successfully.

## Code layout

| File | Responsibility |
|---|---|
| `main.salam` | Process entry point |
| `src/cli.salam` | Arguments, orchestration, errors and exit status |
| `src/files.salam` | Bounded file reads and strict UTF-8 validation |
| `src/csv.salam` | CSV state machine and table ownership |
| `src/schema.salam` | Header and category contracts |
| `src/money.salam` | Exact amount parsing and formatting |
| `src/dates.salam` | Month and Gregorian-date validation |
| `src/expenses.salam` | Expense record validation |
| `src/budgets.salam` | Unique budget validation |
| `src/summary.salam` | Monthly category aggregation and sorting |
| `src/text_report.salam` | Human-readable report |
| `src/json_report.salam` | Machine-readable report |

The source is MIT licensed. Salam is a separate project with its own license; its compiler and standard library are not vendored here.
