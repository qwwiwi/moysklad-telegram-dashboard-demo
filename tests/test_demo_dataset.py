import unittest
from tools.demo_dataset import build_dataset

class DatasetTests(unittest.TestCase):
    def test_opening_and_repeatability(self):
        data = build_dataset()
        self.assertEqual(data, build_dataset())
        self.assertEqual(len(data['products']), 30)
        self.assertEqual(data['period']['days'], 180)
        self.assertEqual(data['expected']['opening_inventory_cost'], 700_000_000)
        self.assertEqual(data['expected']['opening_cash'], 300_000_000)
        self.assertEqual(data['expected']['closing_inventory_cost'], 700_000_000)

    def test_stock_and_cash_never_negative_and_reconcile(self):
        data = build_dataset()
        stock = {}
        cash = 0
        products = {p['code']: p for p in data['products']}
        sales = costs = operating = 0
        for doc in data['documents']:
            kind = doc['kind']
            for pos in doc.get('positions', []):
                key = (doc['store'], pos['product'])
                qty = pos['quantity']
                if kind in ('enter', 'supply'):
                    stock[key] = stock.get(key, 0) + qty
                elif kind in ('demand', 'move'):
                    stock[key] = stock.get(key, 0) - qty
                    self.assertGreaterEqual(stock[key], 0)
                    if kind == 'move':
                        target = (doc['target_store'], pos['product'])
                        stock[target] = stock.get(target, 0) + qty
                    else:
                        sales += qty * pos['price']
                        costs += qty * products[pos['product']]['cost']
            if kind == 'cashin': cash += doc['sum']
            if kind == 'cashout':
                cash -= doc['sum']
                if doc['agent'] == 'operations': operating += doc['sum']
            self.assertGreaterEqual(cash, 0)
        expected = data['expected']
        self.assertEqual(cash, expected['closing_cash'])
        self.assertEqual(sales, expected['net_sales'])
        self.assertEqual(costs, expected['net_cogs'])
        self.assertEqual(sales - costs - operating, expected['net_management_profit'])
        inventory = sum(q * products[code]['cost'] for (_,code), q in stock.items())
        self.assertEqual(inventory + cash, 1_000_000_000 + expected['net_management_profit'])
        self.assertEqual({f'{store}:{code}':qty for (store,code),qty in stock.items()}, expected['stock_by_store'])

    def test_slow_stock_and_transfer_do_not_count_as_sales(self):
        data = build_dataset()
        slow = set(data['expected']['slow_product_codes'])
        sold = {p['product'] for d in data['documents'] if d['kind']=='demand' for p in d['positions']}
        self.assertEqual(len(slow), 10)
        self.assertFalse(slow & sold)
        self.assertTrue(any(d['kind']=='move' for d in data['documents']))
        codes = [d['code'] for d in data['documents']]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual([d['moment'] for d in data['documents']], sorted(d['moment'] for d in data['documents']))
        self.assertTrue(all(d['moment'][:10] <= data['period']['to'] for d in data['documents']))

if __name__ == '__main__': unittest.main()
