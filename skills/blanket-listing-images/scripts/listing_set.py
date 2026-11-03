"""Prepare, generate and package eight listing images plus one unchanged print master."""

import argparse
import hashlib
from html import escape
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageChops
from generate import MODEL

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE.parent / "references/listing-prompts.json"
NAMES = ["白底正面", "尺寸图", "沙发场景", "卧室场景", "人物使用", "面料细节", "机洗展示", "礼品展示", "工厂印花原图"]


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scene_scale(width, height):
    """Declare staging assumptions, not measured specifications of the user's furniture."""
    back=min(24.,height*0.4)
    seat=min(24.,height-back)
    front=min(16.,height-back-seat)
    folds=height-back-seat-front
    folded_width=width/math.ceil(width/16.)
    values={"blanket_inches":[width,height],"sofa":{"outer_width":84,"usable_width":72,"seat_depth":24,"back_height":24,"seat_height":18,"width_fraction":width/72,"back_run":back,"seat_run":seat,"front_drop":front,"folded_length":folds},"bed":{"width":60,"length":80,"width_fraction":width/60,"length_fraction":height/80,"side_margin_each":max(0,(60-width)/2),"uncovered_head_length":max(0,80-height)},"person":{"height":66,"seated_lap_to_ankle_path":40,"blanket_length_fraction_of_height":height/66},"washer":{"width":27,"height":38,"door_opening":18,"adult_height":66,"gathered_width":folded_width}}
    prompts={
        "sofa_scale":f"Staging dimensions: sofa overall width 84 inches, usable seating width 72 inches, seat depth 24 inches, visible back height 24 inches and seat height 18 inches. Blanket width is {width/72:.1%} of usable seating width; centered placement leaves {(72-width)/2:g} inches of uncovered seating on each side. Allocate its {height:g}-inch length as {back:g} inches along the back, {seat:g} inches along the seat, {front:g} inches down the front and {folds:g} inches consumed in folds. Do not duplicate length between these surfaces; the front edge stays above the floor.",
        "bed_scale":f"Staging mattress is exactly 60 inches wide and 80 inches long. The blanket covers {width/60:.1%} of mattress width and {height/80:.1%} of mattress length before folds. Center it widthwise with {max(0,(60-width)/2):g} inches of exposed white bedding on each side and place its foot edge at the mattress foot, leaving {max(0,80-height):g} inches uncovered toward the head. Shallow folds reduce visible coverage; never enlarge the blanket to compensate.",
        "person_scale":f"Use an adult of approximately 66 inches standing height. The blanket length of {height:g} inches is {height/66:.1%} of that height. The bent-body surface path from seated lap to ankles is approximately 40 inches. Allocate up to {min(height,40):g} inches along that path and gather the remaining {max(0,height-40):g} inches in visible loose folds; do not make the excess trail across the floor. Keep its true {width:g}-inch width gathered naturally around one person's lap rather than stretched across adjacent seats.",
        "wash_scale":f"Staging dimensions: front-loading washer 27 inches wide and 38 inches high, circular door opening about 18 inches in diameter; adult model approximately 66 inches tall. Gather the blanket's {width:g}-inch width into a loose band about {folded_width:g} inches wide so it fits through the door, keeping the full {height:g}-inch length accounted for between the loaded portion and supported folds outside. The apparent small bundle is created by folding, not by shrinking the textile or the print. Show a plausible single thin flannel blanket volume.",
    }
    return values,prompts


def prepare(args):
    source = args.artwork.resolve()
    with Image.open(source) as im:
        im.verify()
    with Image.open(source) as im:
        size = im.size
        if abs(size[0] / size[1] - args.width / args.height) > 0.002:
            raise ValueError("Artwork ratio differs from SKU. Recompose explicitly before preparing the set.")
        if im.format != "PNG":
            raise ValueError("Use a PNG master so the factory copy can retain its original bytes.")
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    config_path = out / "product.json"
    config = {"artwork": str(source), "artwork_sha256": fingerprint(source), "width_inches": args.width, "height_inches": args.height, "master_pixels": list(size), "reverse": "unconfirmed-front-only-details", "packaging": args.packaging, "wash_claim": "user-requested-machine-wash-scene; actual-care-label-not-verified", "colorfastness": "unverified-no-claim", "print_ready": False}
    if config_path.exists() and json.loads(config_path.read_text(encoding="utf-8")) != config:
        raise ValueError("This output folder belongs to different product settings. Choose a new folder.")
    factory = out / "09-factory-artwork.png"
    if factory.exists() and fingerprint(factory) != config["artwork_sha256"]:
        raise ValueError("Existing factory master differs from the approved source.")
    if not factory.exists():
        shutil.copyfile(source, factory)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    scale,scale_prompts=scene_scale(args.width,args.height)
    (out / "scene-scale.json").write_text(json.dumps(scale,indent=2),encoding="utf-8")
    fields = {"width": f"{args.width:g}", "height": f"{args.height:g}", **scale_prompts, "packaging_instruction": "Use a plain unbranded gift box and a coordinated ribbon as styling props, not confirmed included accessories." if args.packaging == "unknown" else "Actual user-confirmed included packaging: " + args.packaging + ". Keep those facts accurate. Any extra box or ribbon needed for this gift composition is a styling prop, not an additional included accessory."}
    templates = json.loads(TEMPLATES.read_text(encoding="utf-8"))
    jobs = []
    for template in templates:
        prompt = "Reference image 1 is the approved flat blanket PRINT ARTWORK, not a product photograph. Use that exact design as the textile's printed surface, preserving its subjects, placement, colors and proportions. Do not invent additional artwork, duplicate central figures or replace the design with a vaguely similar pattern. Natural folds may occlude parts of the print. " + template["prompt"].format(**fields)
        jobs.append({"id": template["id"], "title": template["title"], "prompt": prompt, "out": template["id"] + "-" + template["name"] + ".png", "model": MODEL, "size": "1024x1024", "quality": "high", "images": [str(factory)]})
    folds_x, folds_y = math.ceil(args.width / 16), math.ceil(args.height / 18)
    with Image.open(factory) as im:
        crop_width, crop_height = max(1, im.width // folds_x), max(1, im.height // folds_y)
        left, top = (im.width - crop_width) // 2, (im.height - crop_height) // 2
        im.crop((left, top, left + crop_width, top + crop_height)).save(out / "gift-top-reference.png")
    jobs[7]["images"] = [str(out / "gift-top-reference.png")]
    jobs[7]["prompt"] = (
        f"The supplied reference is ONLY the {args.width/folds_x:g} by {args.height/folds_y:g} inch visible top section of the folded blanket, not its whole print. "
        "Transfer this crop faithfully onto the entire visible folded top face, preserving the clipped subjects at its edges. Do not reconstruct missing parts of the print or fit the full original composition into the box. "
        + templates[7]["prompt"].format(**fields)
    )
    for job in jobs:
        if job["id"] in {"03", "04", "05", "06", "07", "08"}:
            job["prompt"] += (
                " Visual hierarchy: make the blanket or its specified detail the focal subject; "
                "keep surrounding props and background visually subordinate, with uncluttered spacing. "
                "Coordinate the environment with the approved print without recoloring or simplifying the print. "
                "Keep the stated physical scale, boundaries and folds; never enlarge the blanket for visual impact. "
                "Do not add typography, badges, invented textile structure or performance claims for decoration."
            )
    (out / "all-prompts.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "generation-jobs.jsonl").write_text("\n".join(json.dumps(job, ensure_ascii=False) for job in jobs if job["id"] != "02") + "\n", encoding="utf-8")
    (out / "primary-job.jsonl").write_text(json.dumps(jobs[0], ensure_ascii=False) + "\n", encoding="utf-8")
    return out, config, jobs


def font(size, chinese=False):
    return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc" if chinese else "C:/Windows/Fonts/arial.ttf", size)


def clean_main_background(out):
    main="01-white-background.png"
    override_path=out / "selected-images.json"
    if override_path.exists():
        main=json.loads(override_path.read_text(encoding="utf-8")).get("01",main)
    if Path(main).name!=main or not main.endswith(".png"):
        raise ValueError("Invalid main image override.")
    with Image.open(out / main) as im:
        rgb=im.convert("RGB")
    r,g,b=rgb.split()
    minimum=ImageChops.darker(ImageChops.darker(r,g),b)
    mask=minimum.point(lambda value: 255 if value>=243 else 0)
    # Only whiten the near-white region connected to canvas corners, preserving enclosed print areas.
    for seed in [(0,0),(rgb.width-1,0),(0,rgb.height-1),(rgb.width-1,rgb.height-1)]:
        if mask.getpixel(seed)==255:
            ImageDraw.floodfill(mask,seed,128,thresh=0)
    exterior=mask.point(lambda value: 255 if value==128 else 0)
    Image.composite(Image.new("RGB",rgb.size,"white"),rgb,exterior).save(out / "01-white-background-clean.png")


def size_image(out, config):
    main=out / "01-white-background-clean.png"
    with Image.open(main if main.exists() else out / "01-white-background.png") as im:
        rgb = im.convert("RGB")
        difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, "white")).convert("L")
        bbox = difference.point(lambda value: 255 if value > 24 else 0).getbbox()
        product = rgb.crop(bbox) if bbox else rgb
    canvas = Image.new("RGB", (1600, 1600), "white")
    product = ImageOps.contain(product, (1040, 1120), Image.Resampling.LANCZOS)
    left, top = (canvas.width - product.width) // 2, (canvas.height - product.height) // 2
    canvas.paste(product, (left, top))
    draw = ImageDraw.Draw(canvas)
    draw.text((800, 70), "BLANKET SIZE", anchor="mm", font=font(58), fill="#263b32")
    right, bottom = left + product.width, top + product.height
    color = "#364b40"
    def arrow(a, b):
        draw.line([a, b], fill=color, width=4)
        if a[1] == b[1]:
            x1, y = a; x2, _ = b
            draw.polygon([(x1,y),(x1+18,y-10),(x1+18,y+10)],fill=color)
            draw.polygon([(x2,y),(x2-18,y-10),(x2-18,y+10)],fill=color)
        else:
            x,y1=a; _,y2=b
            draw.polygon([(x,y1),(x-10,y1+18),(x+10,y1+18)],fill=color)
            draw.polygon([(x,y2),(x-10,y2-18),(x+10,y2-18)],fill=color)
    arrow((left,bottom+40),(right,bottom+40))
    arrow((right+55,top),(right+55,bottom))
    width, height = config["width_inches"], config["height_inches"]
    draw.text(((left+right)//2,bottom+93),f"{width:g} in",anchor="mm",font=font(43),fill=color)
    layer=Image.new("RGBA",(1000,90),(255,255,255,0))
    ImageDraw.Draw(layer).text((500,45),f"{height:g} in",anchor="mm",font=font(43),fill=color)
    layer=layer.rotate(90,expand=True)
    canvas.paste(layer,(right+76,(top+bottom-layer.height)//2),layer)
    canvas.save(out / "02-size-guide.png")


def finish(out, config, jobs):
    overrides_path=out / "selected-images.json"
    overrides=json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    for slot,name in overrides.items():
        if slot not in {f"{index:02d}" for index in range(1,9)} or Path(name).name!=name or not name.endswith(".png"):
            raise ValueError("Invalid selected-image override.")
        with Image.open(out / name) as selected:
            selected.verify()
    clean_main_background(out)
    size_image(out, config)
    # Caption is a derivative: keep the API output unmodified for traceability.
    gift = out / overrides.get("08", "08-gift-presentation.png")
    if config["packaging"] == "unknown":
        with Image.open(gift) as im:
            canvas=im.convert("RGB")
        draw=ImageDraw.Draw(canvas)
        band=int(canvas.height*0.075)
        draw.rectangle((0,canvas.height-band,canvas.width,canvas.height),fill="white")
        draw.text((canvas.width//2,canvas.height-band//2),"GIFT STYLING IDEA - ACCESSORIES SHOWN AS PROPS",anchor="mm",font=font(max(12,int(canvas.width*0.019))),fill="#3b473f")
        canvas.save(out / "08-gift-presentation-labeled.png")
    files=[job["out"] for job in jobs]+["09-factory-artwork.png"]
    for slot,name in overrides.items():
        files[int(slot)-1]=name
    files[0]="01-white-background-clean.png"
    if config["packaging"] == "unknown":
        files[7]="08-gift-presentation-labeled.png"
    sheet=Image.new("RGB",(1560,1800),"#f2f4f2")
    draw=ImageDraw.Draw(sheet)
    draw.text((30,20),"毛毯图片套装 | 8 张商品展示 + 印花原图",font=font(34,True),fill="#263b32")
    draw.text((30,70),f"{config['width_inches']:g} × {config['height_inches']:g} 英寸 · 示例效果 · 生产规格待确认",font=font(23,True),fill="#5b625c")
    cards=[]
    for index,(name,title) in enumerate(zip(files,NAMES)):
        with Image.open(out / name) as im:
            im.load()
            thumbnail=ImageOps.contain(im.convert("RGB"),(480,480),Image.Resampling.LANCZOS)
            actual=im.size
        x=30+(index%3)*515; y=125+(index//3)*550
        sheet.paste(thumbnail,(x+(480-thumbnail.width)//2,y+(480-thumbnail.height)//2))
        draw.text((x,y+490),f"{index+1:02d}  {title}",font=font(25,True),fill="#263b32")
        cards.append(f'<article><a href="{escape(name)}"><img src="{escape(name)}" alt="{escape(title)}"></a><h2>{index+1:02d} {escape(title)}</h2><p>{actual[0]} × {actual[1]} px · <a href="{escape(name)}" download>下载</a></p></article>')
    sheet.save(out / "listing-contact-sheet.jpg",quality=94,subsampling=0)
    review={"images":files,"visual_review_required":True,"factory_source_sha256":fingerprint(out / "09-factory-artwork.png"),"factory_native_ppi_at_selected_size":[config["master_pixels"][0]/config["width_inches"],config["master_pixels"][1]/config["height_inches"]],"production_ready":False,"notes":["Images are AI product mockups; verify against actual sample before listing.","Machine-wash scene is illustrative; no fade-resistance or wash-cycle claims were added.","Gift styling is not evidence of actual included packaging.","Factory artwork retains the approved source bytes. Confirm printer resolution, bleed and color profile before production."]}
    (out / "delivery-notes.json").write_text(json.dumps(review,indent=2,ensure_ascii=False),encoding="utf-8")
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>毛毯完整图片套装</title><style>*{box-sizing:border-box}body{margin:0;background:#f2f4f2;color:#263b32;font:16px/1.6 "Microsoft YaHei",sans-serif;letter-spacing:0}header,main,footer{max-width:1500px;margin:auto;padding:24px}h1{font-size:28px;margin:0}h2{font-size:18px;margin:10px 0 0}p{margin:4px 0}main{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}article{min-width:0}img{width:100%;aspect-ratio:1;object-fit:contain;background:white;display:block}a{color:#256847}@media(max-width:900px){main{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:540px){main{grid-template-columns:1fr}h1{font-size:23px}}</style><header><h1>秋收稻草人 · 完整图片套装</h1><p>50 × 60 英寸 | 8 张商品展示图 + 1 张印花原图</p></header><main>'''+"\n".join(cards)+'''</main><footer><p>当前为商品效果示例。机洗性能、实际包装需核对实物；原图像素不足以直接承诺大幅印刷质量，生产前须确认工厂规格。</p><a href="listing-set.zip" download>下载完整套装与提示词</a></footer></html>'''
    page=page.replace("秋收稻草人 · 完整图片套装", "毛毯 · 完整图片套装").replace("50 × 60 英寸",f"{config['width_inches']:g} × {config['height_inches']:g} 英寸")
    (out / "gallery.html").write_text(page,encoding="utf-8")
    with zipfile.ZipFile(out / "listing-set.zip","w",zipfile.ZIP_DEFLATED) as archive:
        extras=["listing-contact-sheet.jpg","gallery.html","all-prompts.json","product.json","delivery-notes.json","scene-scale.json"]
        if overrides_path.exists():
            extras.append("selected-images.json")
        extras.extend(path.name for path in out.glob("revision-*.jsonl"))
        extras.extend(name for name in ["source-adaptation.json", "artwork-job.jsonl", "workflow-settings.json"] if (out / name).exists())
        for name in files+extras:
            archive.write(out / name,name)
    print(f"Gallery: {out / 'gallery.html'}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--width",type=float,default=50)
    parser.add_argument("--height",type=float,default=60)
    parser.add_argument("--packaging",default="unknown")
    parser.add_argument("--stage",choices=["prepare","primary","generate","finish","all"],default="all")
    args=parser.parse_args()
    if args.width<=0 or args.height<=0:
        parser.error("Dimensions must be positive.")
    out,config,jobs=prepare(args)
    if args.stage in {"primary","generate","all"}:
        batch=out / ("primary-job.jsonl" if args.stage=="primary" else "generation-jobs.jsonl")
        result=subprocess.run([sys.executable,str(HERE / "generate.py"),"--input",str(batch),"--out-dir",str(out),"--concurrency","2","--skip-existing"])
        if result.returncode:
            return result.returncode
    if args.stage in {"finish","all"}:
        finish(out,config,jobs)
    print(f"Product configuration: {out / 'product.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
