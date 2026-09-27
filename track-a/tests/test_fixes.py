"""Regression tests for the Track A fixes.

These tests cover only the behaviours changed/fixed :
- invoice identity/idempotent imports
- payment matching by customer_id + invoice_number
- currency-precision reporting/status
- filtered CSV export matching invoice status
"""

import tempfile
import unittest
from pathlib import Path

from ledger import importing, reporting, storage


class TestFixRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = storage.connect(Path(self.tmp.name) / "regression.sqlite3")
        storage.seed(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # 1. Invoice identity / idempotent import
    # ------------------------------------------------------------------

    def test_identical_invoice_reimport_is_skipped_without_duplication(self):
        csv_text = (
            "customer_id,invoice_number,amount,due_date\n"
            "HARBOR,INV-100,1250.00,2026-09-01\n"
        )

        before = self.db.execute(
            "SELECT COUNT(*) FROM invoices WHERE customer_id=? AND invoice_number=?",
            ("HARBOR", "INV-100"),
        ).fetchone()[0]

        result = importing.import_csv(self.db, csv_text, "invoices")

        after = self.db.execute(
            "SELECT COUNT(*) FROM invoices WHERE customer_id=? AND invoice_number=?",
            ("HARBOR", "INV-100"),
        ).fetchone()[0]

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual(before, after)

    def test_conflicting_invoice_identity_is_rejected_and_original_preserved(self):
        csv_text = (
            "customer_id,invoice_number,amount,due_date\n"
            "HARBOR,INV-100,1300.00,2026-10-01\n"
        )

        result = importing.import_csv(self.db, csv_text, "invoices")

        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual(result["errors"][0]["line"], 2)

        invoice = self.db.execute(
            """SELECT amount, due_date
               FROM invoices
               WHERE customer_id=? AND invoice_number=?""",
            ("HARBOR", "INV-100"),
        ).fetchone()

        self.assertEqual(invoice["amount"], 1250.00)
        self.assertEqual(invoice["due_date"], "2026-09-01")

    # ------------------------------------------------------------------
    # 2. Payment matching must use composite invoice identity
    # ------------------------------------------------------------------

    def test_payment_matches_by_customer_and_invoice_number_not_amount(self):
        # INV-100 and INV-200 both have amount 1250.00.
        # The payment must attach to the explicitly referenced invoice.
        csv_text = (
            "payment_id,customer_id,invoice_number,amount\n"
            "REG-P1,MAPLE,INV-200,1250.00\n"
        )

        result = importing.import_csv(self.db, csv_text, "payments")

        self.assertEqual(result["imported"], 1)

        harbor = next(
            row
            for row in reporting.invoices(self.db)
            if row["invoice_number"] == "INV-100"
        )
        maple = next(
            row
            for row in reporting.invoices(self.db)
            if row["invoice_number"] == "INV-200"
        )

        self.assertEqual(harbor["paid"], 0.00)
        self.assertEqual(maple["paid"], 1250.00)
        self.assertEqual(maple["status"], "paid")

    def test_same_amount_with_wrong_identity_stays_unmatched(self):
        # There is an invoice for 1250.00, but the payment references
        # a different customer/invoice identity. It must not match by amount.
        csv_text = (
            "payment_id,customer_id,invoice_number,amount\n"
            "REG-P2,NORTH,DOES-NOT-EXIST,1250.00\n"
        )

        result = importing.import_csv(self.db, csv_text, "payments")

        self.assertEqual(result["imported"], 1)

        payment = self.db.execute(
            """SELECT invoice_id
               FROM payments
               WHERE payment_id=?""",
            ("REG-P2",),
        ).fetchone()

        self.assertIsNone(payment["invoice_id"])

        invoice = next(
            row
            for row in reporting.invoices(self.db)
            if row["invoice_number"] == "INV-100"
        )
        self.assertEqual(invoice["paid"], 0.00)

        unmatched = reporting.overview(self.db)["unmatched_payments"]
        self.assertTrue(
            any(p["payment_id"] == "REG-P2" for p in unmatched)
        )

    # ------------------------------------------------------------------
    # 3. Currency precision / -0.00 reporting fix
    # ------------------------------------------------------------------

    def test_payment_sum_is_rounded_to_currency_precision(self):
        # 0.10 + 0.20 can produce a binary floating-point residue.
        # The reporting layer should expose 0.30 exactly at currency precision.
        invoice_csv = (
            "customer_id,invoice_number,amount,due_date\n"
            "NORTH,ROUND-1,0.30,2026-09-30\n"
        )
        payment_csv = (
            "payment_id,customer_id,invoice_number,amount\n"
            "ROUND-P1,NORTH,ROUND-1,0.10\n"
            "ROUND-P2,NORTH,ROUND-1,0.20\n"
        )

        self.assertEqual(
            importing.import_csv(self.db, invoice_csv, "invoices")["imported"],
            1,
        )
        self.assertEqual(
            importing.import_csv(self.db, payment_csv, "payments")["imported"],
            2,
        )

        invoice = next(
            row
            for row in reporting.invoices(self.db)
            if row["invoice_number"] == "ROUND-1"
        )

        self.assertEqual(invoice["paid"], 0.30)
        self.assertEqual(invoice["balance"], 0.00)
        self.assertEqual(invoice["status"], "paid")

    def test_zero_currency_balance_is_paid_not_negative_zero_open(self):
        invoice_csv = (
            "customer_id,invoice_number,amount,due_date\n"
            "NORTH,ROUND-2,10.00,2026-09-30\n"
        )
        payment_csv = (
            "payment_id,customer_id,invoice_number,amount\n"
            "ROUND-P3,NORTH,ROUND-2,10.00\n"
        )

        importing.import_csv(self.db, invoice_csv, "invoices")
        importing.import_csv(self.db, payment_csv, "payments")

        invoice = next(
            row
            for row in reporting.invoices(self.db)
            if row["invoice_number"] == "ROUND-2"
        )

        self.assertEqual(invoice["balance"], 0.00)
        self.assertEqual(invoice["status"], "paid")

    # ------------------------------------------------------------------
    # 4. Open / paid reporting and filtered export
    # ------------------------------------------------------------------

    def test_paid_and_open_filters_are_consistent_with_invoice_status(self):
        all_rows = reporting.invoices(self.db)
        open_rows = reporting.invoices(self.db, "open")
        paid_rows = reporting.invoices(self.db, "paid")

        self.assertTrue(all(row["status"] == "open" for row in open_rows))
        self.assertTrue(all(row["status"] == "paid" for row in paid_rows))

        all_numbers = {row["invoice_number"] for row in all_rows}
        filtered_numbers = (
            {row["invoice_number"] for row in open_rows}
            | {row["invoice_number"] for row in paid_rows}
        )

        self.assertEqual(all_numbers, filtered_numbers)
        self.assertEqual(
            {row["invoice_number"] for row in paid_rows},
            {"INV-101"},
        )

    def test_filtered_export_contains_only_requested_status(self):
        open_csv = reporting.export_csv(self.db, "open")
        paid_csv = reporting.export_csv(self.db, "paid")

        self.assertIn("customer_id,invoice_number,amount,paid,balance,status", open_csv)
        self.assertIn("INV-101", paid_csv)
        self.assertNotIn("INV-101", open_csv)

        # INV-100 is open in the seeded database.
        self.assertIn("INV-100", open_csv)
        self.assertNotIn("INV-100", paid_csv)

        for line in paid_csv.splitlines()[1:]:
            self.assertTrue(line.endswith(",paid"))

        for line in open_csv.splitlines()[1:]:
            self.assertTrue(line.endswith(",open"))


if __name__ == "__main__":
    unittest.main()
