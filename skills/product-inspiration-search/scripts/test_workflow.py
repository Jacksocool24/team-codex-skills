"""Offline behavioral checks; no Pinterest calls or image-generation charges."""
import argparse
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw
import workflow as w


def png(size=(800, 1000), variant=0):
    image = Image.new('RGB', size, (220, 220, 220))
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 30, size[0] // 2, size[1] // 2), fill=(variant, 45, 80))
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def raw(i):
    return {'id': i, 'src': f'https://i.pinimg.com/originals/{i}.png', 'alt': 'test fixture'}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / 'batch'
        self.plan = {'product': 'test blanket', 'themes': ['test'], 'style': 'test artwork',
                     'market': 'US', 'limit': 4, 'min_short_edge': 600, 'queries': ['test query']}
        w.write(self.root / 'plan.json', self.plan)
        self.args = argparse.Namespace(plan=str(self.root / 'plan.json'), output=str(self.out),
            library=str(self.root / 'library'), engine='pinterest-dl', cookies=None, resume=False)

    def collect(self):
        data = {1: png(), 2: png(), 3: png((100, 100)), 4: png(variant=150)}
        with patch.object(w, 'search', return_value=[raw(i) for i in data]), patch.object(
                w, 'download', side_effect=lambda url: data[int(Path(url).stem)]):
            w.collect(self.args)
        return w.read(self.out / 'manifest.json')

    def reviews(self, manifest):
        return {'batch_id': manifest['batch_id'], 'items': [
            {'id': r['id'], 'sha256': r['sha256'], 'decision': 'keep', 'elements': ['offline rectangle'],
             'palette': 'gray', 'composition': 'test shape', 'reason': 'offline fixture only', 'concerns': []}
            for r in w.candidates(manifest)]}

    def test_dedup_low_resolution_resume_cache(self):
        m = self.collect()
        self.assertEqual(m['counts'], {'passed': 2, 'exact_duplicate': 1, 'low_resolution': 1})
        self.assertEqual(m['status'], 'needs_review')
        self.args.resume = True
        with patch.object(w, 'search', side_effect=AssertionError('must reuse search')), patch.object(
                w, 'download', side_effect=AssertionError('must reuse image')):
            w.collect(self.args)
        self.args.output = str(self.root / 'second-batch')
        self.args.resume = False
        with patch.object(w, 'search', return_value=[raw(i) for i in range(1, 5)]), patch.object(
                w, 'download', side_effect=AssertionError('must reuse cross-batch cache')):
            w.collect(self.args)
        self.assertTrue(all(r['cache_hit'] for r in w.read(Path(self.args.output) / 'manifest.json')['items']))

    def test_review_binding_and_handoff(self):
        m = self.collect()
        selection = {'batch_id': m['batch_id'], 'ids': [w.candidates(m)[0]['id']]}
        with self.assertRaises(ValueError):
            w.handoff(self.out, selection)
        reviews = self.reviews(m)
        reviews['items'][0]['sha256'] = 'incorrect'
        with self.assertRaises(ValueError):
            w.apply_reviews(self.out, reviews)
        reviews = self.reviews(m)
        w.apply_reviews(self.out, reviews)
        result = w.handoff(self.out, selection)
        self.assertFalse(result['generation_started'])
        self.assertEqual(len(list(Path(result['references']).iterdir())), 1)
        duplicate = w.handoff(self.out, selection)
        self.assertNotEqual(result['references'], duplicate['references'])
        (self.out / w.candidates(m)[0]['file']).write_bytes(png(variant=200))
        with self.assertRaises(ValueError):
            w.handoff(self.out, selection)

    def test_rate_limit_stops_and_records_failure(self):
        self.plan['queries'] = ['first query', 'second query']
        w.write(self.root / 'plan.json', self.plan)
        with patch.object(w, 'search', side_effect=w.CollectionError('rate_limited')) as search:
            self.assertEqual(w.collect(self.args), 2)
        self.assertEqual(search.call_count, 1)
        m = w.read(self.out / 'manifest.json')
        self.assertEqual(m['status'], 'collection_failed')
        self.assertEqual(m['errors'][0]['kind'], 'rate_limited')

    def test_failed_download_resumes_from_query_cache(self):
        with patch.object(w, 'search', return_value=[raw(1)]), patch.object(w, 'download', side_effect=OSError('connection reset')):
            w.collect(self.args)
        self.assertEqual(w.read(self.out / 'manifest.json')['status'], 'collection_failed')
        self.args.resume = True
        with patch.object(w, 'search', side_effect=AssertionError('must reuse query')), patch.object(w, 'download', return_value=png()):
            w.collect(self.args)
        m = w.read(self.out / 'manifest.json')
        self.assertEqual(m['counts'], {'passed': 1})
        self.assertTrue(m['attempt_history'][0]['failed_images'])

    def test_reject_foreign_sources_and_invalid_images(self):
        opaque = raw('e1_AbC-123_xyz')
        self.assertEqual(w.normalize(opaque)['pin_id'], 'e1_AbC-123_xyz')
        self.assertEqual(w.normalize(opaque)['source_url'], 'https://www.pinterest.com/pin/e1_AbC-123_xyz/')
        with self.assertRaises(ValueError):
            w.normalize(raw('e1_../../outside'))
        with self.assertRaises(ValueError):
            w.normalize({'id': 1, 'src': 'https://example.com/image.jpg'})
        with self.assertRaises(ValueError):
            w.normalize({'src': 'https://i.pinimg.com/x.jpg', 'origin': 'javascript:alert(1)'})
        with self.assertRaises(OSError):
            w.image_info(b'not an image')
        self.plan['limit'] = 500
        with self.assertRaises(ValueError):
            w.validate_plan(self.plan)

    def test_corrupt_cache_is_repaired(self):
        self.collect()
        conn = w.cache_connection(self.root / 'library')
        row = w.normalize(raw(1))
        file, info, _, _ = w.cached_image(conn, self.root / 'library', row)
        file.write_bytes(b'corrupt cache')
        with patch.object(w, 'download', return_value=png()):
            restored, restored_info, _, cache_hit = w.cached_image(conn, self.root / 'library', row)
        self.assertFalse(cache_hit)
        self.assertEqual(w.digest(restored.read_bytes()), info['sha256'])
        conn.close()


if __name__ == '__main__':
    unittest.main()
