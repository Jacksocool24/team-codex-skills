"""Render reusable product arrangements without generative redraw or stretching."""
import argparse
import hashlib
import json
import math
import re
import shutil
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

SCALE = 2
CANVAS = (970, 600)
CATALOG = Path(__file__).resolve().parents[1]/'assets/compositions/catalog.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def product_image(item):
    with Image.open(item['path']) as im:
        src = ImageOps.exif_transpose(im).convert('RGBA')
    original_size = src.size
    if item.get('crop_box'):
        l,t,r,b = item['crop_box']
        if not (0 <= l < r <= src.width and 0 <= t < b <= src.height):
            raise ValueError('crop_box outside source')
        src = src.crop((l,t,r,b))
    if item.get('remove_connected_white', False):
        # Only white connected to the canvas edge is removed, not isolated white print.
        pixels = np.asarray(src)
        eligible = np.all(pixels[:,:,:3] >= item.get('white_threshold', 245), axis=2)
        mask = Image.fromarray(np.where(eligible, 255, 0).astype('uint8')).copy()
        for seed in [(0,0),(mask.width-1,0),(0,mask.height-1),(mask.width-1,mask.height-1),
                     (mask.width//2,0),(mask.width//2,mask.height-1),(0,mask.height//2),(mask.width-1,mask.height//2)]:
            if mask.getpixel(seed) == 255:
                ImageDraw.floodfill(mask, seed, 128)
        alpha = pixels[:,:,3].copy()
        alpha[np.asarray(mask) == 128] = 0
        src.putalpha(Image.fromarray(alpha))
    if item.get('mask_path'):
        with Image.open(item['mask_path']) as im:
            explicit = im.convert('L')
        if explicit.size != src.size:
            raise ValueError('Explicit mask must match source after crop')
        src.putalpha(explicit)
    bbox = src.getbbox()
    if not bbox:
        raise ValueError('Empty product after masking')
    src = src.crop(bbox)
    roi = item.get('protected_box')
    if not roi or len(roi) != 4 or not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
        raise ValueError('Each product needs a normalized protected_box on its trimmed image')
    core = Image.new('L', src.size)
    ImageDraw.Draw(core).rectangle((round(roi[0]*src.width),round(roi[1]*src.height),
                                   round(roi[2]*src.width)-1,round(roi[3]*src.height)-1),fill=255)
    core_arr = np.minimum(np.asarray(core), np.asarray(src.getchannel('A')))
    core = Image.fromarray(core_arr)
    return src, core, {'original_size':list(original_size),'trim_bbox_after_crop':list(bbox),'trimmed_size':list(src.size)}


def place(src, core, slot):
    cx,cy = slot['center']
    bw,bh = slot['box']
    angle = slot['rotation']
    if not all(math.isfinite(float(v)) for v in (cx,cy,bw,bh,angle)) or min(bw,bh)<=0:
        raise ValueError('Invalid slot geometry')
    ratio = min(bw/src.width,bh/src.height)
    if ratio > 1.01:
        raise ValueError('Product source too small for final display pixels')
    size = (round(src.width*ratio*SCALE),round(src.height*ratio*SCALE))
    scaled = src.resize(size,Image.Resampling.LANCZOS)
    protected = core.resize(size,Image.Resampling.NEAREST)
    rotated = scaled.rotate(angle,Image.Resampling.BICUBIC,expand=True)
    protected = protected.rotate(angle,Image.Resampling.NEAREST,expand=True)
    x,y = round(cx*SCALE-rotated.width/2),round(cy*SCALE-rotated.height/2)
    if x<0 or y<0 or x+rotated.width>970*SCALE or y+rotated.height>600*SCALE:
        raise ValueError('Rotated product exceeds canvas')
    layer = Image.new('RGBA',(1940,1200))
    layer.alpha_composite(rotated,(x,y))
    area = Image.new('L',layer.size)
    area.paste(protected,(x,y))
    return layer,area,{'ratio':ratio,'rotation':angle,'z':slot['z'],
                      'center':slot['center'],'box':slot['box'],
                      'actual_bounds':[x/SCALE,y/SCALE,(x+rotated.width)/SCALE,(y+rotated.height)/SCALE]}


def render(brief_path, template_id, output):
    brief_path,output = Path(brief_path).resolve(),Path(output).resolve()
    if output.exists():
        raise ValueError('Output must not exist; preserve previous revisions')
    brief = read(brief_path)
    if brief.get('mode') not in ('finished','custom'):
        raise ValueError('Explicit finished/custom mode required')
    catalog = read(CATALOG)
    template = next((t for t in catalog['templates'] if t['id']==template_id),None)
    if not template:
        raise ValueError('Unknown composition template')
    if template['mode']=='scene-generation':
        raise ValueError('This composition requires scene generation and visual review, not flat-image distortion')
    items = brief['products']
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',item['id']) for item in items):
        raise ValueError('Product IDs must be stable lowercase filename-safe identifiers')
    for item in items:
        source = Path(item['path'])
        if not source.is_absolute() or not source.is_file():
            raise ValueError('Product source must be an existing absolute path')
    if len(items) not in template['supported_counts']:
        raise ValueError('Unsupported product count; create and validate another preset')
    if len({i['id'] for i in items}) != len(items):
        raise ValueError('Duplicate product IDs')
    if sorted(s['index'] for s in template['slots']) != list(range(len(items))):
        raise ValueError('Layout must cover every product exactly once')
    if len({s['z'] for s in template['slots']}) != len(items):
        raise ValueError('Each slot needs a unique stacking order')
    background = Image.new('RGBA',(1940,1200),brief.get('background_color','#ffffff'))
    source_records = []
    if brief.get('background'):
        with Image.open(brief['background']) as im:
            if im.size != CANVAS:
                raise ValueError('Background must be reviewed at 970x600')
            background = im.convert('RGBA').resize((1940,1200),Image.Resampling.LANCZOS)
        source_records.append({'role':'background','path':brief['background'],'sha256':digest(brief['background'])})
    scene_mask = np.zeros((1200,1940),dtype=bool)
    if template['mode']=='scene-local':
        scene = brief.get('scene',{})
        if scene.get('design_id') not in {i['id'] for i in items} or not scene.get('review_path'):
            raise ValueError('Matching scene design ID and its SHA-bound review are required')
        audit = read(scene['review_path'])
        if audit.get('scene_sha256')!=digest(scene['path']) or audit.get('status')!='accepted':
            raise ValueError('Scene review missing or outdated')
        with Image.open(scene['path']) as im:
            im = im.convert('RGBA')
        x,y,w,h = template['scene_box']
        fitted = ImageOps.contain(im,(w*SCALE,h*SCALE),Image.Resampling.LANCZOS)
        px,py = x*SCALE+(w*SCALE-fitted.width)//2,y*SCALE+(h*SCALE-fitted.height)//2
        background.alpha_composite(fitted,(px,py))
        scene_mask[py:py+fitted.height,px:px+fitted.width] = True
        source_records.append({'role':'scene','path':scene['path'],'sha256':digest(scene['path'])})
    layers = []
    for slot in sorted(template['slots'],key=lambda s:s['z']):
        item = items[slot['index']]
        src,core,trim = product_image(item)
        layer,core,geometry = place(src,core,slot)
        entry = {'id':item['id'],'slot':slot,'layer':layer,'core':core,'product':src,'geometry':geometry,'trim':trim}
        layers.append(entry)
        source_records.append({'role':'product','id':item['id'],'path':item['path'],'sha256':digest(item['path']),
                               'mask_sha256':digest(item['mask_path']) if item.get('mask_path') else None})
    checks = []
    union = np.zeros((1200,1940),dtype=bool)
    for entry in reversed(layers):
        mask = np.asarray(entry['layer'].getchannel('A'))>127
        core = np.asarray(entry['core'])>127
        occlusion = float(np.count_nonzero(mask & union)/max(1,np.count_nonzero(mask)))
        protected_occlusion = float(np.count_nonzero(core & union)/max(1,np.count_nonzero(core)))
        if occlusion > template['max_occlusion']+1e-8:
            raise ValueError(f"{entry['id']} occlusion {occlusion:.3f} exceeds template limit")
        if protected_occlusion > template['max_protected_occlusion']+1e-8:
            raise ValueError(f"{entry['id']} protected artwork occlusion {protected_occlusion:.3f} exceeds limit")
        if np.any(mask & scene_mask):
            raise ValueError('Product thumbnails overlap scene region')
        checks.append({'id':entry['id'],'occlusion_ratio':occlusion,'protected_occlusion_ratio':protected_occlusion,
                       'protected_box':items[entry['slot']['index']]['protected_box'],**entry['geometry'],**entry['trim']})
        union |= mask
    typography = Image.new('RGBA',(1940,1200))
    draw = ImageDraw.Draw(typography)
    boxes=[]

    def text(value,xy,size,bold=False,max_width=890,center=False):
        if not value or '\n' in value:
            raise ValueError('Use short single-line text for this library version')
        font = ImageFont.truetype('C:/Windows/Fonts/'+('arialbd.ttf' if bold else 'arial.ttf'),size*SCALE)
        width = draw.textlength(value,font=font)
        if width>max_width*SCALE:
            raise ValueError('Text too long; shorten it instead of shrinking type')
        x,y=xy[0]*SCALE,xy[1]*SCALE
        if center:
            x-=width/2
        bbox=draw.textbbox((x,y),value,font=font,anchor='lt')
        if bbox[0]<0 or bbox[1]<0 or bbox[2]>1940 or bbox[3]>1200:
            raise ValueError('Text outside canvas')
        if any(bbox[0]<b[2] and bbox[2]>b[0] and bbox[1]<b[3] and bbox[3]>b[1] for b in boxes):
            raise ValueError('Text blocks overlap')
        boxes.append(bbox)
        draw.text((x,y),value,font=font,anchor='lt',fill=brief.get('ink','#202b2d'))

    for field in ('headline','subline'):
        spec=catalog['text'][field]
        text(brief[field],spec['xy'],spec['size'],field=='headline',spec['max_width'])
    for slot in template['slots']:
        text(items[slot['index']]['label'],(slot['label_x'],slot.get('label_y',catalog['text']['label_y'])),
             catalog['text']['label_size'],max_width=170,center=True)
    if np.any((np.asarray(typography)[:,:,3]>0)&(union|scene_mask)):
        raise ValueError('Text overlaps a product or scene')
    image=background.copy()
    for entry in layers:
        # Decorative shadow follows the actual product alpha; no synthetic cloth detail.
        shadow_alpha=entry['layer'].getchannel('A').filter(ImageFilter.GaussianBlur(5*SCALE)).point(lambda v:round(v*.12))
        shadow=Image.new('RGBA',image.size,(20,28,30,0));shadow.putalpha(shadow_alpha)
        image.alpha_composite(shadow,(0,5*SCALE))
        image.alpha_composite(entry['layer'])
    product_composite=image.copy()
    image.alpha_composite(typography)
    final=image.convert('RGB').resize(CANVAS,Image.Resampling.LANCZOS)
    output.mkdir(parents=True)
    sources=output/'sources';sources.mkdir()
    snapshot_brief=json.loads(json.dumps(brief))
    for index,item in enumerate(items):
        target=sources/f'product-{index+1:02d}{Path(item["path"]).suffix}'
        shutil.copy2(item['path'],target)
        if digest(target)!=next(r['sha256'] for r in source_records if r.get('id')==item['id']):
            raise ValueError('Source changed during rendering')
        snapshot_brief['products'][index]['path']=str(target)
        if item.get('mask_path'):
            mask_target=sources/f'mask-{index+1:02d}.png'
            shutil.copy2(item['mask_path'],mask_target)
            snapshot_brief['products'][index]['mask_path']=str(mask_target)
    for entry in layers:
        entry['product'].save(sources/(entry['id']+'-trimmed.png'))
        entry['layer'].resize(CANVAS,Image.Resampling.LANCZOS).save(output/(entry['id']+'-layer.png'))
    if brief.get('background'):
        target=sources/('background'+Path(brief['background']).suffix)
        shutil.copy2(brief['background'],target)
        snapshot_brief['background']=str(target)
    if brief.get('scene') and template['mode']=='scene-local':
        target=sources/('scene'+Path(brief['scene']['path']).suffix)
        shutil.copy2(brief['scene']['path'],target)
        audit_target=sources/'scene-review.json'
        shutil.copy2(brief['scene']['review_path'],audit_target)
        snapshot_brief['scene']['path']=str(target)
        snapshot_brief['scene']['review_path']=str(audit_target)
    final.save(output/'final.png')
    final.resize((375,232),Image.Resampling.LANCZOS).save(output/'mobile.png')
    typography.resize(CANVAS,Image.Resampling.LANCZOS).save(output/'text-layer.png')
    product_composite.resize(CANVAS,Image.Resampling.LANCZOS).save(output/'products-composite.png')
    write(output/'brief.json',snapshot_brief)
    write(output/'template.json',template)
    result={'template_id':template_id,'template_name':template['name'],'canvas':list(CANVAS),
            'template_sha256':hashlib.sha256(json.dumps(template,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
            'catalog_sha256':digest(CATALOG),'renderer_sha256':digest(__file__),
            'sources':source_records,'product_checks':checks,'text_boxes':[[v/SCALE for v in b] for b in boxes],
            'text_product_overlap_pixels':0,'final_sha256':digest(output/'final.png'),
            'product_mode':brief['mode'],'visual_review':'pending','mobile_review':'pending',
            'model_calls':0,'fidelity':'Original source pixels resampled/rotated, never generatively redrawn; masking and visibility need visual review.'}
    write(output/'checks.json',result)
    return {'template':template_id,'output':str(output),'max_occlusion':max(c['occlusion_ratio'] for c in checks)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brief',required=True)
    parser.add_argument('--template',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    print(json.dumps(render(args.brief,args.template,args.out),ensure_ascii=False))
