"""Create-only, resumable training-data seed for MoySklad JSON API 1.2."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import error, parse, request
import uuid

BASE = 'https://api.moysklad.ru/api/remap/1.2'
NAMESPACE = 'a2s-demo-v1:'
DOCUMENT_KINDS = {'enter', 'supply', 'demand', 'cashin', 'cashout', 'move'}
# The document types below document immutable syncId in the public API.
SYNC_ID_KINDS = {'enter', 'supply', 'demand', 'cashin', 'cashout'}


class SeedError(Exception):
    """A sanitized error safe to display during a recorded lesson."""


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, token: str, timeout: int = 30):
        if not token or any(c in token for c in '\r\n\x00'):
            raise SeedError('Credential is missing or malformed')
        self._token = token
        self.timeout = timeout
        self._opener = request.build_opener(NoRedirect())

    @staticmethod
    def _url(route: str, params: dict | None = None) -> str:
        url = route if route.startswith(('https://', 'http://')) else BASE + '/' + route.lstrip('/')
        parsed = parse.urlsplit(url)
        allowed = parse.urlsplit(BASE)
        if parsed.scheme != 'https' or parsed.netloc != allowed.netloc or not parsed.path.startswith(allowed.path + '/') or parsed.fragment:
            raise SeedError('Refusing an API URL outside the configured MoySklad origin')
        if params:
            url += ('&' if parsed.query else '?') + parse.urlencode(params)
        return url

    def request(self, method: str, route: str, payload: dict | None = None, params: dict | None = None) -> Any:
        url = self._url(route, params)
        if method not in {'GET', 'POST'}:
            raise SeedError('This adapter permits only reads and create requests')
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
        req = request.Request(url, data=body, method=method, headers={
            'Authorization': 'Bearer ' + self._token,
            'Accept': 'application/json;charset=utf-8',
            'Accept-Encoding': 'gzip',
            'Content-Type': 'application/json;charset=utf-8',
        })
        endpoint = parse.urlsplit(url).path.removeprefix(parse.urlsplit(BASE).path)
        try:
            with self._opener.open(req, timeout=self.timeout) as response:
                raw = response.read()
                if response.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except error.HTTPError as exc:
            codes = []
            try:
                raw = exc.read()
                if exc.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                data = json.loads(raw)
                codes = [row['code'] for row in data.get('errors', []) if isinstance(row, dict) and isinstance(row.get('code'), int)]
            except Exception:
                pass
            # Never include error text, response bodies, headers or request payloads.
            exc.close()
            raise SeedError(f'{method} {endpoint}: HTTP {exc.code}; API codes {codes}') from None
        except Exception as exc:
            raise SeedError(f'{method} {endpoint}: {type(exc).__name__}; no automatic write retry') from None

    def get(self, route: str, params: dict | None = None) -> Any:
        return self.request('GET', route, params=params)

    def get_all(self, route: str, params: dict | None = None) -> list[dict]:
        rows = []
        current = route
        seen = set()
        query = {'limit': 1000, **(params or {})}
        while current:
            self._url(current)  # Validate even when get() is replaced in offline tests.
            if current in seen:
                raise SeedError('API pagination cycle detected')
            seen.add(current)
            data = self.get(current, query)
            if not isinstance(data.get('rows'), list):
                raise SeedError('API collection response has no rows array')
            rows.extend(data['rows'])
            current = data.get('meta', {}).get('nextHref')
            query = None
        return rows


def load_token(path: Path) -> str:
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError):
        raise SeedError('Unable to read the designated credential file') from None
    values = []
    for line in lines:
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'MOYSKLAD_API_TOKEN':
            values.append(value.strip())
    if len(values) != 1 or not values[0]:
        raise SeedError('Credential file must contain exactly one nonempty MOYSKLAD_API_TOKEN')
    return values[0]


def _reference_identity(href: Any) -> str | None:
    if not isinstance(href, str) or not href.startswith('https://'):
        return None
    try:
        Client._url(href)
    except SeedError:
        return None
    return parse.urlunsplit(parse.urlsplit(href)._replace(query='', fragment=''))


def meta_ref(row: dict) -> dict:
    meta = row.get('meta', {})
    Client._url(meta.get('href', ''))
    if not meta.get('type'):
        raise SeedError('API entity is missing reference metadata')
    identity = _reference_identity(meta.get('href'))
    if identity is None:
        raise SeedError('API entity has invalid reference metadata')
    return {'meta': {**{key: meta[key] for key in ('type', 'mediaType') if key in meta}, 'href': identity}}


def _normal(value: Any) -> Any:
    if isinstance(value, dict):
        if 'rows' in value:
            return _normal(value['rows'])
        if 'meta' in value:
            return {'meta': {'href': value['meta'].get('href')}}
        return {key: _normal(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_normal(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _matches(expected: Any, actual: Any, field: str | None = None) -> bool:
    if isinstance(expected, dict):
        if 'meta' in expected:
            identity = _reference_identity(expected['meta'].get('href'))
            if identity is None or not isinstance(actual, dict) or identity != _reference_identity(actual.get('meta', {}).get('href')):
                return False
            return all(_matches(value, actual.get(key), key) for key, value in expected.items() if key != 'meta')
        return isinstance(actual, dict) and all(_matches(value, actual.get(key), key) for key, value in expected.items())
    if isinstance(expected, list):
        if isinstance(actual, dict) and 'rows' in actual:
            actual = actual['rows']
        if not isinstance(actual, list) or len(expected) != len(actual):
            return False
        # Arrays are semantically sets of positions/links for this adapter.
        unmatched = list(actual)
        for value in expected:
            match = next((i for i, row in enumerate(unmatched) if _matches(value, row)), None)
            if match is None:
                return False
            unmatched.pop(match)
        return True
    if field in {'moment', 'accrualDate'} and isinstance(expected, str) and isinstance(actual, str):
        try:
            return datetime.fromisoformat(expected) == datetime.fromisoformat(actual)
        except ValueError:
            return False
    return expected == actual


class Seeder:
    def __init__(self, client: Client, apply: bool = False, receipt: Path | None = None, progress: bool = False):
        self.client = client
        self.apply = apply
        self.receipt = receipt
        if receipt is not None and receipt.expanduser().resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise SeedError('Receipt must be outside the public checkout')
        self.progress = progress
        self.index: dict[str, dict[str, dict]] = {}
        self.mapping: dict[str, dict] = {}
        self.counts = Counter(created=0, reused=0, planned=0)
        self.by_kind: dict[str, Counter] = {}

    def _collection(self, kind: str) -> dict[str, dict]:
        if kind not in self.index:
            rows = self.client.get_all('entity/' + kind)
            records = {}
            for row in rows:
                code = row.get('externalCode', '')
                if code.startswith(NAMESPACE):
                    if code in records:
                        raise SeedError(f'Duplicate demo externalCode in {kind}; no writes attempted for this item')
                    records[code] = row
            self.index[kind] = records
        return self.index[kind]

    def _save(self):
        if self.receipt is None:
            return
        target = self.receipt.expanduser().resolve()
        checkout = Path(__file__).resolve().parents[1]
        if target.is_relative_to(checkout):
            raise SeedError('Receipt must be outside the public checkout')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(self.summary(), stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.chmod(temporary, 0o600)
        temporary.replace(target)

    def summary(self):
        return {'namespace': NAMESPACE, 'applied': self.apply, 'counts': dict(self.counts),
                'by_kind': {kind: dict(counts) for kind, counts in self.by_kind.items()}, 'mapping': self.mapping}

    def ensure(self, kind: str, code: str, fields: dict) -> dict:
        external = NAMESPACE + code
        payload = {'externalCode': external, **fields}
        if kind in SYNC_ID_KINDS:
            payload['syncId'] = str(uuid.uuid5(uuid.NAMESPACE_URL, 'https://agent2s.demo/' + external))
        records = self._collection(kind)
        existing = records.get(external)
        if existing is not None:
            if kind in DOCUMENT_KINDS:
                params = {'expand': 'positions'} if 'positions' in payload else None
                existing = self.client.get(f'entity/{kind}/{existing["id"]}', params)
            if not _matches(payload, existing):
                raise SeedError(f'Existing demo record drift in {kind} ({code}); refusing overwrite')
            row = existing
            outcome = 'reused'
        elif self.apply:
            row = self.client.request('POST', 'entity/' + kind, payload)
            records[external] = row
            outcome = 'created'
        else:
            identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, external))
            row = {'id': identifier, 'meta': {'href': f'{BASE}/entity/{kind}/{identifier}', 'type': kind, 'mediaType': 'application/json'}, **payload}
            records[external] = row
            outcome = 'planned'
        self.mapping[code] = {'kind': kind, 'id': row['id'], **meta_ref(row)}
        self.counts[outcome] += 1
        self.by_kind.setdefault(kind, Counter(created=0, reused=0, planned=0))[outcome] += 1
        self._save()
        if self.progress:
            print(f'{kind}: {outcome}; created={self.counts["created"]} reused={self.counts["reused"]} planned={self.counts["planned"]}', flush=True)
        return meta_ref(row)

    def run(self, dataset: dict) -> dict:
        # Currency must be checked before any creation, including directories.
        currencies = self.client.get_all('entity/currency')
        default_currencies = [row for row in currencies if row.get('default') is True]
        if len(default_currencies) != 1 or not dataset.get('currency'):
            raise SeedError('Unable to verify the dataset currency against the account default currency')
        if default_currencies[0].get('isoCode') != dataset['currency']:
            raise SeedError('Dataset currency differs from the account default currency; no writes permitted')
        default_currency = meta_ref(default_currencies[0])
        # Load baseline references before any mutation.
        organizations = self.client.get_all('entity/organization')
        if len(organizations) != 1:
            raise SeedError('Select an account with exactly one organization for this training seed')
        organization = meta_ref(organizations[0])
        stores = self.client.get_all('entity/store')
        primary = [row for row in stores if not row.get('externalCode', '').startswith(NAMESPACE)]
        if len(primary) != 1:
            raise SeedError('Expected exactly one original primary warehouse')
        references = {'organization': organization, 'main': meta_ref(primary[0])}
        price_types = self.client.get('context/companysettings/pricetype')
        if not isinstance(price_types, list) or not price_types:
            raise SeedError('No configured product sale price type; refusing incomplete catalog creation')
        sale_price_type = meta_ref(price_types[0])
        # Preflight every affected collection for duplicate codes before creating anything.
        kinds = {'store', 'productfolder', 'product', 'counterparty', 'expenseitem'} | {row['kind'] for row in dataset['documents']}
        if not kinds.issubset(DOCUMENT_KINDS | {'store', 'productfolder', 'product', 'counterparty', 'expenseitem'}):
            raise SeedError('Unsupported demo entity kind')
        for kind in sorted(kinds):
            self._collection(kind)
        references['secondary'] = self.ensure('store', 'STORE-SECONDARY', {'name': 'A2S-DEMO | Второй склад', 'code': 'A2S-DEMO-STORE-2'})
        for symbol, name in [('supplier', 'Учебный поставщик'), ('customer', 'Учебный покупатель'), ('owner', 'Взнос владельца'), ('operations', 'Операционные расходы')]:
            references[symbol] = self.ensure('counterparty', 'AGENT-' + symbol.upper(), {'name': 'A2S-DEMO | ' + name, 'code': 'A2S-DEMO-' + symbol.upper()})
        references['expense-supplier'] = self.ensure('expenseitem', 'EXPENSE-SUPPLIER', {'name': 'A2S-DEMO | Закупка товара', 'code': 'A2S-DEMO-PURCHASES', 'operatingExpenses': False})
        references['expense-operations'] = self.ensure('expenseitem', 'EXPENSE-OPERATIONS', {'name': 'A2S-DEMO | Прочие расходы и учебные налоги', 'code': 'A2S-DEMO-OPEX', 'operatingExpenses': True})
        categories = {}
        for product in dataset['products']:
            category = product['category']
            if category not in categories:
                category_id = uuid.uuid5(uuid.NAMESPACE_URL, category).hex[:12]
                categories[category] = self.ensure('productfolder', 'FOLDER-' + category_id, {'name': 'A2S-DEMO | ' + category})
            fields = {'code': product['code'], 'name': product['name'] if 'A2S-DEMO' in product['name'] else 'A2S-DEMO | ' + product['name'], 'article': product['article'],
                      'buyPrice': {'value': product['cost'], 'currency': default_currency}, 'salePrices': [{'value': product['sale_price'], 'priceType': sale_price_type, 'currency': default_currency}], 'productFolder': categories[category]}
            references[product['code']] = self.ensure('product', product['code'], fields)
        for document in dataset['documents']:
            kind = document['kind']
            code = document['code']
            fields = {'name': code, 'code': code, 'moment': document['moment'], 'applicable': True,
                      'organization': organization, 'description': document.get('description', 'A2S-DEMO: вымышленные данные учебного проекта')}
            if 'store' in document:
                fields['store'] = references[document['store']]
            if kind == 'move':
                fields.pop('store', None)
                fields['sourceStore'] = references[document['store']]
                fields['targetStore'] = references[document['target_store']]
            if 'agent' in document:
                fields['agent'] = references[document['agent']]
            if 'sum' in document:
                fields['sum'] = document['sum']
            if 'positions' in document:
                fields['positions'] = [{'quantity': row['quantity'], 'price': row['price'], 'assortment': references[row['product']]} for row in document['positions']]
            if kind in {'demand', 'supply'}:
                fields['vatEnabled'] = False
                for position in fields.get('positions', []):
                    position['vat'] = 0
                    position['vatEnabled'] = False
            if kind in {'cashin', 'cashout'}:
                fields['paymentPurpose'] = document.get('description', 'A2S-DEMO: учебная операция')
                if document.get('operation'):
                    fields['operations'] = [{**references[document['operation']], 'linkedSum': document['sum']}]
                elif kind == 'cashout':
                    fields['noClosingDocs'] = True
                    fields['accrualDate'] = document['moment']
                if kind == 'cashout':
                    fields['expenseItem'] = references['expense-supplier' if document.get('agent') == 'supplier' else 'expense-operations']
            references[code] = self.ensure(kind, code, fields)
        return self.summary()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Create-only MoySklad training seed; dry-run is the default')
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.apply and args.receipt is None:
            raise SeedError('--apply requires a private --receipt outside the checkout')
        if args.receipt is not None and args.receipt.expanduser().resolve().is_relative_to(Path(__file__).resolve().parents[1]):
            raise SeedError('Receipt must be outside the public checkout')
        if __package__:
            from .demo_dataset import build_dataset
        else:
            from demo_dataset import build_dataset
        client = Client(load_token(args.env_file))
        result = Seeder(client, apply=args.apply, receipt=args.receipt, progress=args.apply).run(build_dataset())
        print(json.dumps({key: result[key] for key in ('namespace', 'applied', 'counts', 'by_kind')}, ensure_ascii=False, indent=2))
        return 0
    except SeedError as exc:
        print('Seed stopped: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
