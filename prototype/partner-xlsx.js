/* Read a single-sheet shipment workbook locally. Formula cells require exported values. */
window.readPartnerXlsx = async function readPartnerXlsx(file) {
  const fail = message => { throw new Error(message); };
  if (!/\.xlsx$/i.test(file.name) || file.size > 5 * 1024 * 1024) fail('Выберите файл .xlsx размером до 5 МБ.');
  const bytes = new Uint8Array(await file.arrayBuffer());
  const view = new DataView(bytes.buffer);
  const u16 = offset => view.getUint16(offset, true);
  const u32 = offset => view.getUint32(offset, true);
  const decoder = new TextDecoder();
  let tail = bytes.length - 22;
  while (tail >= Math.max(0, bytes.length - 65557) && u32(tail) !== 0x06054b50) tail--;
  if (tail < Math.max(0, bytes.length - 65557)) fail('Файл не распознан как книга Excel.');
  const count = u16(tail + 10);
  if (count > 1000) fail('Для отчёта нужен файл с одной таблицей.');
  const entries = new Map();
  let at = u32(tail + 16);
  for (let i = 0; i < count; i++) {
    if (u32(at) !== 0x02014b50) fail('Не удалось прочитать каталог XLSX.');
    const nameLength = u16(at + 28);
    const name = decoder.decode(bytes.subarray(at + 46, at + 46 + nameLength));
    entries.set(name, {method:u16(at+10), packed:u32(at+20), offset:u32(at+42)});
    at += 46 + nameLength + u16(at + 30) + u16(at + 32);
  }
  async function xml(name) {
    const entry = entries.get(name);
    if (!entry) fail('В книге отсутствует таблица отчёта.');
    const begin = entry.offset + 30 + u16(entry.offset+26) + u16(entry.offset+28);
    let stream = new Blob([bytes.subarray(begin, begin + entry.packed)]).stream();
    if (entry.method === 8) stream = stream.pipeThrough(new DecompressionStream('deflate-raw'));
    else if (entry.method !== 0) fail('Неподдерживаемое сжатие XLSX.');
    const reader = stream.getReader(), parts = [];
    let length = 0;
    for (;;) {
      const {value,done} = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 8 * 1024 * 1024) { await reader.cancel(); fail('Таблица превышает лимит размера.'); }
      parts.push(value);
    }
    const doc = new DOMParser().parseFromString(await new Blob(parts).text(), 'application/xml');
    if (doc.querySelector('parsererror') || doc.doctype) fail('Некорректная структура XLSX.');
    return doc;
  }
  const nodes = (element, name) => Array.from(element.getElementsByTagNameNS('*', name));
  const workbook = await xml('xl/workbook.xml');
  const sheets = nodes(workbook,'sheet');
  if (sheets.length !== 1) fail('Сохраните лист с отгрузками отдельным файлом .xlsx.');
  const rels = await xml('xl/_rels/workbook.xml.rels');
  const relId = sheets[0].getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships','id');
  const rel = nodes(rels,'Relationship').find(r => r.getAttribute('Id') === relId);
  const target = rel?.getAttribute('Target') || '';
  const path = target.startsWith('/') ? target.slice(1) : 'xl/' + target.replace(/^\.\//,'');
  if (!/^xl\/worksheets\/[^/]+\.xml$/.test(path)) fail('Неподдерживаемая ссылка на лист.');
  const strings = entries.has('xl/sharedStrings.xml') ? nodes(await xml('xl/sharedStrings.xml'),'si').map(si=>nodes(si,'t').map(t=>t.textContent).join('')) : [];
  const rows = nodes(await xml(path),'row');
  if (rows.length > 5001) fail('Лимит одного отчёта — 5000 строк.');
  return rows.map(row => {
    const result = [];
    for (const cell of nodes(row,'c')) {
      const letters = /^[A-Z]+/.exec(cell.getAttribute('r') || '')?.[0];
      if (!letters) fail('Некорректный адрес ячейки.');
      const index = [...letters].reduce((n,c)=>n*26+c.charCodeAt(0)-64,0)-1;
      if(index >= 100) fail('Лимит отчёта — 100 столбцов.');
      if(nodes(cell,'f').length) fail('Перед загрузкой замените формулы значениями.');
      const value = nodes(cell,'v')[0]?.textContent || '';
      const type = cell.getAttribute('t');
      result[index] = type==='s' ? strings[Number(value)] : type==='inlineStr' ? nodes(cell,'t').map(t=>t.textContent).join('') : value;
    }
    return Array.from(result,v=>v??'');
  });
};
