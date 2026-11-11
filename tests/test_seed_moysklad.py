import copy
import io
import json
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from tools.seed_moysklad import Client, SeedError, Seeder, _matches, meta_ref

BASE = 'https://api.moysklad.ru/api/remap/1.2'


def entity(kind, identifier, **fields):
    return {'id': identifier, 'meta': {'href': f'{BASE}/entity/{kind}/{identifier}', 'type': kind, 'mediaType': 'application/json'}, **fields}


class MemoryClient:
    def __init__(self):
        self.rows = {'organization': [entity('organization', 'org')], 'store': [entity('store', 'main')], 'currency': [entity('currency', 'rub', isoCode='RUB', default=True)]}
        self.writes = []

    def get_all(self, route, params=None):
        kind = route.split('/')[1]
        rows = copy.deepcopy(self.rows.get(kind, []))
        if kind in {'cashin', 'cashout'}:
            for row in rows:
                for field in ('operations', 'paymentPurpose', 'accrualDate'):
                    row.pop(field, None)
        return rows

    def get(self, route, params=None):
        if route == 'context/companysettings/pricetype':
            return [entity('pricetype', 'sale-price')]
        parts = route.split('/')
        row = copy.deepcopy(next(x for x in self.rows[parts[1]] if x['id'] == parts[2]))
        if params and params.get('expand') == 'positions':
            row['meta']['href'] += '?expand=positions'
        return row

    def request(self, method, route, payload=None):
        if method != 'POST':
            raise AssertionError('Only create writes are permitted')
        self.writes.append((method, route, copy.deepcopy(payload)))
        kind = route.split('/')[1]
        row = entity(kind, str(len(self.writes)), **copy.deepcopy(payload))
        if kind in {'demand', 'supply'} and row.get('vatEnabled') is False:
            row.pop('vatIncluded', None)
        if isinstance(row.get('positions'), list):
            row['positions'] = {'rows': row['positions']}
        self.rows.setdefault(kind, []).append(row)
        return copy.deepcopy(row)


def dataset():
    return {'currency': 'RUB', 'products': [{'code': 'A2S-DEMO-P001', 'name': 'Кружка', 'article': 'DEMO001', 'cost': 10000, 'sale_price': 16000, 'category': 'Посуда'}],
            'documents': [
                {'code': 'A2S-DEMO-OPEN', 'kind': 'enter', 'moment': '2026-05-15 09:00:00', 'store': 'main', 'positions': [{'product': 'A2S-DEMO-P001', 'quantity': 100, 'price': 10000}]},
                {'code': 'A2S-DEMO-CAPITAL', 'kind': 'cashin', 'moment': '2026-05-15 09:00:00', 'agent': 'owner', 'sum': 300000000},
                {'code': 'A2S-DEMO-SALE', 'kind': 'demand', 'moment': '2026-05-16 09:00:00', 'store': 'main', 'agent': 'customer', 'positions': [{'product': 'A2S-DEMO-P001', 'quantity': 2, 'price': 16000}]},
                {'code': 'A2S-DEMO-PAID', 'kind': 'cashin', 'moment': '2026-05-16 10:00:00', 'agent': 'customer', 'sum': 32000, 'operation': 'A2S-DEMO-SALE'}], 'expected': {}}


class SeederTests(unittest.TestCase):
    def test_meta_reference_sibling_amount_is_checked_for_drift(self):
        reference = {'meta': {'href': BASE + '/entity/demand/sale', 'type': 'demand'}, 'linkedSum': 32000}
        same = {'meta': {'href': BASE + '/entity/demand/sale', 'type': 'demand', 'mediaType': 'application/json'}, 'linkedSum': 32000}
        changed = {**same, 'linkedSum': 31000}
        self.assertTrue(_matches(reference, same))
        self.assertFalse(_matches(reference, changed))
        self.assertTrue(_matches({'meta': reference['meta']}, same))

    def test_reference_identity_ignores_presentation_query_only(self):
        expanded = entity('demand', 'sale')
        expanded['meta']['href'] += '?expand=positions'
        reference = meta_ref(expanded)
        self.assertEqual(reference['meta']['href'], BASE + '/entity/demand/sale')
        self.assertTrue(_matches(reference, expanded))
        self.assertFalse(_matches(reference, entity('demand', 'different-sale')))
        foreign = {'meta': {'href': 'https://attacker.invalid/entity/demand/sale'}}
        self.assertFalse(_matches(reference, foreign))

    def test_datetime_precision_normalized_only_for_datetime_fields(self):
        self.assertTrue(_matches({'moment': '2026-05-15 09:00:00'}, {'moment': '2026-05-15 09:00:00.000'}))
        self.assertTrue(_matches({'accrualDate': '2026-05-15 09:00:00'}, {'accrualDate': '2026-05-15 09:00:00.000'}))
        self.assertFalse(_matches({'moment': '2026-05-15 09:00:00'}, {'moment': '2026-05-15 09:00:01.000'}))
        self.assertFalse(_matches({'name': '2026-05-15 09:00:00'}, {'name': '2026-05-15 09:00:00.000'}))

    def test_resume_accepts_moysklad_millisecond_timestamp_precision(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        for rows in client.rows.values():
            for row in rows:
                if 'moment' in row:
                    row['moment'] += '.000'
        writes = len(client.writes)
        result = Seeder(client, apply=True).run(dataset())
        self.assertEqual(len(client.writes), writes)
        self.assertEqual(result['counts']['created'], 0)

    def test_dry_run_creates_nothing(self):
        client = MemoryClient()
        result = Seeder(client, apply=False).run(dataset())
        self.assertEqual(client.writes, [])
        self.assertGreater(result['counts']['planned'], 0)

    def test_repeated_seed_reuses_every_record(self):
        client = MemoryClient()
        first = Seeder(client, apply=True).run(dataset())
        self.assertGreater(first['counts']['created'], 0)
        written = len(client.writes)
        second = Seeder(client, apply=True).run(dataset())
        self.assertEqual(len(client.writes), written)
        self.assertEqual(second['counts']['created'], 0)
        self.assertEqual(second['counts']['reused'], first['counts']['created'])

    def test_existing_demo_drift_is_rejected_without_overwrite(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        client.rows['product'][0]['name'] = 'Changed outside seeder'
        before = len(client.writes)
        with self.assertRaisesRegex(SeedError, 'drift'):
            Seeder(client, apply=True).run(dataset())
        self.assertEqual(before, len(client.writes))

    def test_products_have_configured_sale_price_type(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        sale_price = client.rows['product'][0]['salePrices'][0]
        self.assertEqual(sale_price['value'], 16000)
        self.assertEqual(sale_price['currency']['meta']['type'], 'currency')
        self.assertEqual(client.rows['product'][0]['buyPrice']['currency']['meta']['type'], 'currency')
        self.assertEqual(sale_price['priceType']['meta']['type'], 'pricetype')

    def test_resume_uses_full_document_not_collection_projection(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        self.assertNotIn('operations', client.get_all('entity/cashin')[1])
        writes = len(client.writes)
        result = Seeder(client, apply=True).run(dataset())
        self.assertEqual(result['counts']['created'], 0)
        self.assertEqual(len(client.writes), writes)

    def test_no_vat_documents_omit_ignored_vat_included_field(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        for _, route, payload in client.writes:
            if route in {'entity/demand', 'entity/supply'}:
                self.assertFalse(payload['vatEnabled'])
                self.assertNotIn('vatIncluded', payload)
        self.assertEqual(Seeder(client, apply=True).run(dataset())['counts']['created'], 0)

    def test_money_documents_link_sales_but_not_owner_capital(self):
        client = MemoryClient()
        Seeder(client, apply=True).run(dataset())
        owner, paid = client.rows['cashin']
        self.assertNotIn('operations', owner)
        self.assertNotIn('noClosingDocs', owner)
        self.assertEqual(paid['operations'][0]['linkedSum'], 32000)
        self.assertEqual(paid['operations'][0]['meta']['type'], 'demand')

    def test_public_receipt_path_rejected_before_any_write(self):
        client = MemoryClient()
        with self.assertRaisesRegex(SeedError, 'outside'):
            Seeder(client, apply=True, receipt=Path('demo/public-receipt.json')).run(dataset())
        self.assertEqual(client.writes, [])

    def test_currency_mismatch_is_rejected_before_writes(self):
        client = MemoryClient()
        client.rows['currency'][0]['isoCode'] = 'KZT'
        with self.assertRaisesRegex(SeedError, 'currency'):
            Seeder(client, apply=True).run(dataset())
        self.assertEqual(client.writes, [])

    def test_http_error_never_contains_server_echo_or_credential(self):
        secret = 'never-print-this-token'
        error = HTTPError(BASE + '/entity/product', 401, secret, {}, io.BytesIO(json.dumps({'errors': [{'code': 1056, 'error': secret}]}).encode()))
        with patch('urllib.request.OpenerDirector.open', side_effect=error):
            with self.assertRaises(SeedError) as caught:
                Client(secret).get('entity/product')
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn('401', str(caught.exception))

    def test_foreign_pagination_url_is_rejected(self):
        client = Client('never-print-this-token')
        with self.assertRaises(SeedError):
            client.get('https://attacker.invalid/steal')

    def test_pagination_follows_every_page(self):
        client = Client('never-print-this-token')
        with patch.object(client, 'get', side_effect=[{'rows': [{'id': 1}], 'meta': {'nextHref': BASE + '/entity/product?offset=1'}}, {'rows': [{'id': 2}], 'meta': {}}]):
            self.assertEqual(client.get_all('entity/product'), [{'id': 1}, {'id': 2}])


if __name__ == '__main__':
    unittest.main()
