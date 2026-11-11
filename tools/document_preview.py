"""Bounded, non-executing previews for privately stored spreadsheet files."""
import csv
import io
import posixpath
import re
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_ROWS = 50000
MAX_COLUMNS = 100
MAX_XML_BYTES = 32 * 1024 * 1024
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


class PreviewError(ValueError):
    pass


def _xml(archive, name):
    data = archive.read(name)
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise PreviewError('XML с DTD или сущностями не поддерживается.')
    return ET.fromstring(data)


def _xlsx(path):
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if len(infos) > 10000 or sum(i.file_size for i in infos) > MAX_XML_BYTES:
            raise PreviewError('Распакованный Excel превышает лимит предпросмотра 32 МБ.')
        if len({i.filename for i in infos}) != len(infos):
            raise PreviewError('В архиве Excel повторяются имена файлов.')
        shared = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared = [''.join(si.itertext()) for si in _xml(archive, 'xl/sharedStrings.xml').findall('s:si', NS)]
        workbook = _xml(archive, 'xl/workbook.xml')
        relationships = _xml(archive, 'xl/_rels/workbook.xml.rels')
        targets = {r.attrib.get('Id'): r.attrib.get('Target', '') for r in relationships
                   if r.attrib.get('TargetMode') != 'External'}
        for sheet in workbook.findall('s:sheets/s:sheet', NS):
            relation = sheet.attrib.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target = targets.get(relation, '')
            name = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            if not name.startswith('xl/worksheets/'):
                continue
            root = _xml(archive, name)
            rows, warnings, limited = [], [], False
            for row in root.findall('s:sheetData/s:row', NS):
                values = []
                for cell in row.findall('s:c', NS):
                    ref = re.match(r'([A-Z]+)', cell.attrib.get('r', ''))
                    index = len(values)
                    if ref:
                        index = 0
                        for char in ref[1]:
                            index = index * 26 + ord(char) - 64
                        index -= 1
                    if index >= MAX_COLUMNS:
                        warnings.append('Показаны только первые 100 колонок.')
                        continue
                    while len(values) <= index:
                        values.append('')
                    if cell.find('s:f', NS) is not None:
                        warnings.append('Формулы не вычислялись, ячейки с формулами пропущены.')
                        value = ''
                    elif cell.attrib.get('t') == 'inlineStr':
                        value = ''.join(cell.find('s:is', NS).itertext()) if cell.find('s:is', NS) is not None else ''
                    else:
                        value = cell.findtext('s:v', '', NS)
                        if cell.attrib.get('t') == 's':
                            try:
                                number = int(value)
                                value = shared[number] if number >= 0 else ''
                            except (ValueError, IndexError):
                                raise PreviewError('Повреждён справочник строк Excel.') from None
                    values[index] = value[:2000]
                    if len(value) > 2000:
                        warnings.append('Длинные ячейки сокращены до 2000 символов.')
                if any(str(v).strip() for v in values):
                    rows.append(values)
                    if len(rows) > MAX_ROWS + 1:
                        rows.pop()
                        limited = True
                        break
            if rows:
                return rows, sheet.attrib.get('name', 'Лист'), warnings, limited
        raise PreviewError('В Excel не найдены заполненные листы.')


def _csv(path):
    if path.stat().st_size > 10 * 1024 * 1024:
        raise PreviewError('CSV превышает лимит предпросмотра 10 МБ. Оригинал доступен для скачивания.')
    raw = path.read_bytes()
    warnings = []
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1251')
        warnings.append('Кодировка определена как Windows-1251.')
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel
    rows, limited = [], False
    csv.field_size_limit(2 * 1024 * 1024)
    for row in csv.reader(io.StringIO(text), dialect):
        if not any(v.strip() for v in row):
            continue
        if len(row) > MAX_COLUMNS:
            warnings.append('Показаны только первые 100 колонок.')
        if any(len(v) > 2000 for v in row):
            warnings.append('Длинные ячейки сокращены до 2000 символов.')
        rows.append([v[:2000] for v in row[:MAX_COLUMNS]])
        if len(rows) > MAX_ROWS + 1:
            rows.pop()
            limited = True
            break
    if not rows:
        raise PreviewError('В CSV нет заполненных строк.')
    return rows, None, warnings, limited


def _number(value):
    value = str(value).strip().replace('\u00a0', '').replace(' ', '').replace(',', '.')
    if not re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        raise ValueError()
    number = Decimal(value)
    if not number.is_finite() or len(number.as_tuple().digits) > 30:
        raise ValueError()
    return number


def summarize(path, filename):
    """Return display-safe metadata and values, never evaluate formulas or macros."""
    path = Path(path)
    empty = {'columns': [], 'rows': [], 'row_count': None, 'truncated': False, 'warnings': []}
    try:
        if path.stat().st_size > 100 * 1024 * 1024:
            raise PreviewError('Файл превышает лимит предпросмотра 100 МБ.')
        suffix = Path(filename).suffix.lower()
        if suffix not in {'.xlsx', '.csv'}:
            raise PreviewError('Предпросмотр доступен для XLSX и CSV.')
        table, sheet, warnings, limited = _xlsx(path) if suffix == '.xlsx' else _csv(path)
        columns, rows = table[0], table[1:]
        width = max(len(columns), max((len(row) for row in rows), default=0))
        columns = columns + ['Колонка ' + str(i + 1) for i in range(len(columns), width)]
        details = [('Лист «' + sheet + '».') if sheet else 'CSV.']
        details.append(('Не менее ' if limited else '') + str(len(rows)) + ' строк данных, ' + str(width) + ' колонок.')
        if sheet:
            warnings.append('Предпросмотр и итоги относятся только к первому заполненному листу.')
        for names, label in [({'количество'}, 'Единиц товара'), ({'к оплате ₽', 'к оплате руб', 'к оплате руб.'}, 'К оплате, ₽')]:
            indexes = [i for i, col in enumerate(columns) if col.strip().casefold() in names]
            if len(indexes) != 1 or not rows or limited or any('сокращены' in w for w in warnings):
                continue
            try:
                total = sum((_number(row[indexes[0]]) for row in rows), Decimal(0))
                details.append(label + ' — ' + format(total, 'f') + '.')
            except (ValueError, IndexError, InvalidOperation):
                warnings.append('Итог «' + columns[indexes[0]] + '» не рассчитан из-за пропущенных или нечисловых значений.')
        return {'columns': columns, 'rows': [(row + [''] * width)[:width] for row in rows[:20]],
                'row_count': len(rows), 'sheet': sheet, 'summary': ' '.join(details),
                'truncated': limited or len(rows) > 20, 'warnings': list(dict.fromkeys(warnings))}
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, UnicodeError, csv.Error, PreviewError) as error:
        message = str(error) if isinstance(error, PreviewError) else 'Не удалось прочитать таблицу. Оригинал доступен для скачивания.'
        return {**empty, 'summary': message, 'warnings': [message]}
