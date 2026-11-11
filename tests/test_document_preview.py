import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('document_preview', Path(__file__).parents[1] / 'tools/document_preview.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PreviewTests(unittest.TestCase):
    def test_real_excel_fixture(self):
        path = Path(__file__).parents[3] / 'outputs/test-bot-shipments.xlsx'
        result = module.summarize(path, path.name)
        self.assertEqual(result['row_count'], 2)
        self.assertIn('Единиц товара — 5.', result['summary'])
        self.assertIn('К оплате, ₽ — 1400.', result['summary'])

    def test_csv_and_invalid_total(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.csv'
            path.write_text('Артикул;Количество;К оплате ₽\nA;2;10,50\nB;3;нет\n', encoding='utf-8-sig')
            result = module.summarize(path, path.name)
            self.assertEqual(result['row_count'], 2)
            self.assertIn('Единиц товара — 5.', result['summary'])
            self.assertNotIn('К оплате, ₽ —', result['summary'])
            self.assertTrue(result['warnings'])

    def test_dtd_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.xlsx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('xl/workbook.xml', '<!DOCTYPE test><workbook/>')
            self.assertIn('DTD', module.summarize(path, path.name)['summary'])

    def test_formula_not_counted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.xlsx'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Data" r:id="r1"/></sheets></workbook>')
                archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
                archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1" t="inlineStr"><is><t>Количество</t></is></c><c r="B1" t="inlineStr"><is><t>Товар</t></is></c></row><row><c r="A2"><f>1+1</f><v>2</v></c><c r="B2" t="inlineStr"><is><t>A</t></is></c></row></sheetData></worksheet>')
            result = module.summarize(path, path.name)
            self.assertEqual(result['rows'][0][0], '')
            self.assertNotIn('Единиц товара —', result['summary'])


if __name__ == '__main__':
    unittest.main()
