import csv
import io
from .validation import HEADERS, normalize
from .storage import insert_invoice, insert_payment
from .matching import find_invoice


def import_csv(db, text, kind):
    if kind not in HEADERS:
        raise ValueError('Unknown import kind')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    if reader.fieldnames != HEADERS[kind]:
        raise ValueError('Expected CSV header: ' + ','.join(HEADERS[kind]))
    customers = {r[0] for r in db.execute('SELECT customer_id FROM customers')}

    existing_invoices = {
        (r['customer_id'], r['invoice_number']): (r['amount'], r['due_date'])
        for r in db.execute('SELECT customer_id, invoice_number, amount, due_date FROM invoices')
    }

    result = {'imported': 0, 'skipped': 0, 'rejected': 0, 'errors': []}
    with db:
        for line, row in enumerate(reader, 2):
            try:
                if kind == 'invoices':
                    try:
                        row = normalize(row, kind, customers)
                    except ValueError as exc:
                        result['rejected'] += 1
                        result['errors'].append({'line': line, 'reason': str(exc)})
                        continue

                    key = (row['customer_id'], row['invoice_number'])
                    if key in existing_invoices:
                        if existing_invoices[key] == (row['amount'], row['due_date']):
                            result['skipped'] += 1
                        else:
                            result['rejected'] += 1
                            result['errors'].append({
                                'line': line,
                                'reason': 'Invoice already exists with different details',
                            })
                        continue

                    outcome = insert_invoice(db, row)
                    existing_invoices[key] = (row['amount'], row['due_date'])
                else:
                    try:
                        row = normalize(row,kind,customers)
                    except ValueError as exc:
                        result['rejected'] += 1
                        result['errors'].append({'line': line, 'reason': str(exc)})
                        continue
                    outcome = insert_payment(db, row, find_invoice(db, row))
                result[outcome] += 1
            except ValueError as exc:
                result['rejected'] += 1
                result['errors'].append({'line': line, 'reason': str(exc)})
    return result

    