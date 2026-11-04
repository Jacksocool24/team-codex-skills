"""Fixed seven-image parent campaigns; reuses the shared generation/recovery pipeline."""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
from pathlib import Path
import shutil
import sys
from string import Template
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
import workflow as w
import visual

MODULES = ('hero', 'details', 'designs', 'lifestyle', 'sizes', 'care', 'gift')
SCENES = ('hero', 'living', 'bedroom', 'care', 'gift')
SIZES = [[30,40], [40,50], [50,60], [60,80]]
FILES = {key:f'{i+1:02}-{key}.png' for i,key in enumerate(MODULES)}


def paths_in(brief):
    paths = []
    for design in brief['designs']:
        paths.extend(design['artwork'].values())
        paths.extend([design['front'], design['detail']])
    for scene in brief['scenes'].values():
        paths.extend(scene['references'])
    if brief.get('detail_photo'):
        paths.append(brief['detail_photo']['path'])
    return list(dict.fromkeys(paths))


def validate(brief, base):
    w.require(brief.get('schema_version') == 2 and brief.get('profile') == 'parent-seven', 'Use schema_version 2 and profile parent-seven')
    w.require(brief.get('product_mode') in ('finished', 'custom'), 'Choose finished or custom blankets')
    custom = brief.get('product_mode') == 'custom'
    if custom:
        w.require(brief.get('layout') in ('lean-v3','visual-v4'), 'Custom campaigns require visual-v4 (lean-v3 for historical restore only)')
        config = brief.get('customization', {})
        w.require(config.get('confirmed') is True, 'Confirm customer-photo customization')
        w.text(config.get('source'), 'customization.source')
        counts = config.get('photo_counts', [])
        w.require(isinstance(counts, list) and counts and
                  all(type(n) is int and 1 <= n <= 10 for n in counts) and
                  len(set(counts)) == len(counts), 'Provide unique confirmed photo counts from 1 to 10')
        w.require(config.get('instruction_scope') == 'selection-only',
                  'Seven-image custom mode supports selection guidance, not unverified upload UI')
        w.require(config.get('example_disclosure') == 'Example photos shown.',
                  'Label supplied photos as examples')
        w.require(brief.get('copy', {}).get('details', {}).get('selection_labels') ==
                  ['Choose a layout', 'Pick your photos', 'Choose a size'],
                  'Use selection guidance without implying a verified order/upload sequence')
    w.require(brief.get('sizes') == SIZES, 'Require all four sizes in canonical order')
    for key in ('name','brand','parent_key','style'):
        w.text(brief.get(key), key)
    designs = brief.get('designs', [])
    w.require(1 <= len(designs) <= 10, 'Current layout supports 1..10 actual designs; never truncate a larger family')
    ids = [d['id'] for d in designs]
    w.require(len(set(ids)) == len(ids), 'Duplicate design ID')
    for design in designs:
        w.text(design.get('name'), 'design.name')
        w.require(set(design['artwork']) == {'30x40','40x50','50x60','60x80'}, 'Each design needs all four size artworks')
        if custom:
            w.require(type(design.get('photo_count')) is int and design['photo_count'] in counts,
                      'Each custom design needs a confirmed photo_count')
    if custom:
        w.require(sorted({d['photo_count'] for d in designs}) == sorted(counts),
                  'Photo-count coverage mismatch')
    w.require(set(brief.get('copy',{})) == set(MODULES), 'Exactly seven module copy entries required')
    for key in ('ink','accent','paper'):
        w.require(re.fullmatch(r'#[0-9a-fA-F]{6}',brief.get('palette',{}).get(key,'')),f'Invalid palette: {key}')
    for ident in ('details','lifestyle','care'):
        labels=brief['copy'][ident].get('labels')
        w.require(isinstance(labels,list) and len(labels)==2,f'{ident}: require two labels')
        for label in labels:
            w.text(label,f'{ident}.labels')
    w.text(brief['copy']['sizes'].get('footer'),'sizes.footer')
    for ident, entry in brief['copy'].items():
        for key in ('headline','alt'):
            w.text(entry.get(key), f'{ident}.{key}')
        w.require(len(entry['alt']) <= 100, 'Alt text exceeds internal 100-character review target')
        visible = ' '.join([entry.get('headline',''), entry.get('subline',''), entry.get('footer',''), *entry.get('labels',[])])
        w.require(not re.search(r'(?<!\w)'+re.escape(brief['brand'])+r'(?!\w)', visible, re.I), f'{ident}: keep brand names out of image copy')
        for fact_id in entry.get('claims',[]):
            fact = brief.get('facts',{}).get(fact_id,{})
            w.require(fact.get('confirmed') is True and fact.get('source') and fact.get('value'), f'Unconfirmed fact: {fact_id}')
    w.require(set(brief.get('scenes',{})) == set(SCENES), 'Require five scene assets: hero/living/bedroom/care/gift')
    for name, scene in brief['scenes'].items():
        w.require(scene.get('design_id') in ids, f'{name}: unknown design ID')
        w.require(scene.get('shown_size') in SIZES, f'{name}: unknown size')
        w.require(scene.get('references'), f'{name}: product references required')
        w.text(scene.get('prompt'), f'{name}.prompt')
    w.require(brief.get('detail_design_id') in ids, 'Unknown detail design')
    w.require(brief.get('size_design_id') in ids, 'Unknown size illustration design')
    resolved = {}
    for raw in paths_in(brief):
        path = Path(raw)
        path = (base / path).resolve() if not path.is_absolute() else path.resolve()
        w.picture(path)
        resolved[raw] = path
    by_id={d['id']:d for d in designs}
    for name,scene in brief['scenes'].items():
        a,b=scene['shown_size']
        artwork=resolved[by_id[scene['design_id']]['artwork'][f'{a}x{b}']]
        w.require(artwork in [resolved[p] for p in scene['references']],f'{name}: references must include its actual design and size artwork')
    if brief.get('layout') == 'visual-v4':
        visual.validate(brief)
        for ident in ('details','designs','sizes','lifestyle'):
            if ident == 'lifestyle':
                page=visual.Canvas(brief); copy=brief['copy'][ident]
                page.text(copy['headline'],(26,28),44,915,bold=True,max_lines=1,bottom=90)
                for label in copy['labels']:
                    page.text(label,(22,487),36,440,bold=True,max_lines=1)
            else:
                visual.compose(brief,resolved,{},ident)
    return resolved


def prepare(brief_file, root, restore_legacy_layout=False):
    brief_file, root = Path(brief_file).resolve(), Path(root).resolve()
    brief = w.read(brief_file)
    brief.setdefault('layout','visual-v4')
    w.require(brief['layout'] in ('visual-v4','lean-v3','legacy'), 'Unknown layout')
    w.require(brief['layout']=='visual-v4' or restore_legacy_layout,
              'New campaigns use visual-v4; --restore-legacy-layout is only for explicit historical restoration')
    template_file='scene-prompts-v4.json' if brief['layout']=='visual-v4' else 'scene-prompts.json'
    templates = w.read(Path(__file__).resolve().parents[1]/'references'/template_file)
    for ident, scene in brief.get('scenes',{}).items():
        if 'prompt' not in scene:
            template_name=scene.get('prompt_template',ident)
            w.require(template_name in templates,'Unknown scene prompt template')
            params=dict(scene.get('prompt_params',{}))
            params.update(width=str(scene['shown_size'][0]),height=str(scene['shown_size'][1]))
            scene['prompt']=Template(templates[template_name]).substitute(params)
        if brief['layout']=='visual-v4' and ident in visual.DEFAULT_TEXT:
            spec=visual.text_spec(brief,ident)
            x,y,width,height=spec['box']
            previous_note=scene.get('text_region_instruction')
            if previous_note and scene['prompt'].endswith(previous_note):
                scene['prompt']=scene['prompt'][:-len(previous_note)]
            note=(f' Final local text occupies the rectangle x={x}, y={y}, width={width}, height={height} '
                'on a 970x600 canvas. Keep this precise region as naturally quiet wall or background, '
                'with sufficient contrast for dark type; exclude the product, faces and busy props from it. '
                'Keep one continuous full photographic scene. No graphic sidebar, panels, text, logos or watermark.')
            if not scene['prompt'].endswith(note):
                scene['prompt']+=note
            scene['text_region_instruction']=note
    paths = validate(brief, brief_file.parent)
    w.require(not root.exists() or not any(root.iterdir()), 'Use a new empty campaign directory')
    root.mkdir(parents=True,exist_ok=True)
    sources = {}
    for raw, path in paths.items():
        sha = w.digest(path)
        relative = f'sources/{sha}{path.suffix.lower()}'
        target = root/relative
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.copy2(path,target)
        sources[raw] = {'file':relative,'original':str(path),'sha256':sha}
    child = {'schema_version':1,'name':brief['name']+' / scene materials','brand':brief['brand'],
             'marketplace':'US','product_mode':brief['product_mode'],'sizes':SIZES,'asins':[],
             'identity_lock':'Use only the supplied actual product references for each scene. Preserve the exact print, orientation, colours and border. Do not mix designs or replace fixed artwork with customer photos.',
             'style':brief['style'],'facts':{},'modules':[]}
    if brief['product_mode'] == 'custom':
        child['customization'] = brief['customization']
        child['identity_lock'] = ('The supplied photos are demonstration customer photos, not fixed designs. '
            'For these example scenes preserve the exact sample photos, photo-slot count, dividing lines, '
            'borders, orientation and colors. Never invent added text, extra slots or physical photo patches. '
            'Do not render a customization interface or upload instructions.')
    for ident, scene in brief['scenes'].items():
        width,height = scene.get('canvas',[970,600])
        child['modules'].append({'id':ident,'kind':'image','purpose':'scene_material',
            'amazon_module':'Intermediate scene material; not a final upload module',
            'spec':{'width':width,'height':height,'max_bytes':20000000,'verified':False},
            'text_mode':'native','shown_size':scene['shown_size'],'headline':ident,'body':'',
            'alt':'Product scene material','claims':[],'prompt':scene['prompt'],
            'references':[str(root/sources[p]['file']) for p in scene['references']]})
    w.write(root/'scene-brief.json',child)
    generated = w.prepare(root/'scene-brief.json',root/'generation')
    project={'brief':brief,'sources':sources,'generation_fingerprint':generated['fingerprint'],'created_at':w.now()}
    project['fingerprint']=w.signature(project)
    w.write(root/'campaign.json',project)
    w.write(root/'review.json',{'project_fingerprint':project['fingerprint'],'modules':{}})
    reused={}
    for ident,scene in brief['scenes'].items():
        if not scene.get('reuse_from'):
            continue
        previous=Path(scene['reuse_from']).resolve()
        old=load(previous)
        old_scene=old['brief']['scenes'][ident]
        for key in ('brand','product_mode','parent_key','style'):
            w.require(old['brief'][key]==brief[key],f'{ident}: reuse product mismatch')
        if brief['product_mode'] == 'custom':
            w.require(old['brief'].get('customization') == brief.get('customization'),
                      f'{ident}: customization changed; no reuse')
        for key in ('design_id','shown_size','prompt'):
            w.require(old_scene[key]==scene[key],f'{ident}: changed {key}; generate a new scene')
        w.require(old_scene.get('canvas',[970,600])==scene.get('canvas',[970,600]),f'{ident}: changed canvas; no reuse')
        old_hashes=[old['sources'][p]['sha256'] for p in old_scene['references']]
        w.require(old_hashes==[sources[p]['sha256'] for p in scene['references']],f'{ident}: changed reference; no reuse')
        original=scene_path(previous,ident)
        target=root/'generation/raw'/f'{ident}.png'; target.parent.mkdir(exist_ok=True)
        shutil.copy2(original,target)
        reused[ident]={'status':'completed','sha256':w.digest(target),'reused_from':str(original),'source_fingerprint':old['fingerprint']}
    if reused:
        w.write(root/'generation/generation-state.json',reused)
    print(f'Prepared seven-image campaign with {len(brief["designs"])} designs: {root}')


def load(root):
    root = Path(root).resolve()
    project = w.read(root/'campaign.json')
    w.require(w.signature({k:v for k,v in project.items() if k!='fingerprint'}) == project['fingerprint'], 'Campaign changed; prepare a new revision')
    for source in project['sources'].values():
        path = (root/source['file']).resolve()
        w.require(path.is_relative_to(root) and path.is_file() and w.digest(path)==source['sha256'], 'Changed or missing source snapshot')
    child = w.load_project(root/'generation')
    w.require(child['fingerprint']==project['generation_fingerprint'], 'Scene generation project replaced')
    return project


def face(size, bold=False, serif=False):
    family=('georgiab.ttf' if bold else 'georgia.ttf') if serif else ('arialbd.ttf' if bold else 'arial.ttf')
    return ImageFont.truetype('C:/Windows/Fonts/'+family,size)


def draw_text(im, value, xy, size, color, *, width, bold=False, serif=False, max_lines=3, bottom=600):
    draw=ImageDraw.Draw(im)
    font=face(size,bold,serif)
    lines=w.lines(draw,value,font,width)
    w.require(len(lines)<=max_lines, f'Text too long for layout: {value}')
    x,y=xy
    for line in lines:
        w.require(draw.textlength(line,font=font)<=width, f'Text exceeds width: {value}')
        w.require(y+size+5<=bottom,f'Text exceeds region: {value}')
        draw.text((x,y),line,font=font,fill=color)
        y+=size+8
    return y


def paste(im, path, box, *, fit=False):
    x,y,width,height=box
    with Image.open(path) as original:
        source=ImageOps.exif_transpose(original).convert('RGBA')
        rgb=Image.new('RGBA',source.size,'white')
        rgb.alpha_composite(source)
        rgb=rgb.convert('RGB')
        scale=max(width/rgb.width,height/rgb.height) if fit else min(width/rgb.width,height/rgb.height)
        w.require(scale<=1.01,'Source too small; avoid unreviewed upscaling')
        rendered=ImageOps.fit(rgb,(width,height),method=Image.Resampling.LANCZOS) if fit else ImageOps.contain(rgb,(width,height),method=Image.Resampling.LANCZOS)
    im.paste(rendered,(x+(width-rendered.width)//2,y+(height-rendered.height)//2))


def source_path(project,root,raw):
    return root/project['sources'][raw]['file']


def scene_path(root,ident):
    state=w.read(root/'generation/generation-state.json')
    path=root/'generation/raw'/f'{ident}.png'
    w.require(state.get(ident,{}).get('status')=='completed' and path.is_file() and w.digest(path)==state[ident].get('sha256'), f'{ident}: generation not complete or changed')
    return path


def paste_front(im,path,box):
    # Remove only the white photography margin; preserve the blanket's edge.
    with Image.open(path) as opened:
        photo=ImageOps.exif_transpose(opened).convert('RGB')
        mask=ImageChops.difference(photo,Image.new('RGB',photo.size,'white')).convert('L').point(lambda v:255 if v>20 else 0)
        bounds=mask.getbbox()
        if bounds:
            left,top,right,bottom=bounds
            photo=photo.crop((max(0,left-5),max(0,top-5),min(photo.width,right+5),min(photo.height,bottom+5)))
        x,y,width,height=box
        w.require(min(width/photo.width,height/photo.height)<=1.01,'Front source too small')
        rendered=ImageOps.contain(photo,(width,height),method=Image.Resampling.LANCZOS)
        im.paste(rendered,(x+(width-rendered.width)//2,y+(height-rendered.height)//2))


def title(im,brief,ident, *, size=46, subtitle=True):
    copy=brief['copy'][ident]
    ink=brief['palette']['ink']
    draw_text(im,copy['headline'],(32,24),size,ink,width=906,bold=True,serif=True,max_lines=1,bottom=90)
    if subtitle and copy.get('subline'):
        draw_text(im,copy['subline'],(34,82),28,ink,width=902,max_lines=1,bottom=125)


def compose(root,project,ident):
    if project['brief'].get('layout')=='visual-v4':
        return visual.compose(project['brief'],{raw:root/info['file'] for raw,info in project['sources'].items()},
                              {name:scene_path(root,name) for name in SCENES},ident)
    if project['brief'].get('layout')=='lean-v3':
        return compose_lean(root,project,ident)
    b=project['brief']; c=b['copy'][ident]; p=b['palette']
    ink,accent,paper=p['ink'],p['accent'],p['paper']
    im=Image.new('RGB',(970,600),paper)
    geometry={}
    designs={d['id']:d for d in b['designs']}
    if ident in ('hero','gift'):
        paste(im,scene_path(root,ident),(0,0,970,600))
        # A light editorial panel keeps type readable without changing product pixels.
        panel=Image.new('RGBA',im.size,(0,0,0,0))
        draw=ImageDraw.Draw(panel)
        draw.rectangle((0,0,334,599),fill=(*tuple(int(paper[i:i+2],16) for i in (1,3,5)),245))
        im=Image.alpha_composite(im.convert('RGBA'),panel).convert('RGB')
        headline_size=48 if ident=='hero' else 42
        y=draw_text(im,c['headline'],(30,133),headline_size,ink,width=278,bold=True,serif=True,max_lines=4,bottom=405)
        draw_text(im,c.get('subline',''),(32,y+25),30,ink,width=270,max_lines=3,bottom=550)
        ImageDraw.Draw(im).line((32,105,115,105),fill=accent,width=3)
    elif ident=='details':
        title(im,b,ident)
        d=designs[b['detail_design_id']]
        paste(im,source_path(project,root,d['detail']),(0,133,540,467))
        paste(im,source_path(project,root,d['front']),(596,135,304,280))
        for j,line in enumerate(c['labels']):
            draw_text(im,line,(578,438+j*53),34,ink,width=360,bold=j==0,max_lines=1)
    elif ident=='designs':
        title(im,b,ident, size=44)
        count=len(b['designs']); cols=count if count<=4 else math.ceil(count/2); rows=1 if count<=4 else 2
        gap=16; width=(906-gap*(cols-1))//cols
        top=145 if rows==1 else 125; available=430 if rows==1 else 440
        height=(available-20*(rows-1))//rows
        cells=[]
        for i,d in enumerate(b['designs']):
            x=32+(i%cols)*(width+gap); y=top+(i//cols)*(height+20)
            image_h=min(300,height-48) if rows==1 else height-40
            paste(im,source_path(project,root,d['artwork']['50x60']),(x,y,width,image_h))
            label=d.get('short_name',d['name']) if count<=4 else f'Style {d["id"]}'
            draw_text(im,label,(x,y+image_h+12),32 if count<=4 else 30,ink,width=width,bold=True,max_lines=2 if count<=4 else 1,bottom=599)
            cells.append({'design_id':d['id'],'image_box':[x,y,width,image_h]})
        geometry={'design_ids':[d['id'] for d in b['designs']],'cells':cells}
    elif ident=='lifestyle':
        title(im,b,ident)
        for i,scene in enumerate(('living','bedroom')):
            x=i*490
            paste(im,scene_path(root,scene),(x,132,480,360))
            draw_text(im,c['labels'][i],(x+24,513),34,ink,width=438,bold=True,max_lines=1)
            wv,hv=b['scenes'][scene]['shown_size']
            draw_text(im,f'{wv} x {hv} in shown',(x+24,558),25,accent,width=438,max_lines=1)
    elif ident=='sizes':
        title(im,b,ident)
        scale=4.7; gap=16; total=sum(round(s[0]*scale) for s in SIZES)+3*gap; x=(970-total)//2
        boxes=[]; design=designs[b['size_design_id']]
        for width,height in SIZES:
            rw,rh=round(width*scale),round(height*scale); y=495-rh
            path=source_path(project,root,design['artwork'][f'{width}x{height}'])
            paste(im,path,(x,y,rw,rh))
            ImageDraw.Draw(im).rectangle((x,y,x+rw-1,494),outline=accent,width=2)
            label=f'{width} x {height}'
            font=face(34,True); tw=ImageDraw.Draw(im).textlength(label,font=font)
            ImageDraw.Draw(im).text((x+(rw-tw)/2,510),label,font=font,fill=ink)
            boxes.append({'size':[width,height],'box':[x,y,rw,rh]}); x+=rw+gap
        draw_text(im,c['footer'],(32,561),25,ink,width=906,max_lines=1)
        geometry={'pixels_per_inch':scale,'rectangles':boxes,'illustrated_design':design['id']}
    elif ident=='care':
        paste(im,scene_path(root,'care'),(0,0,970,600))
        ImageDraw.Draw(im).rectangle((620,0,969,599),fill=paper)
        draw_text(im,c['headline'],(650,46),43,ink,width=288,bold=True,serif=True,max_lines=3,bottom=245)
        y=285
        for line in c['labels']:
            ImageDraw.Draw(im).line((650,y-15,915,y-15),fill=accent,width=2)
            y=draw_text(im,line,(650,y),34,ink,width=288,bold=True,max_lines=2,bottom=588)+36
    return im,geometry


def compose_lean(root,project,ident):
    b=project['brief']; c=b['copy'][ident]; p=b['palette']; ink=p['ink']; paper=p['paper']; accent=p['accent']
    im=Image.new('RGB',(970,600),paper); geometry={}
    designs={d['id']:d for d in b['designs']}
    if ident in ('hero','gift'):
        paste(im,scene_path(root,ident),(0,0,970,600))
        ImageDraw.Draw(im).rectangle((0,0,334,599),fill=paper)
        ImageDraw.Draw(im).line((30,101,110,101),fill=accent,width=3)
        y=draw_text(im,c['headline'],(30,139),42,ink,width=280,serif=True,bold=True,max_lines=4,bottom=400)
        draw_text(im,c.get('subline',''),(30,y+30),36,ink,width=280,max_lines=3,bottom=570)
    elif ident=='details':
        title(im,b,ident,size=48,subtitle=False)
        d=designs[b['detail_design_id']]; path=source_path(project,root,d['front'])
        if b['product_mode'] == 'custom':
            paste_front(im,path,(30,112,380,407))
            draw_text(im,b['customization']['example_disclosure'],(30,547),30,ink,width=420,max_lines=1)
            for i,label in enumerate(c['selection_labels']):
                y=147+i*108
                ImageDraw.Draw(im).line((455,y-14,930,y-14),fill=accent,width=2)
                draw_text(im,label,(455,y),38,ink,width=485,bold=True,max_lines=1)
            draw_text(im,c['labels'][1],(455,524),36,ink,width=485,max_lines=2,bottom=595)
            return im,{'detail_source':'actual photo-layout example; not a physical macro',
                       'instruction_scope':'selection-only','design_id':d['id']}
        paste(im,path,(24,110,400,450))
        with Image.open(path) as opened:
            photo=ImageOps.exif_transpose(opened).convert('RGB')
            box=b.get('detail_crop',[.20,.64,.79,.98])
            crop=photo.crop(tuple(round(v*(photo.width if i%2==0 else photo.height)) for i,v in enumerate(box)))
            w.require(crop.width>=472 and crop.height>=300,'Detail crop needs sufficient source pixels')
            crop=ImageOps.contain(crop,(472,300),method=Image.Resampling.LANCZOS)
            im.paste(crop,(458+(472-crop.width)//2,163+(300-crop.height)//2))
        draw_text(im,c['labels'][0],(458,112),36,ink,width=480,bold=True,max_lines=1)
        draw_text(im,c['labels'][1],(458,490),36,ink,width=480,max_lines=2,bottom=590)
        geometry={'detail_source':'exact front crop; not a physical macro','normalized_crop':box}
    elif ident=='designs':
        title(im,b,ident,size=48,subtitle=False)
        count=len(b['designs']); cols=count if count<=4 else math.ceil(count/2); rows=1 if count<=4 else 2
        gap=16; width=(906-gap*(cols-1))//cols; image_h=300 if rows==1 else 180
        if b['product_mode']=='custom' and rows==2:
            image_h=170
        cells=[]
        for i,d in enumerate(b['designs']):
            custom=b['product_mode']=='custom'
            x=32+(i%cols)*(width+gap); y=(145 if rows==1 else 110)+(i//cols)*(220 if custom else 235)
            paste_front(im,source_path(project,root,d['front']),(x,y,width,image_h))
            label=d.get('short_name',d['name']) if count<=4 else f'Style {d["id"]}'
            if custom:
                n=d['photo_count']; label=f'{n} photo' if n==1 else f'{n} photos'
            draw_text(im,label,(x,y+image_h+10),36 if count<=4 else 32,ink,width=width,bold=True,max_lines=2 if count<=4 else 1,bottom=598)
            cells.append({'design_id':d['id'],'image_box':[x,y,width,image_h]})
        geometry={'design_ids':list(designs),'cells':cells}
        if b['product_mode']=='custom':
            draw_text(im,b['customization']['example_disclosure'],(32,560),30,ink,width=906,max_lines=1)
            geometry['photo_counts']=[d['photo_count'] for d in b['designs']]
    elif ident=='lifestyle':
        title(im,b,ident,size=48,subtitle=False)
        for i,scene in enumerate(('living','bedroom')):
            x=i*490
            paste(im,scene_path(root,scene),(x,108,480,360))
            draw_text(im,c['labels'][i],(x+22,487),38,ink,width=440,bold=True,max_lines=1)
            a,z=b['scenes'][scene]['shown_size']
            draw_text(im,f'{a} x {z} in',(x+22,540),36,accent,width=440,max_lines=1)
    elif ident=='sizes':
        title(im,b,ident,size=48,subtitle=False)
        scale=4.7; gap=16; x=(970-sum(round(s[0]*scale) for s in SIZES)-3*gap)//2; boxes=[]
        d=designs[b['size_design_id']]
        for a,z in SIZES:
            rw,rh=round(a*scale),round(z*scale); y=485-rh
            paste(im,source_path(project,root,d['artwork'][f'{a}x{z}']),(x,y,rw,rh))
            ImageDraw.Draw(im).rectangle((x,y,x+rw-1,484),outline=accent,width=2)
            for label,yy,sz in ((f'{a} x {z}',498,34),('in',544,34)):
                f=face(sz,True); tw=ImageDraw.Draw(im).textlength(label,font=f)
                ImageDraw.Draw(im).text((x+(rw-tw)/2,yy),label,font=f,fill=ink)
            boxes.append({'size':[a,z],'box':[x,y,rw,rh]}); x+=rw+gap
        geometry={'pixels_per_inch':scale,'rectangles':boxes,'illustrated_design':d['id']}
    elif ident=='care':
        paste(im,scene_path(root,'care'),(0,0,970,600))
        ImageDraw.Draw(im).rectangle((620,0,969,599),fill=paper)
        draw_text(im,c['headline'],(650,130),42,ink,width=288,bold=True,serif=True,max_lines=3,bottom=350)
        ImageDraw.Draw(im).line((650,350,920,350),fill=accent,width=2)
        draw_text(im,c['subline'],(650,390),36,ink,width=288,max_lines=3,bottom=590)
    return im,geometry


def render(root,full=False):
    project=load(root); brief=project['brief']; records={}; assets=root/'assets'; assets.mkdir(exist_ok=True)
    for ident in MODULES:
        image,geometry=compose(root,project,ident)
        target=assets/FILES[ident]; image.save(target,optimize=True)
        records[ident]={'file':'assets/'+target.name,'sha256':w.digest(target),'pixels':list(image.size),'bytes':target.stat().st_size,'geometry':geometry}
    files=write_extras(root,brief) if full else {}
    manifest={'fingerprint':project['fingerprint'],'modules':records,
              'scene_hashes':{name:w.digest(scene_path(root,name)) for name in SCENES},
              'renderer_sha256':w.digest(Path(__file__)), 'files':files}
    if brief.get('layout')=='visual-v4':
        manifest['visual_renderer_sha256']=w.digest(Path(visual.__file__))
    w.write(root/'render-manifest.json',manifest)
    return check(root)


def write_extras(root,brief):
    w.write(root/'copy.json',brief['copy'])
    lines=['# '+brief['brand']+' / Seven-image A+ copy','']
    for ident in MODULES:
        c=brief['copy'][ident]
        lines += ['## '+ident,'',c['headline'],'',c.get('subline',''),'',' / '.join(c.get('labels',[])),'',c.get('footer',''),'','Alt: '+c['alt'],'']
    (root/'english-copy.md').write_text('\n'.join(lines),encoding='utf-8')
    with (root/'design-map.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f); writer.writerow(['design_id','name','size_inches','parent_key','brand'])
        for d in brief['designs']:
            for a,z in SIZES:
                writer.writerow([d['id'],d['name'],f'{a} x {z}',brief['parent_key'],brief['brand']])
    sections=''.join(f'<section><img src="assets/{FILES[i]}" alt="{html.escape(brief["copy"][i]["alt"],quote=True)}"></section>' for i in MODULES)
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(brief['brand'])+' A+ preview</title><style>*{box-sizing:border-box}body{margin:0;background:#ebefed;color:#233c33;font:16px Arial,sans-serif}header{max-width:970px;margin:20px auto;padding:0 16px}h1{font-size:24px}main{max-width:970px;margin:auto;background:white}section{margin:0 0 12px}img{width:100%;height:auto;display:block}p{line-height:1.5}</style><header><h1>'+html.escape(brief['brand'])+' | A+ design preview</h1><p>Seven images. Four sizes. '+str(len(brief['designs']))+' prints. Local design draft.</p></header><main>'+sections+'</main></html>'
    (root/'preview.html').write_text(page,encoding='utf-8')
    return {name:w.digest(root/name) for name in ['copy.json','english-copy.md','design-map.csv','preview.html']}


def check(root):
    project=load(root); b=project['brief']; errors=[]; pending=[]
    manifest=w.read(root/'render-manifest.json') if (root/'render-manifest.json').exists() else {}
    review=w.read(root/'review.json')
    if manifest.get('fingerprint')!=project['fingerprint']:
        errors.append('Missing/stale render manifest')
    if manifest.get('renderer_sha256')!=w.digest(Path(__file__)):
        errors.append('Renderer changed; render and review again')
    if b.get('layout')=='visual-v4' and manifest.get('visual_renderer_sha256')!=w.digest(Path(visual.__file__)):
        errors.append('Visual renderer changed; render and review again')
    for ident in SCENES:
        try:
            if w.digest(scene_path(root,ident))!=manifest.get('scene_hashes',{}).get(ident):
                errors.append(f'{ident}: scene changed after rendering')
        except (ValueError,OSError):
            errors.append(f'{ident}: missing/changed scene')
    if {p.name for p in (root/'assets').glob('*.png')} != set(FILES.values()):
        errors.append('Require exactly seven final PNGs')
    for ident in MODULES:
        record=manifest.get('modules',{}).get(ident,{})
        path=root/'assets'/FILES[ident]
        if not path.exists() or w.digest(path)!=record.get('sha256') or w.picture(path)!=[970,600]:
            errors.append(f'{ident}: missing/changed/wrong size')
        elif path.stat().st_size>2000000:
            errors.append(f'{ident}: exceeds internal 2MB target')
        rv=review.get('modules',{}).get(ident,{})
        if review.get('project_fingerprint')!=project['fingerprint'] or rv.get('sha256')!=record.get('sha256') or not all(rv.get(k) is True for k in w.REVIEW_KEYS) or not rv.get('notes'):
            pending.append(f'{ident}: visual review required')
    for name in manifest.get('files',{}):
        if not (root/name).exists() or w.digest(root/name)!=manifest.get('files',{}).get(name):
            errors.append(f'{name}: missing/changed')
    found=manifest.get('modules',{}).get('designs',{}).get('geometry',{}).get('design_ids',[])
    if found != [d['id'] for d in b['designs']]:
        errors.append('Parent design coverage mismatch')
    if b['product_mode']=='custom':
        counts=manifest.get('modules',{}).get('designs',{}).get('geometry',{}).get('photo_counts',[])
        if counts != [d['photo_count'] for d in b['designs']]:
            errors.append('Custom photo-count coverage mismatch')
        if not b['customization'].get('workflow_verified'):
            pending.append('Actual Amazon customization UI not verified; images contain selection guidance only')
    pending.append('Confirm actual Seller Central module slots and child ASIN applicability; seven files do not establish seven available Basic slots')
    result={'status':'invalid' if errors else 'design_draft','errors':errors,'pending':pending,'brand':b['brand'],'parent_key':b['parent_key'],'image_count':7,'dimensions':[970,600],'checked_at':w.now()}
    w.write(root/'checks.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return result


def package(root):
    render(root,full=True)
    result=check(root); w.require(not result['errors'],'Fix structural errors before packaging')
    archive_path=root/'aplus-seven-design-draft.zip'
    files=['campaign.json','copy.json','english-copy.md','design-map.csv','preview.html','render-manifest.json','review.json','checks.json','scene-brief.json']
    files+=['assets/'+FILES[i] for i in MODULES]
    files+=['generation/jobs.jsonl','generation/generation-state.json']
    if (root/'delivery-notes.md').exists():
        files.append('delivery-notes.md')
    with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in files:
            archive.write(root/name,name)
    with zipfile.ZipFile(archive_path) as archive:
        w.require(archive.testzip() is None,'ZIP integrity failure')
    print(archive_path)


def export(root,out):
    result=check(root)
    w.require(not result['errors'] and not any('visual review required' in v for v in result['pending']),'Complete technical and visual review before export')
    out=Path(out).resolve()
    w.require(not out.exists() or not any(out.iterdir()),'Use a new empty delivery folder')
    out.mkdir(parents=True,exist_ok=True)
    for name in FILES.values():
        shutil.copy2(root/'assets'/name,out/name)
        w.require(w.digest(root/'assets'/name)==w.digest(out/name),'Export hash mismatch')
    print(f'Exported exactly seven PNGs: {out}')


def main():
    parser=argparse.ArgumentParser(description=__doc__); subs=parser.add_subparsers(dest='command',required=True)
    prep=subs.add_parser('prepare'); prep.add_argument('--brief',type=Path,required=True); prep.add_argument('--out',type=Path,required=True)
    prep.add_argument('--restore-legacy-layout',action='store_true',help='Historical restoration only; new campaigns use visual-v4')
    exp=subs.add_parser('export'); exp.add_argument('--project',type=Path,required=True); exp.add_argument('--out',type=Path,required=True)
    for name in ('generate','render','check','package'):
        sub=subs.add_parser(name); sub.add_argument('--project',type=Path,required=True)
        if name=='render':
            sub.add_argument('--full',action='store_true',help='Optional copy/HTML artifacts, not the default delivery')
        if name=='generate':
            sub.add_argument('--module',choices=SCENES); sub.add_argument('--execute',action='store_true'); sub.add_argument('--retry-note')
            sub.add_argument('--concurrency',type=int,choices=(1,2),default=2)
    args=parser.parse_args()
    try:
        if args.command=='prepare':
            prepare(args.brief,args.out,args.restore_legacy_layout)
        elif args.command=='generate':
            load(args.project.resolve()); w.generate(args.project.resolve()/'generation',args.module,args.execute,args.retry_note,args.concurrency)
        elif args.command=='render':
            result=render(args.project.resolve(),args.full)
            return 1 if result['errors'] else 0
        elif args.command=='export':
            export(args.project.resolve(),args.out)
        else:
            result=globals()[args.command](args.project.resolve())
            if isinstance(result,dict) and result.get('errors'):
                return 1
        return 0
    except (ValueError,OSError,KeyError,TypeError) as exc:
        print(f'Campaign stopped: {exc}',file=sys.stderr); return 1


if __name__=='__main__':
    raise SystemExit(main())
