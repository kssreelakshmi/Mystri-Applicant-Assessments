# Handover

-   Name: Sreelakshmi K S
-   Email used for this application: kssreelakshmi2211@gmail.com
-   Chosen track: Track A --- Repair the register
-   Why this track: I chose Track A because I enjoy product engineering,
    debugging existing applications and improving backend/full-stack
    workflows.
-   Approximate total time, including setup and handover: **\[5-6 hour]**

## Run and verify

Prerequisite: Python 3.10+ and a modern browser. No additional
third-party application dependency was added.

From the `track-a` directory:

``` text
python3 -m pytest -v
python3 app.py
```

Open:

``` text
http://127.0.0.1:8787
```

To restore the supplied owner register before verification, with the
server stopped:

``` text
python3 restore_fixture.py --replace
python3 app.py
```

The existing smoke suite contains 5 tests. I added `tests/test_fixes.py`
with 8 focused regression tests.

Observed results:

``` text
python3 -m pytest tests/test_fixes.py -v
8 passed in 1.18s
```

The existing smoke suite was also run separately and completed with:

``` text
5 passed in 0.73s
```

Therefore the verification performed so far covers 13 tests in total.

## What I delivered

I selected the main problems around reporting consistency, CSV export,
import idempotency and payment matching.

### 1. Invoice reporting/status consistency

I fixed the invoice reporting logic so balances are calculated at
currency precision and `open`/`paid` status is derived consistently from
the balance.

This addresses the mismatch between the open-invoice view and the
overview.

### 2. Currency rounding

I changed the invoice payment aggregation to round the payment sum to
two decimal places. This prevents floating-point drift from producing
values such as `-0.00`.

### 3. Invoice identity and idempotent imports

Invoice identity is enforced using:

``` text
(customer_id, invoice_number)
```

An identical invoice re-import is skipped without changing totals.
Reusing the same identity with different invoice details is rejected
while preserving the existing record.

### 4. Payment matching

Payments are matched using both:

``` text
customer_id + invoice_number
```

rather than amount alone.

This prevents a payment from being attached to the wrong invoice when
two invoices happen to have the same amount.

### 5. Import feedback

The browser now reports actual import results, including
imported/skipped/rejected counts and rejected-row information. HTTP
import failures are also surfaced instead of being presented as
successful imports.

### 6. Small improvement: filtered CSV export

I added support for passing the selected invoice status to the export
endpoint.

The export now follows the current UI selection:

``` text
all  -> /api/export?status=all
open -> /api/export?status=open
paid -> /api/export?status=paid
```

This keeps the downloaded report aligned with what the user is viewing.

## Evidence and limits

### Failing-before / passing-after reproduction

I used the payment-matching case where two invoices can have the same
amount. A payment referencing one customer/invoice identity must not be
attached to another invoice merely because its amount is equal.

After the fix, the regression test
`test_payment_matches_by_customer_and_invoice_number_not_amount`
verifies that the payment is attached to the invoice identified by both
`customer_id` and `invoice_number`.

I also added the complementary case
`test_same_amount_with_wrong_identity_stays_unmatched`, which verifies
that an unknown invoice identity does not attach the payment to an
invoice with the same amount.

### Regression checks added

`tests/test_fixes.py` contains 8 focused tests covering:

-   identical invoice re-import is skipped without duplication
-   conflicting invoice identity is rejected and the original is
    preserved
-   payment matching uses customer ID and invoice number
-   same-amount payment with the wrong invoice identity remains
    unmatched
-   payment aggregation is rounded to currency precision
-   zero balance is reported as paid rather than negative zero/open
-   open and paid filters contain the correct records
-   filtered CSV export contains only the requested invoice status

All 8 regression tests passed.

### Existing-register check

I used the supplied existing-register fixture rather than replacing it
with the fresh demo data. The existing register was checked before
testing new imports, and the repair was designed to preserve existing
customer, invoice and payment identities and allocations while allowing
valid new records to be imported.

### Changed-input cases

I tested inputs beyond the supplied happy path, including:

-   re-importing an identical invoice
-   reusing an invoice identity with changed details
-   two invoices sharing the same amount
-   a payment referencing an invoice identity that does not exist
-   decimal payment amounts that can expose floating-point rounding
    problems


## Tools and judgment

-   **Python/pytest:** I used the existing test suite and added focused
    regression tests. I verified the new tests independently rather than
    assuming that a successful application run meant the fixes were
    correct.
-   **Claude Sonnet 5 medium:** I used it for generating/reviewing testcases. I validated and verified the
    fixes I made - against the business rules and actual test results. 

I kept the supplied smoke tests unchanged and added only regression
coverage for the behaviours I modified.

