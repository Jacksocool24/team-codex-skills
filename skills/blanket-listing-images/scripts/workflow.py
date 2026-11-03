"""Reusable blanket listing workflow; API requests are delegated to one shared engine."""
import argparse
from fractions import Fraction
from html import escape
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import types
import zipfile

from PIL import Image, ImageDraw, ImageOps
import listing_set

HERE = Path(__file__).resolve().parent
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp'}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def save_job(path, job):
    path.write_text(json.dumps(job, ensure_ascii=False)+'\n', encoding='utf-8')


def generate(path, folder):
    result = subprocess.run([sys.executable, str(HERE/'generate.py'), '--input', str(path),
                             '--out-dir', str(folder), '--concurrency', '2', '--skip-existing'])
    if result.returncode:
        raise RuntimeError('Generation stopped. Inspect local manifests and provider history before resuming missing images.')


def natural(path):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', str(path))]


def plan(args):
    source, output = args.references.resolve(), args.output.resolve()
    if not (math.isfinite(args.width) and math.isfinite(args.height) and 0 < args.width <= 72 and 0 < args.height <= 120):
        raise ValueError('Blanket dimensions must be positive, at most 72 by 120 inches.')
    if source.is_dir() and output.is_relative_to(source):
        raise ValueError('Output must be outside the reference folder.')
    sources = [source] if source.is_file() and source.suffix.lower() in EXTENSIONS else (
        sorted((p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS), key=natural) if source.is_dir() else [])
    if not sources:
        raise ValueError('No supported reference images.')
    records = []
    for index, path in enumerate(sources, 1):
        with Image.open(path) as im:
            im.verify()
        records.append({'folder':f'set-{index:03d}', 'title':path.stem, 'source':str(path), 'sha256':listing_set.fingerprint(path)})
    return {'schema_version':1, 'skill':'blanket-listing-images', 'version':'1.1',
            'width':args.width, 'height':args.height, 'theme':args.theme.strip(), 'palette':args.palette.strip(),
            'packaging':args.packaging.strip() or 'unknown', 'sets':records}


def master_for(record, folder, batch):
    source = Path(record['source'])
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / ('source-reference'+source.suffix.lower())
    if original.exists():
        if listing_set.fingerprint(original) != record['sha256']:
            raise ValueError('Saved source changed; use a new output folder.')
    else:
        shutil.copyfile(source, original)
    master = folder/'adapted-artwork.png'
    with Image.open(source) as im:
        oriented = ImageOps.exif_transpose(im)
        size = oriented.size
        native_format = im.format
        needs_adaptation = abs(size[0]/size[1]-batch['width']/batch['height']) > .002 or bool(batch['theme'] or batch['palette'])
        if not needs_adaptation and not master.exists():
            if native_format == 'PNG' and im.getexif().get(274, 1) == 1:
                shutil.copyfile(source, master)
            else:
                oriented.convert('RGB').save(master)
    if needs_adaptation:
        ratio = Fraction(str(batch['width']))/Fraction(str(batch['height']))
        prompt = (HERE.parent/'references/print-master-prompt.txt').read_text(encoding='utf-8').format(
            theme_and_subjects=batch['theme'] or 'faithfully preserve the supplied reference subjects, central figures and theme',
            style_and_palette=batch['palette'] or 'match the supplied reference style and palette',
            width_inches=batch['width'], height_inches=batch['height'], width_ratio=ratio.numerator, height_ratio=ratio.denominator)
        prompt += (f' Recompose the supplied reference into exactly {ratio.numerator}:{ratio.denominator} width:height. '
                   'Keep complete decorative borders when present and all important motifs inside the canvas. '
                   'Do not stretch, squash, mirror or duplicate central figures. Redistribute background ornaments naturally; '
                   'no blank padding. Output only flat full-bleed artwork, with no product mockup, folds, words or measurements.')
        job_path=folder/'artwork-job.jsonl'
        if not job_path.exists():
            save_job(job_path, {'prompt':prompt,'out':master.name,'images':[str(original)],'size':'auto','quality':'high'})
        generate(job_path, folder)
    with Image.open(master) as im:
        actual = im.size
        im.verify()
    if abs(actual[0]/actual[1]-batch['width']/batch['height']) > .002:
        raise ValueError(f'Adapted artwork has wrong aspect ratio: {actual}; review before continuing.')
    adaptation = {'source':str(source),'source_sha256':record['sha256'], 'master_sha256':listing_set.fingerprint(master),
                  'pixels':list(actual), 'method':'AI recomposition' if needs_adaptation else 'source preserved or format converted without resizing',
                  'production_ready':False}
    if (folder/'source-adaptation.json').exists() and read_json(folder/'source-adaptation.json') != adaptation:
        raise ValueError('Adapted artwork changed since preparation; use a new set.')
    save_json(folder/'source-adaptation.json', adaptation)
    return master


def finish_set(folder):
    config = read_json(folder/'product.json')
    if listing_set.fingerprint(folder/'09-factory-artwork.png') != config['artwork_sha256']:
        raise ValueError('Factory artwork no longer matches the selected master.')
    listing_set.finish(folder, config, read_json(folder/'all-prompts.json'))


def run(args):
    batch = plan(args)
    if args.dry_run:
        print(json.dumps({'dry_run':True,'sets':len(batch['sets']),'deliverables':len(batch['sets'])*9,
                          'size_inches':[args.width,args.height], 'sources':[r['source'] for r in batch['sets']]}, ensure_ascii=True))
        return
    root = args.output.resolve()
    saved = root/'batch-plan.json'
    if saved.exists():
        if not args.resume:
            raise ValueError('Batch already exists. Use --resume only after checking previous outcomes.')
        previous_batch = read_json(saved)
        comparable = dict(previous_batch)
        if comparable.get('version') in ('1.0', '1.1'):
            comparable['version'] = batch['version']
        if comparable != batch:
            raise ValueError('Sources or product parameters changed; choose a new output directory.')
        batch = previous_batch
    elif root.exists() and any(root.iterdir()):
        raise ValueError('Output directory is not empty and has no matching batch plan.')
    root.mkdir(parents=True,exist_ok=True)
    save_json(saved,batch)
    for index,record in enumerate(batch['sets'],1):
        print(f"SET {index}/{len(batch['sets'])}: {record['title']}",flush=True)
        folder = root/record['folder']
        master = master_for(record,folder,batch)
        if not (folder/'product.json').exists():
            _,config,_ = listing_set.prepare(types.SimpleNamespace(artwork=master,out_dir=folder,
                width=batch['width'],height=batch['height'],packaging=batch['packaging']))
            save_json(folder/'workflow-settings.json',{k:v for k,v in batch.items() if k!='sets'})
            save_json(folder/'prompt-preparation.json',{'skill_version':'1.1'})
        else:
            config=read_json(folder/'product.json')
            if config['artwork_sha256'] != listing_set.fingerprint(master):
                raise ValueError('Master changed; do not combine old photos with new artwork.')
        generate(folder/'generation-jobs.jsonl',folder)
        finish_set(folder)
        print(f'SET COMPLETE: {index}',flush=True)
    summarize(root)


def summarize(root):
    batch=read_json(root/'batch-plan.json')
    records=[]
    for record in batch['sets']:
        folder=root/record['folder']
        notes=read_json(folder/'delivery-notes.json')
        config=read_json(folder/'product.json')
        if len(notes['images'])!=9 or len(set(notes['images']))!=9:
            raise ValueError('Expected nine unique deliverables per set.')
        for name in notes['images']:
            if Path(name).name!=name:
                raise ValueError('Invalid deliverable path')
            with Image.open(folder/name) as im: im.verify()
        if listing_set.fingerprint(folder/'09-factory-artwork.png') != config['artwork_sha256']:
            raise ValueError('Factory artwork changed')
        records.append({**record,'images':notes['images'],'master_pixels':config['master_pixels']})
    count=len(records)
    cols=min(4,count);cell=320
    overview=Image.new('RGB',(cols*cell,100+math.ceil(count/cols)*385),'#f4f5f3')
    draw=ImageDraw.Draw(overview)
    draw.text((15,15),f'{count}款毛毯 · {count*9}张图片',font=listing_set.font(26,True),fill='#283c31')
    draw.text((15,58),f"{batch['width']:g} × {batch['height']:g} 英寸",font=listing_set.font(22,True),fill='#526156')
    cards=[]
    for index,record in enumerate(records):
        folder=root/record['folder']
        with Image.open(folder/record['images'][0]) as im:
            thumb=ImageOps.contain(im.convert('RGB'),(300,310),Image.Resampling.LANCZOS)
        x=10+(index%cols)*cell;y=100+(index//cols)*385
        overview.paste(thumb,(x+(300-thumb.width)//2,y))
        title=f"{index+1:02d} {record['title']}"
        display=title if len(title)<=19 else title[:18]+'…'
        draw.text((x,y+320),display,font=listing_set.font(20,True),fill='#283c31')
        name=record['folder']
        cards.append(f'<article><h2>{escape(title)}</h2><a href="{name}/gallery.html"><img src="{name}/listing-contact-sheet.jpg" alt="{escape(title)}"></a><p><a href="{name}/gallery.html">查看九张大图</a> · <a href="{name}/listing-set.zip" download>下载本款套装</a></p></article>')
    overview.save(root/'all-designs-overview.jpg',quality=94,subsampling=0)
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>毛毯商品图套装</title><style>*{box-sizing:border-box}body{margin:0;background:#f4f5f3;color:#283c31;font:16px/1.6 "Microsoft YaHei",sans-serif;letter-spacing:0}header,main,footer{max-width:1500px;margin:auto;padding:24px}h1{font-size:28px}h2{font-size:21px;overflow-wrap:anywhere}main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}img{width:100%;height:auto}a{color:#23603b}article{min-width:0}@media(max-width:720px){main{grid-template-columns:1fr}}</style>'''
    page+=f'<header><h1>成品毛毯商品图套装</h1><p>{count}款 · {count*9}张 · {batch["width"]:g} × {batch["height"]:g} 英寸</p><a href="all-listing-sets.zip" download>下载全部套装</a></header><main>'+''.join(cards)
    page+='</main><footer>商品图为AI效果示例；包装、洗护与印刷规格需按实物核实。</footer></html>'
    (root/'index.html').write_text(page,encoding='utf-8')
    save_json(root/'batch-inventory.json',records)
    with zipfile.ZipFile(root/'all-listing-sets.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for record in records:
            with zipfile.ZipFile(root/record['folder']/'listing-set.zip') as source:
                if source.testzip(): raise ValueError('Corrupt archive')
                for name in source.namelist():
                    data=source.read(name)
                    if name=='gallery.html':
                        data=data.decode('utf-8').replace('<a href="listing-set.zip" download>下载完整套装与提示词</a>','<a href="../index.html">返回总览</a>').encode('utf-8')
                    archive.writestr(record['folder']+'/'+name,data)
        archive_page=page.replace('<a href="all-listing-sets.zip" download>下载全部套装</a>','')
        for record in records:
            archive_page=archive_page.replace(f' · <a href="{record["folder"]}/listing-set.zip" download>下载本款套装</a>','')
        archive.writestr('index.html',archive_page.encode('utf-8'))
        for name in ['all-designs-overview.jpg','batch-inventory.json']:
            archive.write(root/name,name)
    print(f'Completed {count} sets, {count*9} images. Gallery: {root / "index.html"}',flush=True)


def select(folder,slot,name):
    if Path(name).name!=name or not name.endswith('.png'):
        raise ValueError('Select a PNG basename inside this set.')
    with Image.open(folder/name) as im: im.verify()
    path=folder/'selected-images.json'
    selected=read_json(path) if path.exists() else {}
    selected[slot]=name
    save_json(path,selected)
    finish_set(folder)


def revise(args):
    folder=args.folder.resolve()
    read_json(folder/'product.json')
    reference=(args.reference or folder/('gift-top-reference.png' if args.slot=='08' else '09-factory-artwork.png')).resolve()
    with Image.open(reference) as im: im.verify()
    version=2
    while (folder/f'{args.slot}-revision-v{version}.png').exists() or (folder/f'revision-{args.slot}-v{version}.jsonl').exists():
        version+=1
    job={'prompt':args.prompt_file.read_text(encoding='utf-8-sig'),'out':f'{args.slot}-revision-v{version}.png',
         'images':[str(reference)],'size':'1024x1024','quality':'high'}
    path=folder/f'revision-{args.slot}-v{version}.jsonl'
    save_job(path,job)
    generate(path,folder)
    print(f"Review before selecting: {folder / job['out']}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    run_parser=commands.add_parser('run')
    run_parser.add_argument('--references',type=Path,required=True)
    run_parser.add_argument('--output',type=Path,required=True)
    run_parser.add_argument('--width',type=float,default=50)
    run_parser.add_argument('--height',type=float,default=60)
    run_parser.add_argument('--theme',default='')
    run_parser.add_argument('--palette',default='')
    run_parser.add_argument('--packaging',default='unknown')
    run_parser.add_argument('--resume',action='store_true')
    run_parser.add_argument('--dry-run',action='store_true')
    commands.add_parser('summarize').add_argument('--output',type=Path,required=True)
    commands.add_parser('finish').add_argument('--folder',type=Path,required=True)
    for command in ['revise','select']:
        sub=commands.add_parser(command)
        sub.add_argument('--folder',type=Path,required=True)
        sub.add_argument('--slot',choices=[f'{i:02d}' for i in range(1,9)],required=True)
        if command=='revise':
            sub.add_argument('--prompt-file',type=Path,required=True)
            sub.add_argument('--reference',type=Path)
        else:
            sub.add_argument('--image',required=True)
    args=parser.parse_args()
    if args.command=='run': run(args)
    elif args.command=='summarize': summarize(args.output.resolve())
    elif args.command=='finish': finish_set(args.folder.resolve())
    elif args.command=='revise': revise(args)
    else: select(args.folder.resolve(),args.slot,args.image)


if __name__=='__main__':
    main()
