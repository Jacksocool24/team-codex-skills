"""Apply factual information and typography to a hash-locked, text-free frame."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
STYLES=ROOT/'assets/visual-styles/catalog.json'
COMPONENTS=ROOT/'assets/information-components/catalog.json'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def checked_file(record):
    path=Path(record['path'])
    if not path.is_absolute() or not path.is_file() or sha(path)!=record['sha256']:
        raise ValueError('Missing or changed locked input: '+str(path))
    return path


def confirmed(facts,key):
    item=facts['facts'][key]
    if item.get('status') not in ('user_confirmed','verified_from_assets','user_and_metadata_confirmed') or not item.get('evidence'):
        raise ValueError('Unconfirmed fact: '+key)
    return item['value']


def factual_counts(facts,base):
    count=confirmed(facts,'design_count')
    sizes=confirmed(facts,'sizes_inches')
    if not isinstance(count,int) or isinstance(count,bool) or count!=len(base['products']):
        raise ValueError('Design count differs from locked products')
    if len({p['id'] for p in base['products']})!=count:
        raise ValueError('Duplicate product IDs')
    if not sizes or any(len(s)!=2 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not np.isfinite(v) or v<=0 for v in s) for s in sizes):
        raise ValueError('Invalid size facts')
    if len({tuple(s) for s in sizes})!=len(sizes):
        raise ValueError('Duplicate sizes')
    matrix=facts['product_matrix']
    expected={(p['id'],tuple(s)) for p in base['products'] for s in sizes}
    if len(matrix)!=len(expected) or {(r['design_id'],tuple(r['size_inches'])) for r in matrix}!=expected:
        raise ValueError('Product size matrix is incomplete or duplicated')
    if any(not r.get('evidence') for r in matrix):
        raise ValueError('Matrix entries need evidence')
    return count,sizes


def contrast(foreground,background):
    def luminance(rgb):
        v=np.asarray(rgb,dtype=float)/255
        linear=np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)
        return np.sum(linear*np.array([.2126,.7152,.0722]),axis=-1)
    a,b=luminance(foreground),luminance(background)
    return (np.maximum(a,b)+.05)/(np.minimum(a,b)+.05)


def render(config_path,out):
    config_path,out=Path(config_path).resolve(),Path(out).resolve()
    if out.exists():
        raise ValueError('Use a new output directory; preserve earlier revisions')
    config=read(config_path)
    base_path=checked_file(config['base_manifest'])
    facts_path=checked_file(config['facts'])
    base,facts=read(base_path),read(facts_path)
    if base['mode']!=facts['mode'] or base['parent_key']!=facts['parent_key']:
        raise ValueError('Product mode or parent does not match')
    profiles={s['id']:s for s in read(STYLES)['profiles']}
    if config['style_id'] not in profiles:
        raise ValueError('Unknown visual style')
    style=profiles[config['style_id']]
    definitions={c['id']:c for c in read(COMPONENTS)['components']}
    ids=[c['id'] for c in config['components']]
    if len(set(ids))!=len(ids) or any(i not in definitions for i in ids):
        raise ValueError('Unknown or duplicate information component')
    frame_path=checked_file(base['frame'])
    template_path=checked_file(base['template'])
    template=read(template_path)
    with Image.open(frame_path) as im:
        if im.size!=(970,600):
            raise ValueError('Locked frame must be 970x600')
        background=im.convert('RGB')
    obstacles=np.zeros((600,970),dtype=bool)
    for record in base['layers']:
        with Image.open(checked_file(record)) as layer:
            if layer.mode!='RGBA' or layer.size!=(970,600):
                raise ValueError('Expected a 970x600 RGBA product layer')
            obstacles |= np.asarray(layer)[:,:,3]>0
    if len(base['layers'])!=len(base['products']):
        raise ValueError('Product layer coverage mismatch')
    if sorted(s['index'] for s in template['slots'])!=list(range(len(base['products']))):
        raise ValueError('Invalid locked slot coverage')
    canvas=Image.new('RGBA',(1940,1200))
    draw=ImageDraw.Draw(canvas)
    boxes=[];records=[];fonts={};actual_text=[]

    def text(value,xy,role,width=890,center=False):
        spec=style[role]
        if not value or '\n' in value:
            raise ValueError('Use nonempty short single-line text')
        font_path=Path('C:/Windows/Fonts')/spec['font']
        if not font_path.is_file():
            raise ValueError('Configured font unavailable; select a verified installed font')
        font=ImageFont.truetype(str(font_path),spec['size']*2)
        fonts[spec['font']]=sha(font_path)
        tw=draw.textlength(value,font=font)
        if tw>width*2:
            raise ValueError('Text exceeds its reserved region; shorten it, do not squeeze the font')
        x,y=xy[0]*2,xy[1]*2
        if center:
            x-=tw/2
        box=draw.textbbox((x,y),value,font=font,anchor='lt')
        if box[0]<0 or box[1]<0 or box[2]>1940 or box[3]>1200:
            raise ValueError('Text exceeds canvas')
        if any(box[0]<b[2] and box[2]>b[0] and box[1]<b[3] and box[3]>b[1] for b in boxes):
            raise ValueError('Information components overlap')
        boxes.append(box)
        glyph=Image.new('L',canvas.size)
        ImageDraw.Draw(glyph).text((x,y),value,font=font,anchor='lt',fill=255)
        sample=np.asarray(glyph.resize((970,600),Image.Resampling.LANCZOS))>180
        rgb=ImageColor.getrgb(spec['color'])
        ratios=contrast(rgb,np.asarray(background)[sample])
        minimum=float(np.min(ratios)) if ratios.size else 0
        if minimum<style['minimum_sampled_contrast']:
            raise ValueError(f'Insufficient text/background contrast for {role}: {minimum:.2f}')
        draw.text((x,y),value,font=font,anchor='lt',fill=spec['color'])
        records.append({'text':value,'role':role,'box':[v/2 for v in box],
                        'font':spec['font'],'font_px':spec['size'],'color':spec['color'],'minimum_sampled_contrast':minimum})
        actual_text.append(value)

    for instance in config['components']:
        definition=definitions[instance['id']]
        if base['mode'] not in definition['available_modes']:
            raise ValueError('Component not compatible with product mode')
        ident=instance['id'];variant=instance.get('variant')
        if 'variants' in definition and variant not in definition['variants']:
            raise ValueError('Unknown information variant')
        if ident=='collection-heading':
            value=base['copy']['headline'] if variant=='baseline' else confirmed(facts,'product_name')
            text(value,definition['xy'],definition['role'],definition['max_width'])
        elif ident=='verified-fact-line':
            if variant=='baseline':
                value=base['copy']['subline']
            else:
                count,sizes=factual_counts(facts,base)
                value=f'{count} designs. {len(sizes)} sizes.'
            text(value,definition['xy'],definition['roles'][variant],definition['max_width'])
        elif ident=='product-labels':
            for slot in template['slots']:
                item=base['products'][slot['index']]
                text(item['label'],(slot['label_x'],slot.get('label_y',base['default_label_y'])),definition['role'],definition['max_width'],True)
        elif ident=='size-line':
            _,sizes=factual_counts(facts,base)
            value=' / '.join(f'{w:g} x {h:g}' for w,h in sizes)+' in'
            text(value,definition['xy'],definition['role'],definition['max_width'])
    text_layer=canvas.resize((970,600),Image.Resampling.LANCZOS)
    alpha=np.asarray(text_layer)[:,:,3]
    if np.any((alpha>0)&obstacles):
        raise ValueError('Information overlaps a locked product')
    final=Image.alpha_composite(background.convert('RGBA'),text_layer).convert('RGB')
    changed=np.any(np.asarray(final)!=np.asarray(background),axis=2)
    outside_changed=int(np.count_nonzero(changed&(alpha==0)))
    product_changed=int(np.count_nonzero(changed&obstacles))
    if outside_changed or product_changed:
        raise ValueError('Locked frame pixels changed outside typography')
    out.mkdir(parents=True)
    final.save(out/'final.png')
    text_layer.save(out/'text-layer.png')
    final.resize((375,232),Image.Resampling.LANCZOS).save(out/'mobile.png')
    write(out/'config.json',config)
    write(out/'style.json',style)
    write(out/'information.json',[definitions[i] for i in ids])
    write(out/'checks.json',{'style_id':style['id'],'components':config['components'],
          'base_manifest_sha256':sha(base_path),'frame_sha256':sha(frame_path),'template_sha256':sha(template_path),
          'facts_sha256':sha(facts_path),'styles_sha256':sha(STYLES),'information_sha256':sha(COMPONENTS),
          'renderer_sha256':sha(__file__),'font_hashes':fonts,'text':records,
          'copy_character_count':sum(len(t) for t in actual_text),'canvas':[970,600],
          'final_sha256':sha(out/'final.png'),'product_changed_pixels':product_changed,
          'outside_text_changed_pixels':outside_changed,'visual_review':'pending','model_calls':0})
    return {'out':str(out),'style':style['name'],'product_changed_pixels':product_changed,'outside_text_changed_pixels':outside_changed}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args()
    print(json.dumps(render(args.config,args.out),ensure_ascii=False))
