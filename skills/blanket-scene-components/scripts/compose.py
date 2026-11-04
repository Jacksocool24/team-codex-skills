"""Compose reviewed scene regions and local typography; never call a model."""
import argparse
import hashlib
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def compose(config_path, output):
    config_path, output = Path(config_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Output must be a new component directory; preserve prior revisions.')
    cfg = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if cfg['mode'] not in ('finished', 'custom'):
        raise ValueError('mode must be finished or custom')
    sources = {}
    for key in ('background', 'integration', 'product_reference'):
        path = Path(cfg[key])
        if not path.is_absolute() or not path.is_file():
            raise ValueError(f'{key}: existing absolute file required')
        sources[key] = {'path': str(path), 'sha256': sha(path)}
    with Image.open(cfg['background']) as im:
        if im.size != (970, 600):
            raise ValueError('Normalize and review background at 970x600 first.')
        background = im.convert('RGB')
    with Image.open(cfg['integration']) as im:
        generated = ImageOps.fit(im.convert('RGB'), (970, 600), Image.Resampling.LANCZOS)
    points = cfg['polygon']
    if len(points) < 3 or any(len(p) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in p) or not (0 <= p[0] < 970 and 0 <= p[1] < 600) for p in points):
        raise ValueError('polygon needs at least three in-canvas finite coordinate pairs')
    feather = float(cfg.get('feather_px', 5))
    if not 0 <= feather <= 20:
        raise ValueError('feather_px must be between 0 and 20')
    mask = Image.new('L', (970, 600))
    ImageDraw.Draw(mask).polygon([tuple(p) for p in points], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))
    alpha = np.asarray(mask)
    if not np.any(alpha == 255) or not np.any(alpha == 0):
        raise ValueError('Region must have both opaque product area and unchanged background.')
    foreground = generated.convert('RGBA')
    foreground.putalpha(mask)
    composite = Image.composite(generated, background, mask)
    typography = Image.new('RGBA', (1940, 1200))
    draw = ImageDraw.Draw(typography)
    used_rects = []
    for item in cfg['text']:
        x, y = item['xy']
        size = int(item['size'])
        step = int(item.get('line_height', size + 8))
        if size < 1 or step < size:
            raise ValueError('Invalid text size or line spacing')
        font_path = Path('C:/Windows/Fonts') / ('arialbd.ttf' if item.get('bold') else 'arial.ttf')
        font = ImageFont.truetype(str(font_path), size * 2)
        for i, line in enumerate(item['value'].split('\n')):
            xy = (x * 2, (y + i * step) * 2)
            box = draw.textbbox(xy, line, font=font)
            if not (0 <= box[0] <= box[2] <= 1940 and 0 <= box[1] <= box[3] <= 1200):
                raise ValueError('Text exceeds canvas; shorten or reposition it.')
            if any(box[0] < b[2] and box[2] > b[0] and box[1] < b[3] and box[3] > b[1] for b in used_rects):
                raise ValueError('Text blocks overlap.')
            used_rects.append(box)
            draw.text(xy, line, font=font, fill=item.get('color', '#202b2d'))
    text_layer = typography.resize((970, 600), Image.Resampling.LANCZOS)
    overlap = int(np.count_nonzero((np.asarray(text_layer)[:, :, 3] > 0) & (alpha > 0)))
    if overlap:
        raise ValueError(f'Text overlaps integration region at {overlap} pixels.')
    outside_changed = int(np.count_nonzero(np.any(np.asarray(composite) != np.asarray(background), axis=2) & (alpha == 0)))
    if outside_changed:
        raise ValueError('Background changed outside the mask.')
    base = composite.resize((1940, 1200), Image.Resampling.LANCZOS).convert('RGBA')
    final = Image.alpha_composite(base, typography).convert('RGB').resize((970, 600), Image.Resampling.LANCZOS)
    output.mkdir(parents=True)
    inputs = output / 'inputs'
    inputs.mkdir()
    for key, record in sources.items():
        target = inputs / (key + Path(record['path']).suffix.lower())
        shutil.copy2(record['path'], target)
        if sha(target) != record['sha256']:
            raise ValueError('Source changed while snapshotting; inspect partial output.')
        cfg[key] = str(target)
    for name, im in [('background', background), ('integration-normalized', generated),
                     ('integration-region-mask', mask), ('product-and-contact-layer', foreground),
                     ('composite', composite), ('text-layer', text_layer), ('final', final)]:
        im.save(output / (name + '.png'))
    final.resize((375, 232), Image.Resampling.LANCZOS).save(output / 'mobile.png')
    save_json(output / 'config.json', cfg)
    save_json(output / 'component.json', {
        'id': cfg['id'], 'sources': sources, 'canvas': [970, 600],
        'background_sha256': sha(output / 'background.png'),
        'final_sha256': sha(output / 'final.png'),
        'outside_region_changed_pixels': outside_changed,
        'text_region_overlap_pixels': overlap,
        'visual_review': 'pending', 'exact_photo_identity_verified': False,
        'reuse_scope': 'Same background and coordinates; foreground contains nearby furniture and contact shadow.'
    })
    return {'output': str(output), 'visual_review': 'pending', 'outside_region_changed_pixels': outside_changed}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    print(json.dumps(compose(args.config, args.out), ensure_ascii=False))
