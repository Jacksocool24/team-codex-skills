"""Seven-module renderer based on the approved three-image visual pilot."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
import math

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

SCALE = 2
SIZES = [[30,40],[40,50],[50,60],[60,80]]
DEFAULT_TEXT = {
    'hero': {'box':[100,25,345,170], 'headline_size':40, 'subline_size':30, 'gap':14},
    'gift': {'box':[40,30,410,205], 'headline_size':40, 'subline_size':30, 'gap':16},
    'care': {'box':[622,35,310,220], 'headline_size':40, 'subline_size':30, 'gap':16},
}


@lru_cache(maxsize=32)
def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/'+('arialbd.ttf' if bold else 'arial.ttf'),round(size*SCALE))


def text_spec(brief, ident):
    spec=dict(DEFAULT_TEXT[ident])
    spec.update(brief.get('text_layout',{}).get(ident,{}))
    return spec


class Canvas:
    def __init__(self, brief):
        self.brief=brief
        self.ink=brief['palette']['ink']
        self.accent=brief['palette']['accent']
        self.image=Image.new('RGB',(970*SCALE,600*SCALE),'white')
        self.text_boxes=[]

    def text(self,value,xy,size=36,width=900,bold=False,color=None,center=False,bottom=600,max_lines=3):
        draw=ImageDraw.Draw(self.image); f=font(size,bold); lines=[]
        for paragraph in value.split('\n'):
            current=''
            for word in paragraph.split():
                proposed=(current+' '+word).strip()
                if draw.textlength(proposed,font=f)>width*SCALE and current:
                    lines.append(current); current=word
                else:
                    current=proposed
            if current:
                lines.append(current)
        if len(lines)>max_lines:
            raise ValueError(f'Text too long for visual-v4: {value}')
        x,y=xy
        for row in lines:
            tw=draw.textlength(row,font=f)/SCALE
            if tw>width:
                raise ValueError(f'Text exceeds width: {row}; shorten the copy')
            px=x+(width-tw)/2 if center else x
            box=draw.textbbox((round(px*SCALE),round(y*SCALE)),row,font=f,anchor='lt')
            if box[0]<0 or box[1]<0 or box[2]>970*SCALE or box[3]>bottom*SCALE:
                raise ValueError(f'Text exceeds region: {row}')
            draw.text((round(px*SCALE),round(y*SCALE)),row,font=f,fill=color or self.ink,anchor='lt')
            self.text_boxes.append({'text':row,'box':[v/SCALE for v in box],'font_px':size})
            y+=size*1.18
        return y

    def line(self,points,color=None,width=1):
        ImageDraw.Draw(self.image).line([(round(x*SCALE),round(y*SCALE)) for x,y in points],fill=color or self.accent,width=round(width*SCALE))

    def place(self,source,box,cover=False):
        if isinstance(source,(str,Path)):
            with Image.open(source) as opened:
                source=ImageOps.exif_transpose(opened).convert('RGB')
        x,y,width,height=box
        ratio=max(width/source.width,height/source.height) if cover else min(width/source.width,height/source.height)
        if ratio>1.01:
            raise ValueError('Source too small for final pixels; supply a larger source')
        fn=ImageOps.fit if cover else ImageOps.contain
        resized=fn(source,(round(width*SCALE),round(height*SCALE)),method=Image.Resampling.LANCZOS)
        px=round(x*SCALE)+(round(width*SCALE)-resized.width)//2
        py=round(y*SCALE)+(round(height*SCALE)-resized.height)//2
        self.image.paste(resized,(px,py))
        return [px/SCALE,py/SCALE,resized.width/SCALE,resized.height/SCALE]

    def finish(self,geometry):
        geometry['text_boxes']=self.text_boxes
        geometry['layout']='visual-v4'
        return self.image.resize((970,600),Image.Resampling.LANCZOS),geometry


def front(path):
    with Image.open(path) as opened:
        photo=ImageOps.exif_transpose(opened).convert('RGB')
    mask=ImageChops.difference(photo,Image.new('RGB',photo.size,'white')).convert('L').point(lambda v:255 if v>20 else 0)
    bounds=mask.getbbox()
    if not bounds:
        raise ValueError('Front source has no visible product')
    l,t,r,b=bounds
    return photo.crop((max(0,l-4),max(0,t-4),min(photo.width,r+4),min(photo.height,b+4)))


def scene_text(page, ident):
    spec=text_spec(page.brief,ident); x,y,width,height=spec['box']
    copy=page.brief['copy'][ident]
    y=page.text(copy['headline'],(x,y),spec['headline_size'],width,bold=True,bottom=y+height,max_lines=3)
    if copy.get('subline'):
        page.text(copy['subline'],(x,y+spec['gap']),spec['subline_size'],width,bottom=spec['box'][1]+height,max_lines=2)
    return spec


def validate(brief):
    for ident in DEFAULT_TEXT:
        spec=text_spec(brief,ident)
        box=spec['box']
        if not isinstance(box,list) or len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box):
            raise ValueError('text_layout box must contain four finite numbers')
        x,y,width,height=box
        if min(x,y)<0 or min(width,height)<=0 or x+width>970 or y+height>600:
            raise ValueError('text_layout box outside 970x600 canvas')
        if not 36<=spec['headline_size']<=56 or not 28<=spec['subline_size']<=40 or not 0<=spec['gap']<=40:
            raise ValueError('Keep readable visual-v4 type sizes; shorten long copy')
        scene_text(Canvas(brief),ident)
    box=brief.get('detail_crop')
    if box is not None and (not isinstance(box,list) or len(box)!=4 or
        not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box) or
        not (0<=box[0]<box[2]<=1 and 0<=box[1]<box[3]<=1)):
        raise ValueError('detail_crop must be a valid normalized rectangle on the trimmed front')
    evidence=brief.get('detail_photo')
    if evidence and not (evidence.get('confirmed') is True and evidence.get('source') and evidence.get('path')):
        raise ValueError('Physical detail photo needs confirmed provenance')


def compose(brief,sources,scenes,ident):
    page=Canvas(brief); copy=brief['copy'][ident]; custom=brief['product_mode']=='custom'
    designs=brief['designs']; geometry={}
    if ident in DEFAULT_TEXT:
        page.place(scenes[ident],(0,0,970,600),cover=True)
        geometry['text_layout']=scene_text(page,ident)
        geometry['full_bleed']=True
    elif ident=='details':
        design=next(d for d in designs if d['id']==brief['detail_design_id'])
        photo=front(sources[design['front']])
        if custom:
            page.text(copy['headline'],(30,28),44,910,bold=True,max_lines=1,bottom=87)
            page.place(photo,(30,112,380,407))
            page.text(brief['customization']['example_disclosure'],(30,558),28,910,max_lines=1)
            for i,label in enumerate(copy['selection_labels']):
                y=145+i*105
                page.line([(455,y-15),(935,y-15)],width=2)
                page.text(label,(455,y),36,480,bold=True,max_lines=1)
            page.text(copy['labels'][1],(455,488),32,480,max_lines=2,bottom=550)
            geometry.update(detail_source='photo-layout example, not physical macro',instruction_scope='selection-only',design_id=design['id'])
        else:
            page.text(copy['headline'],(36,37),44,330,bold=True,max_lines=2,bottom=143)
            page.text(copy['labels'][1],(38,155),34,330,max_lines=2,bottom=220)
            x,y,width,height=page.place(photo,(67,226,242,290))
            if brief.get('detail_photo'):
                page.place(sources[brief['detail_photo']['path']],(380,0,590,546))
                label='Fabric detail'
                geometry['detail_source']='confirmed physical photo'
            else:
                if brief.get('detail_crop'):
                    box=tuple(round(v*(photo.width if i%2==0 else photo.height)) for i,v in enumerate(brief['detail_crop']))
                else:
                    ch=round(photo.height*.52); cw=min(photo.width,round(ch*590/546))
                    box=(photo.width-cw,photo.height-ch,photo.width,photo.height)
                page.place(photo.crop(box),(380,0,590,546))
                selection=(x+box[0]/photo.width*width,y+box[1]/photo.height*height,
                           x+box[2]/photo.width*width,y+box[3]/photo.height*height)
                ImageDraw.Draw(page.image).rectangle(tuple(round(v*SCALE) for v in selection),outline=page.accent,width=2*SCALE)
                cy=(selection[1]+selection[3])/2
                page.line([(selection[2],cy),(345,cy),(368,350)],width=1.5)
                label='Enlarged print detail'
                geometry.update(detail_source='exact front pixels, not physical macro',crop_px=box,selection=selection)
            page.text('Full blanket',(38,552),28,320,max_lines=1)
            page.text(label,(405,561),30,540,max_lines=1)
    elif ident=='designs':
        page.text(copy['headline'],(26,30),44,915,bold=True,max_lines=1,bottom=87)
        count=len(designs); rows=1 if count<=4 else 2; cols=count if rows==1 else math.ceil(count/2)
        if rows==1 and copy.get('subline'):
            page.text(copy['subline'],(28,92),28,910,max_lines=1,bottom=132)
        gap=16; width=(926-gap*(cols-1))/cols; cells=[]
        counts=Counter(d.get('photo_count') for d in designs) if custom else Counter()
        occurrences=Counter()
        for i,design in enumerate(designs):
            row=i//cols; in_row=min(cols,count-row*cols)
            start=(970-(in_row*width+(in_row-1)*gap))/2
            x=start+(i%cols)*(width+gap); y=159 if rows==1 else 96+row*230
            image_h=273 if rows==1 else 160
            page.place(front(sources[design['front']]),(x,y,width,image_h))
            if rows==1:
                page.line([(x+width/2-17,454),(x+width/2+17,454)],width=3)
            label=design.get('short_name',design['name']) if count<=4 else f'Style {design["id"]}'
            if custom:
                n=design['photo_count']; label=f'{n} photo' if n==1 else f'{n} photos'
                occurrences[n]+=1
            yy=473 if rows==1 else y+image_h+10
            page.text(label,(x-2,yy),36 if rows==1 else 30,width+4,bold=True,center=True,max_lines=2 if rows==1 else 1,bottom=550)
            if custom and counts[n]>1:
                suffix=chr(64+occurrences[n])
                page.text(f'Layout {suffix}',(x,yy+38),24,width,center=True,max_lines=1,bottom=550)
            cells.append({'design_id':design['id'],'image_box':[x,y,width,image_h]})
        geometry.update(design_ids=[d['id'] for d in designs],cells=cells)
        if custom:
            page.text(brief['customization']['example_disclosure'],(28,565),28,910,max_lines=1)
            geometry['photo_counts']=[d['photo_count'] for d in designs]
    elif ident=='lifestyle':
        page.text(copy['headline'],(26,28),44,915,bold=True,max_lines=1,bottom=90)
        for i,scene in enumerate(('living','bedroom')):
            x=i*490
            page.place(scenes[scene],(x,108,480,360))
            page.text(copy['labels'][i],(x+22,487),36,440,bold=True,max_lines=1)
            a,b=brief['scenes'][scene]['shown_size']
            page.text(f'{a} x {b} in',(x+22,540),34,440,color=page.accent,max_lines=1)
    elif ident=='sizes':
        page.text(copy['headline'],(26,28),44,915,bold=True,max_lines=1,bottom=90)
        scale=4.7; gap=16; x=(970-sum(round(s[0]*scale) for s in SIZES)-3*gap)/2; boxes=[]
        design=next(d for d in designs if d['id']==brief['size_design_id'])
        for a,b in SIZES:
            width,height=round(a*scale),round(b*scale); y=485-height
            page.place(sources[design['artwork'][f'{a}x{b}']],(x,y,width,height))
            ImageDraw.Draw(page.image).rectangle(tuple(round(v*SCALE) for v in (x,y,x+width,485)),outline=page.accent,width=2*SCALE)
            page.text(f'{a} x {b}',(x,500),34,width,bold=True,center=True,max_lines=1)
            page.text('in',(x,546),32,width,center=True,max_lines=1)
            boxes.append({'size':[a,b],'box':[x,y,width,height]}); x+=width+gap
        geometry.update(pixels_per_inch=scale,rectangles=boxes,illustrated_design=design['id'])
    else:
        raise ValueError(f'Unknown visual module: {ident}')
    return page.finish(geometry)
