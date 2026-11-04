"""Source-preserving planar artwork and background replacement. No model calls."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def absolute(value):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Input paths must be absolute')
    return path


def read_image(path, mode='RGB'):
    with Image.open(absolute(path)) as im:
        return ImageOps.exif_transpose(im).convert(mode)


def polygon(points, size, minimum=3):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < minimum or not np.isfinite(p).all():
        raise ValueError('Invalid polygon')
    if (p < 0).any() or (p[:, 0] >= size[0]).any() or (p[:, 1] >= size[1]).any():
        raise ValueError('Polygon outside source canvas')
    return p


def mask(spec, size):
    if 'path' in spec:
        with Image.open(absolute(spec['path'])) as im:
            if im.mode != 'L':
                raise ValueError('Masks must be L-mode grayscale images')
            result = ImageOps.exif_transpose(im).copy()
        if result.size != size:
            raise ValueError('Mask size mismatch')
        return result
    large = Image.new('L', (size[0] * 4, size[1] * 4))
    draw = ImageDraw.Draw(large)
    for key, fill in [('polygons', 255), ('exclude_polygons', 0)]:
        for points in spec.get(key, []):
            p = polygon(points, size)
            draw.polygon([tuple(v * 4) for v in p], fill=fill)
    return large.resize(size, Image.Resampling.LANCZOS)


def quad_mask(quad, size):
    p = polygon(quad, size, 4)
    if len(p) != 4:
        raise ValueError('Exactly four artwork corners required')
    edge = np.roll(p, -1, axis=0) - p
    nxt = np.roll(edge, -1, axis=0)
    cross = edge[:, 0] * nxt[:, 1] - edge[:, 1] * nxt[:, 0]
    if not (cross > 1).all():
        raise ValueError('Quad must be convex, clockwise TL TR BR BL')
    area = abs(np.dot(p[:, 0], np.roll(p[:, 1], -1)) - np.dot(p[:, 1], np.roll(p[:, 0], -1))) / 2
    if area < 16:
        raise ValueError('Artwork area too small')
    return p, mask({'polygons': [quad]}, size)


def warp_artwork(art, quad, size, cfg):
    ratio = float(cfg.get('artwork_ratio', art.width / art.height))
    if not np.isfinite(ratio) or not 0.02 <= ratio <= 50:
        raise ValueError('Invalid artwork ratio')
    width = max(2, round(1600 * min(1, ratio)))
    height = max(2, round(width / ratio))
    fit = cfg.get('artwork_fit', 'contain')
    if fit == 'contain':
        prepared = ImageOps.pad(art, (width, height), method=Image.Resampling.LANCZOS,
                                color=cfg.get('artwork_matte', '#ffffff'))
    elif fit == 'cover':
        prepared = ImageOps.fit(art, (width, height), method=Image.Resampling.LANCZOS)
    else:
        raise ValueError('artwork_fit must be contain or cover')
    target = [(0, 0), (width - 1, 0), (width - 1, height - 1), (0, height - 1)]
    matrix, rhs = [], []
    for (x, y), (u, v) in zip(quad, target):
        matrix.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y],
                       [0, 0, 0, x, y, 1, -v*x, -v*y]])
        rhs.extend([u, v])
    coeffs = np.linalg.solve(matrix, rhs)
    return prepared.transform(size, Image.Transform.PERSPECTIVE, coeffs,
                              resample=Image.Resampling.BICUBIC)


def compose(cfg, out):
    out = Path(out)
    if out.exists():
        raise FileExistsError('Use a new output directory; existing work is never overwritten')
    mode = cfg.get('mode')
    if mode not in ('artwork', 'background', 'both'):
        raise ValueError('Unknown mode')
    source_path = absolute(cfg['source'])
    source_hash = digest(source_path)
    if source_hash != cfg['source_sha256'].lower():
        raise ValueError('Source hash changed: recalibrate before reuse')
    source = read_image(source_path)
    if list(source.size) != cfg['canvas']:
        raise ValueError('Source canvas changed: recalibrate before reuse')
    if not cfg.get('source_notes', '').strip():
        raise ValueError('Source and rights notes required')
    size = source.size
    protect = np.asarray(mask(cfg['protected_mask'], size)) > 0
    if not protect.any():
        raise ValueError('Protected product structure must be marked')
    protected_image = Image.fromarray((protect * 255).astype('uint8'))
    product = source.copy()
    edits = Image.new('L', size)
    inputs = {str(source_path): source_hash}
    product_alpha = None
    if mode in ('artwork', 'both'):
        quad, edits = quad_mask(cfg['quad'], size)
        if np.any((np.asarray(edits) > 0) & protect):
            raise ValueError('Artwork overlaps protected structure')
        art = read_image(cfg['artwork'])
        warped = warp_artwork(art, quad, size, cfg)
        product = Image.composite(warped, source, edits)
        inputs[str(absolute(cfg['artwork']))] = digest(cfg['artwork'])
    if mode in ('background', 'both'):
        bg = read_image(cfg['background'])
        if bg.size != size:
            raise ValueError('Background must match canvas; crop explicitly before composition')
        inputs[str(absolute(cfg['background']))] = digest(cfg['background'])
        product_alpha = mask(cfg['product_mask'], size)
        alpha = np.asarray(product_alpha)
        if np.any(alpha[protect] != 255):
            raise ValueError('Protected structure must be inside solid product mask')
        if mode == 'both' and np.any(alpha[np.asarray(edits) > 0] != 255):
            raise ValueError('Artwork must be fully inside solid product mask')
        if cfg.get('shadow'):
            with Image.open(absolute(cfg['shadow'])) as shadow:
                if shadow.mode != 'RGBA' or shadow.size != size:
                    raise ValueError('Shadow must be canvas-size transparent RGBA')
                if shadow.getchannel('A').getextrema()[0] == 255:
                    raise ValueError('Shadow has no transparency')
                bg = Image.alpha_composite(bg.convert('RGBA'), shadow).convert('RGB')
            inputs[str(absolute(cfg['shadow']))] = digest(cfg['shadow'])
        final = Image.composite(product, bg, product_alpha)
    else:
        final = product.copy()
    final = Image.composite(source, final, protected_image)
    old, new = np.asarray(source), np.asarray(final)
    changed = np.any(old != new, axis=2)
    if np.any(changed & protect):
        raise AssertionError('Protected pixels changed')
    if mode == 'artwork' and np.any(changed & (np.asarray(edits) == 0)):
        raise AssertionError('Pixels outside artwork changed')
    if mode == 'background' and np.any(changed & (np.asarray(product_alpha) == 255)):
        raise AssertionError('Solid product pixels changed')
    for key in ('protected_mask', 'product_mask'):
        if isinstance(cfg.get(key), dict) and cfg[key].get('path'):
            path = absolute(cfg[key]['path'])
            inputs[str(path)] = digest(path)
    work = out / '.work'
    work.mkdir(parents=True, exist_ok=False)
    source.save(work / 'source.png')
    product.save(work / 'product.png')
    protected_image.save(work / 'protected.png')
    edits.save(work / 'edit-mask.png')
    if product_alpha is not None:
        product_alpha.save(work / 'product-alpha.png')
    final.save(out / 'final.png')
    ImageOps.contain(final, (375, 375)).save(work / 'mobile.png')
    report = {
        'mode': mode, 'canvas': list(size), 'inputs': inputs,
        'final_sha256': digest(out / 'final.png'),
        'protected_pixels': int(protect.sum()), 'protected_changed_pixels': 0,
        'changed_pixels': int(changed.sum()), 'automated_checks': 'passed',
        'visual_review': 'pending', 'delivery_status': 'not_reviewed',
        'limitations': 'No automatic segmentation, relighting, new angles or physical product verification.'
    }
    (work / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    (work / 'check.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    print(json.dumps(compose(config, args.out), ensure_ascii=False, indent=2))
