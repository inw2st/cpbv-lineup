import copy
import csv
import json
import tempfile
import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import STAT_KEYS
from live_cards import CardDatabase, LDScanner, card_version, match_live_badge, export_csv

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = Path(os.environ.get('LINEUP_TEST_CAPTURES', str(ROOT/'tests/private-captures')))
REAL_V3 = CAPTURES / 'ldplayer-20261125-164534-846415/02-C/detail.png'
NONLIVE = CAPTURES / 'ldplayer-20261126-000027-990157/01-DH/detail.png'


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'cards.json'
        self.cards = [{'id': version, 'name': "테스트'26", 'player': '테스트', 'role': '타자',
                       'season': 2026, 'kind': 0, 'grade': 4, 'live_year': 1, 'live_version': version,
                       'stats': {key: 70 for key in STAT_KEYS.values()}} for version in (1, 2, 3)]
        self.path.write_text(json.dumps(self.cards), encoding='utf8')
        self.db = CardDatabase(self.path)
        self.table = {'기본': {key: 70 for key in STAT_KEYS}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_name_same_stats_require_badge_and_select_exact_version(self):
        self.assertEqual(self.db.match(self.table, '테스트')['status'], 'ambiguous')
        for version in (1, 2, 3):
            result = self.db.match(self.table, '테스트', live_version=version)
            self.assertEqual(result['status'], 'verified')
            self.assertEqual(result['card']['id'], version)
            self.assertEqual(result['card']['live_version'], version)

    def test_unknown_live_version_is_never_automatic_even_one_db_candidate(self):
        self.db.cards = self.db.cards[:1]
        result = self.db.match(self.table, '테스트')
        self.assertEqual(result['status'], 'ambiguous')
        self.assertNotIn('card', result)

    def test_badge_never_overrides_missing_name_or_mismatched_stats(self):
        self.assertNotIn('card', self.db.match(self.table, '', live_version=2))
        self.table['기본']['파워'] = 90
        self.assertNotIn('card', self.db.match(self.table, '테스트', live_version=2))

    def test_missing_version_in_catalog_does_not_fall_back_to_other_version(self):
        self.db.cards = self.db.cards[:1]
        result = self.db.match(self.table, '테스트', live_version=3)
        self.assertEqual(result['status'], 'mismatch')
        self.assertNotIn('card', result)

    def test_catalog_and_manual_choice_keep_version(self):
        self.assertEqual([c['id'] for c in self.db.catalog(live_version=2)], [2])
        card = self.db.choose_id(self.table, 3)['card']
        self.assertEqual(card['live_version'], 3)
        self.assertEqual(card['kind_label'], '라이브 V3')

    def test_other_card_types_do_not_become_live(self):
        self.db.cards[0]['kind'] = 4
        self.assertIsNone(card_version(self.db.cards[0]))
        self.db.cards = self.db.cards[:1]
        result = self.db.match(self.table, '테스트')
        self.assertEqual(result['status'], 'verified')
        self.assertIsNone(result['card']['live_version'])

    def test_full_stats_csv_preserves_selected_version(self):
        path = Path(self.tmp.name) / 'stats.csv'
        record = {'slot': 'DH', 'match': {'card': self.db.entry(self.cards[1])},
                  'stats': {'table': self.table}, 'issues': []}
        export_csv([record], path)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['라이브버전'], 'V2')


class ImageTests(unittest.TestCase):
    @unittest.skipUnless(REAL_V3.is_file(), 'Local screenshot fixture unavailable')
    def test_saved_real_v3_at_multiple_capture_sizes(self):
        with Image.open(REAL_V3) as source:
            for width in (400, 556, 1080):
                image = source.resize((width, round(source.height * width / source.width)), Image.Resampling.LANCZOS)
                self.assertEqual(match_live_badge(image)['version'], 3)

    def test_all_original_live_and_year_badges_composited_over_portrait(self):
        with Image.new('RGB', (556,989), 'black') as source:
            for group in ('live', 'year'):
                for version in (1, 2, 3):
                    image = source.convert('RGB')
                    with Image.open(ROOT / f'modern/resources/live-badges/{group}-{version}.png') as sprite:
                        sprite = sprite.resize((97, 30), Image.Resampling.LANCZOS)
                        image.paste(sprite, (286, 338), sprite)
                    self.assertEqual(match_live_badge(image)['version'], version)

    @unittest.skipUnless(NONLIVE.is_file(), 'Local screenshot fixture unavailable')
    def test_all_nine_nonlive_captures_are_rejected(self):
        for path in NONLIVE.parent.parent.glob('*/detail.png'):
            with self.subTest(path=path.parent.name), Image.open(path) as image:
                self.assertIsNone(match_live_badge(image)['version'])

    def test_empty_or_uniform_image_is_not_a_version(self):
        for color in ('black', 'white', '#bbbbbb'):
            self.assertIsNone(match_live_badge(Image.new('RGB', (556, 989), color))['version'])

    def test_scan_hook_clears_previous_card_version_when_badge_unreadable(self):
        scanner = object.__new__(LDScanner)
        scanner.db = type('DB', (), {'current_live_version': 3})()
        scanner._live_badges = {}
        with tempfile.TemporaryDirectory() as directory:
            with patch('ldplayer_scanner.LDScanner.ocr', return_value='선수'), \
                 patch('live_cards.read_live_badge', return_value={'status': 'unreadable', 'version': None}):
                scanner.ocr(Image.new('RGB', (556, 989)), Path(directory), 'identity')
        self.assertIsNone(scanner.db.current_live_version)


if __name__ == '__main__':
    unittest.main()
