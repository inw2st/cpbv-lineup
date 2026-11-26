"""Live version evidence and matching for the new app; legacy modules stay intact."""
import copy
import csv
import json
from pathlib import Path
from PIL import Image
import numpy as np
from core import CardDatabase as LegacyDatabase, STAT_KEYS
from ldplayer_scanner import LDScanner as LegacyScanner, export_csv as legacy_export_csv

VERSIONS = (1, 2, 3)
BADGE_ROI = (.42, .333, .70, .371)


def version_value(value):
    if type(value) is int and value in VERSIONS:
        return value
    if isinstance(value, str) and value.strip() in ('1', '2', '3'):
        return int(value)
    return None


def card_version(card):
    return version_value(card.get('live_version')) if card.get('kind') == 0 else None


def read_live_badge(scanner, image, directory):
    directory = Path(directory)
    bounds = tuple(round(v * (image.width if i % 2 == 0 else image.height))
                   for i, v in enumerate(BADGE_ROI))
    crop = image.crop(bounds)
    directory.mkdir(parents=True, exist_ok=True)
    crop.save(directory / 'live-badge.png')
    result = match_live_badge(image)
    result['bounds'] = list(bounds)
    (directory / 'live-version-evidence.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    return result


def match_live_badge(image):
    """Compare the V glyphs and badge colors, excluding variable year digits."""
    image = image.convert('RGB')
    normalized = image.resize((556, round(image.height * 556 / image.width)), Image.Resampling.LANCZOS)
    bounds = tuple(round(v * (normalized.width if i % 2 == 0 else normalized.height))
                   for i, v in enumerate(BADGE_ROI))
    area = np.asarray(normalized.crop(bounds), dtype=np.float32)
    bank = Path(__file__).resolve().parent / 'resources/live-badges'
    scores = {}
    for group in ('live', 'year'):
        for version in VERSIONS:
            with Image.open(bank / f'{group}-{version}.png') as source:
                # Year is drawn over the left half; compare only the V and digit.
                sprite = source.convert('RGBA').crop((77, 3, 126, 44))
                for scale in (.50, .53, .56, .59, .62, .65):
                    size = (round(sprite.width * scale), round(sprite.height * scale))
                    template = sprite.resize(size, Image.Resampling.LANCZOS)
                    rgba = np.asarray(template, dtype=np.float32)
                    mask = rgba[:, :, 3] > 220
                    h, w = mask.shape
                    if h > area.shape[0] or w > area.shape[1]:
                        continue
                    patches = np.lib.stride_tricks.sliding_window_view(area, (h, w), axis=(0, 1))
                    patches = patches.transpose(0, 1, 3, 4, 2)
                    errors = ((patches - rgba[:, :, :3]) ** 2 * mask[:, :, None]).sum(axis=(2, 3, 4))
                    rmse = np.sqrt(errors / (mask.sum() * 3))
                    y, x = np.unravel_index(np.argmin(rmse), rmse.shape)
                    score = 1 - float(rmse[y, x]) / 255
                    candidate = {'version': version, 'group': group, 'score': round(score, 5),
                                 'scale': scale, 'location': [int(x), int(y)]}
                    if score > scores.get(version, {}).get('score', -1):
                        scores[version] = candidate
    candidates = sorted(scores.values(), key=lambda x: x['score'], reverse=True)
    best = candidates[0]
    margin = best['score'] - candidates[1]['score']
    detected = best['score'] >= .86 and margin >= .025
    return {'status': 'recognized' if detected else 'unreadable',
            'version': best['version'] if detected else None, 'source': 'original_badge_templates',
            'score': best['score'], 'margin': round(margin, 5), 'candidates': candidates}


class CardDatabase(LegacyDatabase):
    def __init__(self, path):
        super().__init__(path)
        self.current_live_version = None

    def entry(self, card, base=None):
        result = super().entry(card, base)
        result.update(live_year=card.get('live_year'), live_version=card_version(card))
        if result['live_version']:
            result['kind_label'] = f'라이브 V{result["live_version"]}'
        return result

    def catalog(self, *args, live_version=None, **kwargs):
        items = super().catalog(*args, **kwargs)
        version = version_value(live_version)
        return [c for c in items if c['live_version'] == version] if version else items

    def match(self, table, observed_text='', live_version=None):
        version = version_value(live_version) or self.current_live_version
        result = super().match(table, observed_text)
        base = table.get('기본', {})
        if version:
            names = self.visible_names(observed_text)
            exact = [c for c in self.cards if c.get('player') in names and
                     card_version(c) == version and
                     all(type(base.get(k)) is int and c.get('stats', {}).get(v) == base[k]
                         for k, v in STAT_KEYS.items())]
            result = {'status': 'verified' if len(exact) == 1 else 'ambiguous' if exact else 'mismatch',
                      'candidates': [self.entry(c, base) for c in exact],
                      'message': f'선수명 + 기본 6개 + 라이브 V{version} 일치' if len(exact) == 1 else
                                 f'라이브 V{version} 후보가 여러 개입니다. 직접 선택하세요.' if exact else
                                 f'화면의 라이브 V{version}와 일치하는 카드가 없습니다. 데이터와 카드를 확인하세요.'}
            if len(exact) == 1:
                result['card'] = self.entry(exact[0], base)
        else:
            # Without a badge observation, matching identical stats cannot confirm
            # a live version, even when just one version exists in this catalog.
            if result.get('card', {}).get('kind') == 0:
                result.pop('card', None)
                result.update(status='ambiguous', message='라이브 버전 미인식: V1·V2·V3를 직접 확인하고 카드를 선택하세요.')
        if result.get('card'):
            result['card'] = self.entry(self.by_id[result['card']['id']], base)
        result['candidates'] = [self.entry(self.by_id[c['id']], base) for c in result.get('candidates', [])]
        result['observed_live_version'] = version
        return result


class LDScanner(LegacyScanner):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = CardDatabase(self.db.path)
        self._live_badges = {}

    def ocr(self, image, directory, label, language='ko-KR'):
        text = super().ocr(image, directory, label, language)
        if label == 'identity':
            try:
                evidence = read_live_badge(self, image, directory)
            except (OSError, RuntimeError, ValueError) as error:
                evidence = {'status': 'unreadable', 'version': None, 'source': 'original_badge_templates', 'error': str(error)}
            self._live_badges[str(Path(directory).resolve())] = evidence
            self.db.current_live_version = version_value(evidence.get('version'))
        return text

    def save(self, directory, status, error=None):
        for record in self.records:
            overview = record.get('overview', {})
            source = overview.get('source_image')
            if source:
                evidence = self._live_badges.get(str(Path(source).parent.resolve()))
                if evidence:
                    overview['live_version_evidence'] = copy.deepcopy(evidence)
        super().save(directory, status, error)
        export_csv(self.records, Path(directory) / 'all_stats.csv')


def export_csv(records, path):
    legacy_export_csv(records, path)
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        fields = list(reader.fieldnames)
        rows = list(reader)
    fields.insert(fields.index('카드종류') + 1, '라이브버전')
    versions = {r['slot']: card_version(r.get('match', {}).get('card', {})) for r in records}
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            version = versions.get(row['배치'])
            row['라이브버전'] = f'V{version}' if version else ''
            writer.writerow(row)
