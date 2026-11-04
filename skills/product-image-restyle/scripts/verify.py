"""Exercise preservation, perspective mapping and refusal cases without generation."""
import argparse
import copy
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from compose import compose, digest, read_image


def reject(cfg, dest):
    try:
        compose(cfg, dest)
    except (ValueError, FileExistsError):
        return
    raise AssertionError('Invalid configuration was accepted')


def verify(root, real_root=None):
    root.mkdir(parents=True, exist_ok=False)
    source = Image.new('RGB', (240, 300), '#cccccc')
    draw = ImageDraw.Draw(source)
    draw.rectangle((60, 30, 180, 265), fill='#999999')
    draw.rectangle((60, 240, 180, 265), fill='#202020')
    source.save(root / 'source.png')
    art = Image.new('RGB', (100, 200), '#49b7ba')
    ImageDraw.Draw(art).rectangle((0, 0, 49, 99), fill='#fdbd44')
    art.save(root / 'artwork.png')
    Image.new('RGB', source.size, '#faf5ed').save(root / 'background.png')
    alpha = Image.new('L', source.size)
    ImageDraw.Draw(alpha).rectangle((60, 30, 180, 265), fill=255)
    alpha.save(root / 'alpha.png')
    cfg = {
        'mode': 'artwork', 'source': str(root / 'source.png'),
        'source_sha256': digest(root / 'source.png'), 'canvas': [240, 300],
        'protected_mask': {'polygons': [[[65,245],[175,245],[175,260],[65,260]]]},
        'artwork': str(root / 'artwork.png'), 'quad': [[70,40],[165,45],[170,230],[68,225]],
        'background': str(root / 'background.png'),
        'product_mask': {'path': str(root / 'alpha.png')},
        'source_notes': 'Synthetic fixture, not a commercial design.'
    }
    results = []
    for mode in ['artwork', 'background', 'both']:
        cfg['mode'] = mode
        report = compose(cfg, root / mode)
        assert report['changed_pixels'] > 0 and report['protected_changed_pixels'] == 0
        if mode != 'background':
            final = read_image(root / mode / 'final.png')
            assert final.getpixel((90, 80)) == (253, 189, 68), 'Artwork orientation/mapping failed'
        results.append(mode)
    bad = copy.deepcopy(cfg)
    bad['source_sha256'] = '0' * 64
    reject(bad, root / 'invalid-hash')
    bad = copy.deepcopy(cfg)
    bad['quad'] = [[70,40],[165,45],[175,260],[68,260]]
    reject(bad, root / 'invalid-overlap')
    bad = copy.deepcopy(cfg)
    bad['quad'] = [[70,40],[170,230],[165,45],[68,225]]
    reject(bad, root / 'invalid-quad')
    bad = copy.deepcopy(cfg)
    bad['product_mask'] = {'polygons': [[[70,40],[165,40],[165,230],[70,230]]]}
    reject(bad, root / 'invalid-alpha')
    reject(cfg, root / 'both')
    results.extend(['stale-source-refused', 'protected-overlap-refused', 'crossed-quad-refused',
                    'missing-product-structure-refused', 'overwrite-refused'])
    if real_root:
        # Coordinates apply only to the inspected 1600px front-and-back source images.
        for number, (name, quad, base) in enumerate([
            ('加厚标准款', [[183,169],[704,169],[704,1417],[183,1417]], [169,1424,720,1491]),
            ('纲丝脚', [[183,169],[704,169],[704,1417],[183,1417]], [164,1424,720,1510]),
            ('银色磨砂', [[222,105],[739,105],[739,1432],[222,1432]], [201,1438,756,1515]),
            ('黑色磨砂', [[183,169],[704,169],[704,1417],[183,1417]], [169,1424,720,1500]),
        ], 1):
            path = real_root / name / '主图1.jpg'
            if not path.exists():
                raise FileNotFoundError(path)
            x1, y1, x2, y2 = base
            real = {
                'mode': 'artwork', 'source': str(path), 'source_sha256': digest(path),
                'canvas': [1600,1600], 'artwork': str(root / 'artwork.png'),
                'quad': quad,
                'protected_mask': {'polygons': [
                    [[x1,y1],[x2,y1],[x2,y2],[x1,y2]],
                    [[160,150],[730,150],[730,160],[160,160]] if number != 3 else
                    [[205,87],[755,87],[755,96],[205,96]],
                    [[880,85],[1450,85],[1450,1520],[880,1520]]
                ]},
                'source_notes': 'User product mockup; generated local color-grid test only, not a final advertisement.'
            }
            report = compose(real, root / f'real-{number:02d}')
            old = np.asarray(read_image(path))
            new = np.asarray(read_image(root / f'real-{number:02d}' / 'final.png'))
            assert np.array_equal(old[1424:, :], new[1424:, :]) if number != 3 else np.array_equal(old[1438:, :], new[1438:, :])
            assert np.array_equal(old[:, 800:], new[:, 800:]), 'Rear view changed'
            results.append(f'real-{number:02d}: base and rear unchanged')
    summary = {'passed': results, 'visual_review': 'pending', 'paid_generation_calls': 0}
    (root / 'verification.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--real-root', type=Path)
    args = parser.parse_args()
    verify(args.out.resolve(), args.real_root.resolve() if args.real_root else None)
