"""Exercise the compiled Salam application with independent Python oracles."""
import csv
from decimal import Decimal
import hashlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get("LEDGER_BINARY", ROOT / "build/pocket-ledger"))
HEADER = "date,category,amount,description\n"


class LedgerCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def run_ledger(self, data, budget=None, extra=(), month="2026-10"):
        call_folder = Path(tempfile.mkdtemp(dir=self.folder))
        path = call_folder / "expenses.csv"
        path.write_bytes(data.encode() if isinstance(data, str) else data)
        argv = [str(BINARY), str(path), "--month", month, "--json"]
        watched = [path]
        if budget is not None:
            budget_path = call_folder / "budgets.csv"
            budget_path.write_text(budget)
            watched.append(budget_path)
            argv += ["--budgets", str(budget_path)]
        before = {p: hashlib.sha256(p.read_bytes()).digest() for p in watched}
        result = subprocess.run(argv + list(extra), capture_output=True, timeout=10)
        for p, digest in before.items():
            self.assertEqual(hashlib.sha256(p.read_bytes()).digest(), digest)
        self.assertEqual(set(call_folder.iterdir()), set(watched))
        return result

    def rejected(self, data, **kwargs):
        result = self.run_ledger(data, **kwargs)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, b"")
        self.assertIn(b"pocket-ledger:", result.stderr)

    def test_exact_total_and_month_filter(self):
        result = self.run_ledger(HEADER + "2026-10-01,food,0.10,a\n2026-10-02,food,0.20,b\n2026-09-30,food,99,x\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = json.loads(result.stdout)
        self.assertEqual((out["total_cents"], out["records"]), (30, 2))
        self.assertIsNone(out["categories"][0]["budget_cents"])

    def test_budget_boundaries_and_unused_categories(self):
        result = self.run_ledger(HEADER + "2026-10-01,food,10.01,x\n2026-10-01,bus,2,x\n", budget="category,limit\nfood,10\nbus,2\nbooks,0\n")
        out = json.loads(result.stdout)
        self.assertEqual([r["name"] for r in out["categories"]], ["books", "bus", "food"])
        self.assertEqual([r["over_budget"] for r in out["categories"]], [False, False, True])

    def test_csv_quotes_multiline_crlf_and_unicode(self):
        data = 'date,category,amount,description\r\n2026-10-01,food,1.23,"tea, ""cake""\r\nभारत 🍵"\r\n'
        result = self.run_ledger(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total_cents"], 123)

    def test_calendar_validation(self):
        for date in ["2026-02-29", "1900-02-29", "2026-04-31", "2026-00-01", "2026-01-00", "1899-12-31", "2026-1-01"]:
            with self.subTest(date=date):
                self.rejected(HEADER + f"{date},food,1,x\n")
        for date in ["2000-02-29", "2024-02-29", "2026-12-31"]:
            with self.subTest(date=date):
                self.assertEqual(self.run_ledger(HEADER + f"{date},food,1,x\n", month=date[:7]).returncode, 0)

    def test_invalid_amounts(self):
        for amount in ["", "-1", "+1", "NaN", "1e2", ".5", "1.", "1.001", " 1", "1 ", "1000000000", "９"]:
            with self.subTest(amount=amount):
                self.rejected(HEADER + f"2026-10-01,food,{amount},x\n")

    def test_maximum_amount_and_10000_records(self):
        data = HEADER + "2026-10-01,food,999999999.99,x\n" * 10000
        result = self.run_ledger(data)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["total_cents"], 999999999990000)

    def test_record_and_file_limits(self):
        self.rejected(HEADER + "2026-10-01,food,1,x\n" * 10001)
        self.rejected(b"x" * (1048576 + 1))

    def test_invalid_csv_shapes_and_quotes(self):
        for data in ["", "wrong,header\n", HEADER + "\n", HEADER + "2026-10-01,food,1\n", HEADER + '2026-10-01,food,1,"unclosed', HEADER + '2026-10-01,food,1,"closed"tail\n', HEADER + '2026-10-01,food,1,mid"quote\n', HEADER + "," * 17]:
            with self.subTest(data=data):
                self.rejected(data)

    def test_invalid_categories_and_description_limit(self):
        for category in ["", "Food", "food space", "a" * 41, "🍵"]:
            self.rejected(HEADER + f"2026-10-01,{category},1,x\n")
        self.rejected(HEADER + "2026-10-01,food,1," + "x" * 1001)

    def test_empty_valid_ledger(self):
        result = self.run_ledger(HEADER)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["categories"], [])

    def test_invalid_utf8_and_nul(self):
        for suffix in [b"\0", b"\xff", b"\xc0\x80", b"\xed\xa0\x80", b"\xf4\x90\x80\x80", b"\xe2\x82"]:
            self.rejected((HEADER + "2026-10-01,food,1,").encode() + suffix)

    def test_budget_validation(self):
        for budget in ["", "category,wrong\n", "category,limit\nfood,1\nfood,2\n", "category,limit\nfood,-1\n", "category,limit\nfood\n"]:
            self.rejected(HEADER, budget=budget)

    def test_category_limits(self):
        budgets = "category,limit\n" + "".join(f"c{i},1\n" for i in range(201))
        self.rejected(HEADER, budget=budgets)
        data = HEADER + "".join(f"2026-10-01,c{i},1,x\n" for i in range(201))
        self.rejected(data)

    def test_cli_rejects_unknown_duplicate_and_missing_options(self):
        for extra in [["--oops"], ["--json"], ["--month", "2026-09"], ["another.csv"], ["--budgets"]]:
            self.rejected(HEADER, extra=extra)
        self.rejected(HEADER, month="2026-13")
        result = subprocess.run([str(BINARY), str(self.folder / "missing"), "--month", "2026-10"], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)

    def test_help_and_text_report(self):
        help_result = subprocess.run([str(BINARY), "--help"], capture_output=True, timeout=10)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn(b"Usage:", help_result.stdout)
        result = subprocess.run([str(BINARY), str(ROOT / "examples/expenses.csv"), "--month", "2026-10", "--budgets", str(ROOT / "examples/budgets.csv")], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"TOTAL 14.94 (3 records)", result.stdout)
        self.assertIn(b"food: 12.44 / 10.00 OVER", result.stdout)

    def test_generated_csv_against_decimal_oracle(self):
        rng = random.Random(1713)
        for case in range(20):
            with self.subTest(case=case):
                stream = io.StringIO(newline="")
                writer = csv.writer(stream)
                writer.writerow(["date", "category", "amount", "description"])
                expected = {}
                count = 0
                for _ in range(100):
                    month = rng.choice(["2026-09", "2026-10"])
                    category = rng.choice(["food", "bus", "books"])
                    amount = f"{rng.randrange(10000)}.{rng.randrange(100):02d}"
                    writer.writerow([month + "-01", category, amount, rng.choice(["a,b", 'a"b', "line\nbreak", "🍵"])])
                    if month == "2026-10":
                        expected[category] = expected.get(category, 0) + int(Decimal(amount) * 100)
                        count += 1
                result = self.run_ledger(stream.getvalue())
                self.assertEqual(result.returncode, 0, result.stderr)
                out = json.loads(result.stdout)
                self.assertEqual(out["records"], count)
                self.assertEqual(out["total_cents"], sum(expected.values()))
                self.assertEqual({r["name"]: r["spent_cents"] for r in out["categories"]}, expected)


if __name__ == "__main__":
    unittest.main()
