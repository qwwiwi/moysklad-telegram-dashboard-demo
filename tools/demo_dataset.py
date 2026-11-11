"""Deterministic training ledger. All money values are integer kopecks."""
from collections import defaultdict
from datetime import date, timedelta
from random import Random

NAMESPACE = 'a2s-demo-v1'


def build_dataset():
    """Return reproducible products, ordered source documents and ledger totals."""
    rng = Random(20261111)
    end = date(2026, 11, 10)
    start = end - timedelta(days=179)
    catalog = [
        ('Термокружки', ['Термокружка Север 350 мл', 'Термокружка Город 400 мл',
         'Термокружка Утро 450 мл', 'Термокружка Волна 500 мл', 'Термокружка Лес 350 мл',
         'Термокружка Маршрут 450 мл', 'Термокружка Камень 400 мл', 'Термокружка Туман 500 мл',
         'Термокружка Песок 350 мл', 'Термокружка Полдень 600 мл']),
        ('Контейнеры', ['Контейнер Квадрат 1 л', 'Контейнер Квадрат 2 л',
         'Контейнер Круг 1 л', 'Контейнер Круг 2 л', 'Контейнер Стекло 0,8 л',
         'Контейнер Стекло 1,5 л', 'Ланч-бокс Два отдела', 'Ланч-бокс Три отдела',
         'Набор контейнеров Малый', 'Набор контейнеров Большой']),
        ('Органайзеры', ['Органайзер Полка', 'Органайзер Ящик', 'Органайзер Стол',
         'Органайзер Кухня', 'Органайзер Ванная', 'Органайзер Шкаф',
         'Органайзер Корзина', 'Органайзер Модуль', 'Органайзер Угол', 'Органайзер Комплект'])]
    products = []
    for category, names in catalog:
        for name in names:
            index = len(products)
            cost = (1000 + 100 * (index % 10)) * 100
            products.append({'code': f'A2S-DEMO-P{index+1:03}', 'article': f'A2S-{index+1:03}',
                             'name': f'[A2S-DEMO] {name}', 'category': category,
                             'cost': cost, 'sale_price': cost * 16 // 10})
    by_code = {p['code']: p for p in products}
    docs = []

    def add(code, kind, offset, time='10:00:00', **fields):
        docs.append({'code': f'A2S-DEMO-{code}', 'kind': kind,
                     'moment': f'{start+timedelta(days=offset)} {time}',
                     'description': 'Учебные данные Agent2s. Не реальные операции.', **fields})

    for store, base_qty in [('main', 130), ('secondary', 30)]:
        positions = [{'product': p['code'], 'quantity': base_qty + (40 if store=='main' and i==0 else 0),
                      'price': p['cost']} for i,p in enumerate(products)]
        add(f'OPEN-{store.upper()}', 'enter', 0, store=store, positions=positions)
    add('OWNER-CASH', 'cashin', 0, '09:00:00', agent='owner', sum=300_000_000,
        description='Учебный взнос владельца: 3 млн рублей наличными; ещё 7 млн внесены товарным остатком. Не выручка.')

    for speed, subset, offsets, low, high in [
        ('FAST', products[:10], range(3,179,7), 35,45),
        ('REGULAR', products[10:20], range(5,179,14), 8,12)]:
        for n,offset in enumerate(offsets,1):
            positions = [{'product':p['code'],'quantity':rng.randint(low,high),'price':p['sale_price']} for p in subset]
            code=f'SALE-{speed}-{n:02}'
            sale_sum=sum(p['quantity']*p['price'] for p in positions)
            add(code,'demand',offset,store='main',agent='customer',positions=positions)
            add(f'PAID-{speed}-{n:02}','cashin',offset,'11:00:00',agent='customer',sum=sale_sum,operation=f'A2S-DEMO-{code}')
            purchase=[dict(p,price=by_code[p['product']]['cost']) for p in positions]
            purchase_sum=sum(p['quantity']*p['price'] for p in purchase)
            buy_code=f'BUY-{speed}-{n:02}'
            add(buy_code,'supply',offset+1,store='main',agent='supplier',positions=purchase)
            add(f'VENDOR-{speed}-{n:02}','cashout',offset+1,'11:00:00',agent='supplier',sum=purchase_sum,operation=f'A2S-DEMO-{buy_code}')

    for n,offset in enumerate(range(29,180,30),1):
        add(f'OPEX-{n:02}','cashout',offset,'19:00:00',agent='operations',sum=90_000_000,
            description='Учебные расходы за 30 дней: команда, аренда, логистика, реклама и условные налоги. Не закупка товара.')
    add('TRANSFER-01','move',120,store='main',target_store='secondary',
        positions=[{'product':products[10]['code'],'quantity':10,'price':products[10]['cost']}],
        description='Учебное перемещение между складами. Не продажа и не расход денег.')
    docs.sort(key=lambda d:(d['moment'],d['code']))
    stock=defaultdict(int)
    cash=sales=cogs=opex=0
    for d in docs:
        for p in d.get('positions',[]):
            key=(d['store'],p['product']);qty=p['quantity']
            if d['kind'] in ('enter','supply'):stock[key]+=qty
            elif d['kind'] in ('demand','move'):
                stock[key]-=qty
                if stock[key]<0:raise ValueError('Synthetic ledger produced negative stock')
                if d['kind']=='move':stock[(d['target_store'],p['product'])]+=qty
                else:
                    sales+=qty*p['price'];cogs+=qty*by_code[p['product']]['cost']
        if d['kind']=='cashin':cash+=d['sum']
        elif d['kind']=='cashout':
            cash-=d['sum']
            if d['agent']=='operations':opex+=d['sum']
        if cash<0:raise ValueError('Synthetic ledger produced negative cash')
    inventory=sum(q*by_code[code]['cost'] for (_,code),q in stock.items())
    return {'synthetic':True,'namespace':NAMESPACE,'seed':20261111,'currency':'RUB','money_unit':'kopeck',
            'period':{'from':str(start),'to':str(end),'days':180,'timezone':'Europe/Moscow'},
            'products':products,'documents':docs,'expected':{
                'opening_inventory_cost':700_000_000,'opening_cash':300_000_000,
                'closing_inventory_cost':inventory,'closing_cash':cash,'net_sales':sales,'net_cogs':cogs,
                'gross_profit':sales-cogs,'operating_expenses':opex,'net_management_profit':sales-cogs-opex,
                'stock_by_store':{f'{store}:{code}':qty for (store,code),qty in stock.items()},
                'slow_product_codes':[p['code'] for p in products[20:]],
                'slow_inventory_cost':sum(q*by_code[code]['cost'] for (_,code),q in stock.items() if code in {p['code'] for p in products[20:]})}}


if __name__=='__main__':
    import json
    data=build_dataset()
    print(json.dumps({'period':data['period'],'products':len(data['products']),'documents':len(data['documents']),
                      'expected':{k:v for k,v in data['expected'].items() if k not in ('stock_by_store','slow_product_codes')}},ensure_ascii=False,indent=2))
