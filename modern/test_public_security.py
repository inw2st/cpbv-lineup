import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from catalog_store import CatalogStore
from core import sheet_awakening_potential
from service import legacy_integrity

class SecurityTests(unittest.TestCase):
    def test_catalog_rejects_traversal_and_code_members(self):
        for path in ('../cards.json','/cards.json','skills\\icons\\a.png','private.py','skills/icons/../cards.json'):
            with self.subTest(path=path),self.assertRaises(ValueError):CatalogStore._safe_path(path)
    def test_missing_awakening_exports_as_blank(self):
        for value in ('-',None,'','0'):self.assertIsNone(sheet_awakening_potential(value))
    def test_included_engine_snapshot(self):self.assertEqual(legacy_integrity(),[])

if __name__=='__main__':unittest.main()
