"""Offline integration: optional guidance must not make daily updates brittle."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import update_news
from test_update_news import valid_news

class HardwarePolicyTests(unittest.TestCase):
    def test_hardware_prose_does_not_fail_existing_valid_schema(self):
        # The browser suppresses these claims instead of failing daily updates.
        for claim in ['VRAM24GBで動作','30 t/s','単一GPUで動作可能','CPUだけで動作可能','Mac miniで快適']:
            data=valid_news();data['ranking_general'][0]['reason']=claim
            self.assertEqual(update_news.validate_news(data),data)
    def test_current_snapshot_remains_valid(self):
        data=json.loads((Path(__file__).parent.parent/'news.json').read_text())
        self.assertEqual(update_news.validate_news(data),data)
    def test_generator_does_not_own_catalog(self):
        catalog=Path(__file__).parent.parent/'hardware-guidance.json';before=catalog.read_bytes()
        with tempfile.TemporaryDirectory() as folder,patch.object(update_news,'NEWS_JSON',str(Path(folder)/'news.json')):
            update_news.save_news(valid_news())
        self.assertEqual(catalog.read_bytes(),before)
if __name__=='__main__':unittest.main()
