"""Bounded Pinterest collection, review and reference handoff."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from urllib.parse import quote, urljoin, urlsplit
import uuid

from PIL import Image, ImageDraw, ImageOps, ImageStat
import requests

HERE = Path(__file__).resolve().parent
MAX_BYTES = 20 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_plan(plan):
    for field in ('product', 'style', 'market'):
        if not isinstance(plan.get(field), str) or not plan[field].strip():
            raise ValueError('Missing text field: ' + field)
    themes = plan.get('themes')
    if not isinstance(themes, list) or not themes or not all(isinstance(t, str) and t.strip() for t in themes):
        raise ValueError('themes must contain nonempty strings')
    queries = plan.get('queries')
    if not isinstance(queries, list) or not 1 <= len(queries) <= 10:
        raise ValueError('Provide 1-10 queries')
    if not all(isinstance(q, str) and 1 <= len(q.strip()) <= 220 and not q.startswith('-') for q in queries):
        raise ValueError('Invalid query')
    if len(set(queries)) != len(queries):
        raise ValueError('Duplicate queries')
    plan.setdefault('limit', 30)
    plan.setdefault('min_short_edge', 600)
    if type(plan['limit']) is not int or not 1 <= plan['limit'] <= 300:
        raise ValueError('limit must be an integer in 1..300')
    if type(plan['min_short_edge']) is not int or not 256 <= plan['min_short_edge'] <= 4096:
        raise ValueError('min_short_edge must be in 256..4096')
    return plan


def error_kind(message):
    value = str(message).lower()
    if '429' in value or 'rate limit' in value:
        return 'rate_limited'
    if any(s in value for s in ('login', '401', '403', 'captcha', 'authentication')):
        return 'login_or_access_required'
    if any(s in value for s in ('timeout', 'timed out', 'connection', 'proxy', 'ssl', 'resolve')):
        return 'network_error'
    return 'provider_or_format_error'


class CollectionError(Exception):
    def __init__(self, kind):
        self.kind = kind
        super().__init__(kind)


def valid_image_url(url):
    p = urlsplit(str(url))
    return p.scheme == 'https' and p.hostname == 'i.pinimg.com' and p.port in (None, 443) and not p.username


def normalize(raw):
    image_url = raw.get('src') or raw.get('image_url')
    if not valid_image_url(image_url):
        raise ValueError('Untrusted or unsupported image host')
    source = raw.get('origin') or raw.get('pin_url') or ''
    pin_id = str(raw.get('id', ''))
    pin_pattern = r'(?:\d+|e1_[A-Za-z0-9_-]{1,160})'
    if re.fullmatch(pin_pattern, pin_id):
        source = 'https://www.pinterest.com/pin/' + pin_id + '/'
    match = re.fullmatch(r'https://(?:www\.)?pinterest\.com/pin/(' + pin_pattern + r')/?', source)
    if not match:
        raise ValueError('Missing Pinterest source identity')
    return {'pin_id': match[1], 'source_url': source, 'image_url': image_url,
            'caption': str(raw.get('alt') or raw.get('title') or '')[:3000],
            'source_published_at': None, 'metrics': None,
            'rights': 'reference_only_unverified', 'market_evidence': 'not_verified'}


def search(query, count, engine, cookies, working):
    if engine == 'pinterest-dl':
        command = [sys.executable, '-m', 'pinterest_dl.cli', 'search', query, '-n', str(count), '--json', '--timeout', '15', '--delay', '1']
        if cookies:
            command += ['-c', str(Path(cookies).resolve())]
    else:
        command = [sys.executable, '-m', 'gallery_dl', '--ignore-config', '--dump-json',
                   '--range', '1-' + str(count), '--retries', '0', '--http-timeout', '15']
        if cookies:
            command += ['--cookies', str(Path(cookies).resolve())]
        command += ['https://www.pinterest.com/search/pins/?q=' + quote(query)]
    try:
        result = subprocess.run(command, cwd=working, capture_output=True, encoding='utf-8',
                                errors='replace', timeout=55,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        raise CollectionError('network_error') from None
    except FileNotFoundError:
        raise CollectionError('engine_not_installed') from None
    if result.returncode:
        raise CollectionError(error_kind(result.stderr + result.stdout))
    try:
        data = json.loads(result.stdout)
        if engine == 'pinterest-dl':
            return [item for row in data['results'] for item in row['items']][:count]
        return [{'id': row[2].get('id'), 'src': row[1], 'alt': row[2].get('description', '')}
                for row in data if isinstance(row, list) and len(row) >= 3 and row[0] == 3][:count]
    except (ValueError, TypeError, KeyError, IndexError):
        raise CollectionError('provider_or_format_error') from None


def download(url):
    started = time.monotonic()
    for _ in range(4):
        if not valid_image_url(url):
            raise ValueError('Invalid image redirect')
        with requests.get(url, timeout=(8, 20), stream=True, allow_redirects=False) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers['Location'])
                continue
            response.raise_for_status()
            if not response.headers.get('Content-Type', '').lower().startswith('image/'):
                raise ValueError('Response is not an image')
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > MAX_BYTES or time.monotonic() - started > 50:
                    raise ValueError('Image size or time budget exceeded')
            return bytes(data)
    raise ValueError('Too many redirects')


def image_info(data):
    with Image.open(io.BytesIO(data)) as image:
        image.verify()
    with Image.open(io.BytesIO(data)) as image:
        if image.format not in ('JPEG', 'PNG', 'WEBP') or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Only static JPEG/PNG/WebP supported')
        ext = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[image.format]
        rgb = ImageOps.exif_transpose(image).convert('RGB')
        w, h = rgb.size
        sample = rgb.convert('L').resize((17, 8), Image.Resampling.LANCZOS)
        pixels = list(sample.getdata())
        bits = ''.join('1' if pixels[y * 17 + x] > pixels[y * 17 + x + 1] else '0'
                       for y in range(8) for x in range(16))
        return {'sha256': digest(data), 'width': w, 'height': h, 'extension': ext,
                'dhash': f'{int(bits, 2):032x}',
                'mean_rgb': [round(v, 1) for v in ImageStat.Stat(rgb.resize((32, 32))).mean]}


def near(a, b):
    return ((int(a['dhash'], 16) ^ int(b['dhash'], 16)).bit_count() <= 3
            and abs(a['width'] / a['height'] - b['width'] / b['height']) < .05
            and max(abs(x - y) for x, y in zip(a['mean_rgb'], b['mean_rgb'])) < 15)


def cache_connection(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'images').mkdir(exist_ok=True)
    conn = sqlite3.connect(root / 'catalog.sqlite3', timeout=20)
    conn.execute('CREATE TABLE IF NOT EXISTS assets (sha TEXT PRIMARY KEY, file TEXT NOT NULL, info TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS sources (url TEXT PRIMARY KEY, sha TEXT, pin TEXT, retrieved_at TEXT)')
    return conn


def cached_image(conn, library, row):
    cached = conn.execute('SELECT a.file,a.info,s.retrieved_at FROM sources s JOIN assets a ON a.sha=s.sha WHERE s.url=?',
                          (row['image_url'],)).fetchone()
    if cached:
        file = library / cached[0]
        if file.is_file() and digest(file.read_bytes()) == json.loads(cached[1])['sha256']:
            return file, json.loads(cached[1]), cached[2], True
    data = download(row['image_url'])
    info = image_info(data)
    relative = 'images/' + info['sha256'] + info['extension']
    target = library / relative
    if not target.exists() or digest(target.read_bytes()) != info['sha256']:
        temp = target.with_suffix(target.suffix + '.part')
        temp.write_bytes(data)
        temp.replace(target)
    stamp = now()
    with conn:
        conn.execute('INSERT OR REPLACE INTO assets VALUES (?,?,?)', (info['sha256'], relative, json.dumps(info)))
        conn.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?)', (row['image_url'], info['sha256'], row['source_url'], stamp))
    return target, info, stamp, False


def candidates(manifest):
    return [r for r in manifest['items'] if r.get('technical_status') == 'passed']


def export(output, manifest):
    manifest['counts'] = dict(Counter(r['technical_status'] for r in manifest['items']))
    manifest['review_counts'] = dict(Counter(r.get('review', {}).get('decision', 'pending') for r in candidates(manifest)))
    manifest['updated_at'] = now()
    write(output / 'manifest.json', manifest)
    fields = ('id', 'pin_id', 'source_url', 'image_url', 'query', 'file', 'width', 'height', 'sha256',
              'retrieved_at', 'source_published_at', 'metrics', 'technical_status', 'near_duplicate_of',
              'decision', 'elements', 'palette', 'composition', 'reason', 'concerns')
    with (output / 'materials.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in manifest['items']:
            flat = {**row, **row.get('review', {})}
            safe = {}
            for key in fields:
                v = flat.get(key, '')
                if isinstance(v, (dict, list)):
                    v = json.dumps(v, ensure_ascii=False)
                if isinstance(v, str) and v.startswith(('=', '+', '-', '@')):
                    v = "'" + v
                safe[key] = v
            writer.writerow(safe)
    template = (HERE.parent / 'assets/preview.html').read_text(encoding='utf-8')
    data = json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    (output / 'index.html').write_text(template.replace('__MANIFEST_JSON__', data), encoding='utf-8')
    valid = candidates(manifest)
    for start in range(0, len(valid), 12):
        page = valid[start:start + 12]
        canvas = Image.new('RGB', (1200, math.ceil(len(page) / 4) * 330), 'white')
        draw = ImageDraw.Draw(canvas)
        for i, row in enumerate(page):
            with Image.open(output / row['file']) as image:
                thumb = ImageOps.contain(ImageOps.exif_transpose(image).convert('RGB'), (284, 282))
            x, y = (i % 4) * 300, (i // 4) * 330
            canvas.paste(thumb, (x + (300 - thumb.width) // 2, y))
            number = manifest['items'].index(row) + 1
            draw.text((x + 8, y + 288), f"#{number:02d} - {row.get('review', {}).get('decision', 'pending')}", fill='black')
            draw.text((x + 8, y + 308), f"{row['width']} x {row['height']}", fill='black')
        canvas.save(output / f'overview-{start // 12 + 1:02d}.jpg', quality=91)


def collect(args):
    plan = validate_plan(read(args.plan))
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'manifest.json'
    if path.exists():
        manifest = read(path)
        if not args.resume or manifest['plan'] != plan or manifest['engine'] != args.engine:
            raise ValueError('Existing batch requires --resume with identical plan and engine')
        manifest.setdefault('attempt_history', []).append({
            'at': now(), 'errors': manifest['errors'],
            'failed_images': [r for r in manifest['items'] if r['technical_status'] == 'download_failed']})
        manifest['items'] = [r for r in manifest['items'] if r['technical_status'] != 'download_failed']
    else:
        if any(output.iterdir()):
            raise ValueError('Use an empty output directory')
        manifest = {'schema_version': 1, 'batch_id': uuid.uuid4().hex, 'plan': plan,
                    'engine': args.engine, 'created_at': now(), 'status': 'collecting', 'items': [],
                    'queries': {}, 'errors': []}
    library = Path(args.library).expanduser().resolve()
    conn = cache_connection(library)
    manifest['library'] = str(library)
    (output / 'images').mkdir(exist_ok=True)
    working = output / 'provider-work'
    working.mkdir(exist_ok=True)
    seen = {r['pin_id'] for r in manifest['items'] if 'pin_id' in r}
    manifest['errors'] = []
    failures = 0
    try:
        for qi, query in enumerate(plan['queries']):
            count = min(math.ceil(plan['limit'] / len(plan['queries'])), plan['limit'] - len(manifest['items']))
            if count <= 0:
                break
            cache = manifest['queries'].get(query)
            if cache and cache['status'] == 'ok':
                raw_items = cache['items']
            else:
                print(json.dumps({'stage': 'search', 'query': query, 'maximum': count}), flush=True)
                try:
                    raw_items = search(query, count, args.engine, args.cookies, working)
                    manifest['queries'][query] = {'status': 'ok', 'retrieved_at': now(), 'items': raw_items}
                except CollectionError as exc:
                    manifest['queries'][query] = {'status': 'error', 'kind': exc.kind, 'at': now()}
                    manifest['errors'].append({'query': query, 'kind': exc.kind})
                    break
                export(output, manifest)
            for raw in raw_items:
                if len(manifest['items']) >= plan['limit']:
                    break
                try:
                    row = normalize(raw)
                except (ValueError, TypeError):
                    manifest['errors'].append({'query': query, 'kind': 'invalid_source_record'})
                    continue
                if row['pin_id'] in seen:
                    continue
                seen.add(row['pin_id'])
                row.update(id=f"pin-{row['pin_id']}", query=query, found_at=now(), technical_status='pending')
                try:
                    file, info, stamp, cache_hit = cached_image(conn, library, row)
                    row.update(info, retrieved_at=stamp, cache_hit=cache_hit)
                    duplicate = next((r for r in manifest['items'] if r.get('sha256') == info['sha256']), None)
                    if min(info['width'], info['height']) < plan['min_short_edge']:
                        row['technical_status'] = 'low_resolution'
                    elif duplicate:
                        row.update(technical_status='exact_duplicate', duplicate_of=duplicate['id'])
                    else:
                        row['technical_status'] = 'passed'
                        row['file'] = 'images/' + row['id'] + info['extension']
                        shutil.copy2(file, output / row['file'])
                        row['near_duplicate_of'] = [r['id'] for r in candidates(manifest) if near(row, r)]
                    failures = 0
                except (OSError, ValueError, requests.RequestException, Image.DecompressionBombError) as exc:
                    row.update(technical_status='download_failed', error=error_kind(str(exc)))
                    failures += 1
                manifest['items'].append(row)
                export(output, manifest)
                print(json.dumps({'stage': 'image', 'id': row['id'], 'status': row['technical_status']}), flush=True)
                if failures >= 3 or row.get('error') in ('rate_limited', 'login_or_access_required'):
                    manifest['errors'].append({'kind': row['error'], 'stage': 'image_download'})
                    break
            if failures >= 3 or (manifest['errors'] and manifest['errors'][-1].get('stage') == 'image_download'):
                break
    finally:
        conn.close()
        valid = candidates(manifest)
        had_download_errors = any(r['technical_status'] == 'download_failed' for r in manifest['items'])
        manifest['status'] = ('needs_review' if valid else
                              'collection_failed' if manifest['errors'] or had_download_errors else 'no_eligible_images')
        if valid and all('review' in r for r in valid):
            manifest['status'] = 'reviewed'
        export(output, manifest)
    print(json.dumps({'status': manifest['status'], 'counts': manifest['counts'],
                      'errors': manifest['errors'], 'preview': str(output / 'index.html')}, ensure_ascii=False))
    return 0 if valid else 2


def local_image(output, row):
    path = (output / row['file']).resolve()
    if not path.is_relative_to(output.resolve()) or digest(path.read_bytes()) != row['sha256']:
        raise ValueError('Changed or invalid local image: ' + row['id'])
    return path


def apply_reviews(output, payload):
    manifest = read(output / 'manifest.json')
    if payload.get('batch_id') != manifest['batch_id']:
        raise ValueError('Review belongs to another batch')
    valid = {r['id']: r for r in candidates(manifest)}
    reviews = payload.get('items', [])
    if not valid or len(reviews) != len(valid) or {r.get('id') for r in reviews} != set(valid):
        raise ValueError('Review must cover every eligible image exactly once')
    for review in reviews:
        row = valid[review['id']]
        local_image(output, row)
        if review.get('sha256') != row['sha256'] or review.get('decision') not in ('keep', 'reject'):
            raise ValueError('Invalid hash or review decision')
        for key in ('palette', 'composition', 'reason'):
            if not isinstance(review.get(key), str) or not review[key].strip():
                raise ValueError('Missing review field: ' + key)
        for key in ('elements', 'concerns'):
            if not isinstance(review.get(key), list) or not all(isinstance(x, str) for x in review[key]):
                raise ValueError('Invalid review list: ' + key)
        if not review['elements']:
            raise ValueError('Describe observed elements')
    for review in reviews:
        valid[review['id']]['review'] = {k: review[k] for k in
            ('decision', 'elements', 'palette', 'composition', 'reason', 'concerns')}
        valid[review['id']]['review']['reviewed_at'] = now()
    manifest['status'] = 'reviewed'
    write(output / 'reviews.json', payload)
    export(output, manifest)
    return manifest


def handoff(output, selection):
    manifest = read(output / 'manifest.json')
    ids = selection.get('ids', [])
    if selection.get('batch_id') != manifest['batch_id'] or not ids or len(ids) != len(set(ids)):
        raise ValueError('Invalid selection batch or empty/duplicate IDs')
    valid = {r['id']: r for r in candidates(manifest) if r.get('review', {}).get('decision') == 'keep'}
    if any(i not in valid for i in ids):
        raise ValueError('Select only reviewed keep images')
    files = [local_image(output, valid[i]) for i in ids]
    dest = output / 'selected-references'
    index = 1
    while dest.exists():
        index += 1
        dest = output / f'selected-references-{index}'
    dest.mkdir()
    for file in files:
        shutil.copy2(file, dest / file.name)
    payload = {'batch_id': manifest['batch_id'], 'product': manifest['plan']['product'],
               'themes': manifest['plan']['themes'], 'style': manifest['plan']['style'],
               'market': manifest['plan']['market'], 'references': str(dest),
               'selected': [valid[i] for i in ids], 'target_skill': 'product-reference-images',
               'generation_started': False}
    write(dest.parent / (dest.name + '-handoff.json'), payload)
    write(output / 'generation-handoff.json', payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect')
    c.add_argument('--plan', required=True)
    c.add_argument('--output', required=True)
    c.add_argument('--library', default=str(Path.home() / 'Pictures/ProductInspiration'))
    c.add_argument('--engine', choices=('pinterest-dl', 'gallery-dl'), default='pinterest-dl')
    c.add_argument('--cookies')
    c.add_argument('--proxy', help='Explicit process-only HTTP proxy; never changes system settings')
    c.add_argument('--resume', action='store_true')
    r = sub.add_parser('review')
    r.add_argument('--output', required=True)
    r.add_argument('--reviews', required=True)
    h = sub.add_parser('handoff')
    h.add_argument('--output', required=True)
    h.add_argument('--selection', required=True)
    sub.add_parser('doctor')
    args = parser.parse_args()
    try:
        if args.command == 'doctor':
            from importlib.metadata import version
            versions = {name: version(name) for name in ('pinterest-dl', 'gallery-dl', 'Pillow', 'requests')}
            result = {'python': sys.version.split()[0], 'executable': sys.executable,
                      'packages': versions, 'checked_at': now(), 'network_verified': False}
            runtime = Path(sys.prefix).parent
            write(runtime / 'installed-versions.json', result)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == 'collect':
            if args.proxy:
                p = urlsplit(args.proxy)
                if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
                    raise ValueError('Use an HTTP(S) proxy URL without embedded credentials')
                os.environ['HTTPS_PROXY'] = args.proxy
                os.environ['HTTP_PROXY'] = args.proxy
            return collect(args)
        output = Path(args.output).expanduser().resolve()
        if args.command == 'review':
            result = apply_reviews(output, read(args.reviews))
            print(json.dumps({'status': result['status'], 'reviews': result['review_counts']}, ensure_ascii=False))
        else:
            result = handoff(output, read(args.selection))
            print(json.dumps({'references': result['references'], 'generation_started': False}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': type(exc).__name__, 'message': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
