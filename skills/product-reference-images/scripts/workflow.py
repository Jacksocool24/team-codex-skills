"""Create and optionally run repeatable product reference-image jobs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from PIL import Image, ImageDraw, ImageOps


HERE = Path(__file__).resolve().parent
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
RUNTIME = Path(os.environ.get(
    "CODEX_IMAGE_RUNTIME",
    CODEX_HOME / "skill-library" / "image-runtime" / "generate.py",
)).expanduser()
SUPPORTED = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
VARIATIONS = (
    "a clear central hero motif with balanced supporting ornaments",
    "a calm repeat-friendly composition with evenly distributed medium motifs",
    "a layered storybook illustration with foreground, middle ground and background",
    "a stable border or medallion composition with a strong central focal point",
)
THEME_EXTENSIONS = {
    "万圣节": "friendly ghosts, pumpkins, a black cat, autumn leaves and a moonlit garden",
    "halloween": "friendly ghosts, pumpkins, a black cat, autumn leaves and a moonlit garden",
    "秋季": "pumpkins, corn, apples, a scarecrow, sunflowers, wheat and warm autumn leaves",
    "丰收": "pumpkins, corn, apples, a scarecrow, sunflowers, wheat and warm autumn leaves",
    "冬日": "a cabin, evergreen trees, snow, pinecones, warm window light and a quiet winter sky",
    "冬季": "a cabin, evergreen trees, snow, pinecones, warm window light and a quiet winter sky",
    "春夏": "flowers, butterflies, cherries, picnic accents, green leaves and a bright open sky",
    "野餐": "flowers, butterflies, cherries, picnic accents, green leaves and a bright open sky",
    "海岸": "shells, gentle waves, a lighthouse, coastal plants and a blue-green palette",
    "coastal": "shells, gentle waves, a lighthouse, coastal plants and a blue-green palette",
}


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def natural(path: Path):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", str(path))]


def collect_references(values: list[str]) -> list[Path]:
    paths = []
    for raw in values:
        source = Path(raw).expanduser().resolve()
        if source.is_file() and source.suffix.casefold() in SUPPORTED:
            paths.append(source)
        elif source.is_dir():
            paths.extend(sorted((p for p in source.rglob("*")
                                 if p.is_file() and p.suffix.casefold() in SUPPORTED), key=natural))
        else:
            raise ValueError(f"Reference image or folder not found: {source}")
    unique = []
    seen = set()
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            continue
        with Image.open(path) as image:
            image.verify()
        unique.append(path)
        seen.add(key)
    return unique


def normalized_themes(values: list[str]) -> list[str]:
    themes = []
    for value in values:
        for part in re.split(r"[,，、]", value):
            cleaned = part.strip()
            if cleaned and cleaned.casefold() not in {item.casefold() for item in themes}:
                themes.append(cleaned)
    return themes or ["seasonal home decor"]


def expand_themes(themes: list[str]) -> str:
    additions = []
    for theme in themes:
        key = theme.casefold()
        for candidate, extension in THEME_EXTENSIONS.items():
            if candidate.casefold() in key and extension not in additions:
                additions.append(extension)
    return ", ".join(themes + additions)


def product_surface(product: str) -> str:
    lowered = product.casefold()
    if any(word in lowered for word in ("毛毯", "blanket", "地毯", "rug", "地垫", "mat", "抱枕", "pillow")):
        return "flat full-bleed textile artwork, coherent repeat-friendly decorative composition, no folds or mockup texture"
    return "a clear product-appropriate visual concept with a coherent silhouette, materials and uncluttered composition"


def build_prompt(product: str, themes: list[str], style: str, palette: str, index: int) -> str:
    style_text = style.strip() or "polished contemporary American home-decor illustration"
    palette_text = palette.strip() or "a coordinated seasonal palette with clear contrast and no muddy colors"
    return (
        f"Create a high-quality visual reference concept for {product}. "
        f"Core theme: {expand_themes(themes)}. "
        f"Composition variation: {VARIATIONS[(index - 1) % len(VARIATIONS)]}. "
        f"Style: {style_text}. Palette: {palette_text}. "
        "Explicit layout and color requirements in Style and Palette take precedence over the default composition variation. "
        "Unless explicitly requested, keep one coherent canvas, not a collage or split-panel contact sheet. "
        "Establish a dominant focal motif, or a deliberate repeat rhythm when requested, with quieter supporting elements. "
        "Control motif scale and spacing so the theme remains legible at thumbnail size; avoid decorative clutter. "
        "Keep the requested color family unchanged; monochrome designs use black, white and gray without color accents. "
        "Make it appealing to US home-decor shoppers with clear hierarchy, balanced color and a memorable focal idea. "
        f"Surface suitability: {product_surface(product)}. "
        "Keep all important motifs recognizable and inside a safe central area. "
        "Use no readable text, logos, trademarks, celebrity likenesses, copyrighted characters, watermark, price or UI. "
        "Do not present unsupported packaging, care claims or product performance. "
        "This is a concept reference image, not a final marketplace listing image or verified production file."
    )


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def make_plan(args) -> dict:
    references = collect_references(args.references)
    themes = normalized_themes(args.theme)
    source_records = [{"path": str(path), "sha256": digest(path)} for path in references]
    jobs = []
    for index in range(1, args.count + 1):
        selected = [str(references[(index - 1) % len(references)])] if references else []
        jobs.append({
            "prompt": build_prompt(args.product, themes, args.style, args.palette, index),
            "out": f"reference-{index:02d}.png",
            "size": args.native_size,
            "quality": args.quality,
            "images": selected,
        })
    return {
        "schema_version": 1,
        "skill": "product-reference-images",
        "version": "1.1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "product": args.product,
        "themes": themes,
        "style": args.style,
        "palette": args.palette,
        "target_pixels": [args.width, args.height],
        "native_size": args.native_size,
        "market": "US",
        "references": source_records,
        "jobs": jobs,
        "status": "planned",
    }


def normalize_outputs(output: Path, manifest: dict) -> None:
    results = []
    failed = False
    for job in manifest["jobs"]:
        path = output / job["out"]
        record = {"file": job["out"], "prompt_sha256": hashlib.sha256(job["prompt"].encode()).hexdigest()}
        try:
            with Image.open(path) as image:
                image.load()
                native = [image.width, image.height]
                if native != manifest["target_pixels"]:
                    converted = ImageOps.fit(image.convert("RGB"), tuple(manifest["target_pixels"]),
                                             method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
                    temporary = path.with_suffix(".normalized.png")
                    converted.save(temporary, format="PNG", optimize=True)
                    temporary.replace(path)
                with Image.open(path) as final:
                    final.load()
                    if final.format != "PNG" or [final.width, final.height] != manifest["target_pixels"]:
                        raise ValueError("final PNG dimensions are incorrect")
                    record.update({"status": "generated", "native_pixels": native,
                                   "pixels": [final.width, final.height], "sha256": digest(path)})
        except (OSError, ValueError) as exc:
            record.update({"status": "missing_or_invalid", "error": str(exc)})
            failed = True
        results.append(record)
    manifest["results"] = results
    manifest["status"] = "failed" if failed else "completed"
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()


def make_preview(output: Path, manifest: dict) -> None:
    valid = [r for r in manifest.get("results", []) if r["status"] == "generated"]
    if not valid:
        return
    cell_w, cell_h = 300, 390
    columns = min(4, len(valid))
    rows = (len(valid) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * cell_w, rows * cell_h), "#f2f4f1")
    draw = ImageDraw.Draw(canvas)
    cards = []
    for index, result in enumerate(valid):
        with Image.open(output / result["file"]) as image:
            thumb = ImageOps.contain(image.convert("RGB"), (280, 320), Image.Resampling.LANCZOS)
        x = (index % columns) * cell_w + (cell_w - thumb.width) // 2
        y = (index // columns) * cell_h + 12
        canvas.paste(thumb, (x, y))
        draw.text(((index % columns) * cell_w + 12, (index // columns) * cell_h + 345), result["file"], fill="#26372c")
        cards.append(f'<article><h2>{html.escape(result["file"])}</h2><img src="{html.escape(result["file"])}" alt="{html.escape(result["file"])}"></article>')
    canvas.save(output / "reference-overview.jpg", quality=94)
    page = (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>商品参考图预览</title>'
        '<style>body{margin:0;padding:24px;background:#f2f4f1;color:#26372c;font:16px/1.5 sans-serif}'
        'main{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px;max-width:1400px}'
        'article{min-width:0}img{display:block;width:100%;height:auto}h1{font-size:28px}h2{font-size:18px}'
        '@media(max-width:720px){main{grid-template-columns:1fr}}</style>'
        f'<h1>{html.escape(manifest["product"])} · 商品参考图</h1>'
        f'<p>{len(valid)}张 · 主题：{html.escape("、".join(manifest["themes"]))}</p><main>'
        + "".join(cards) + "</main></html>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")


def run(args) -> int:
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "generation-plan.json"
    jobs_path = output / "generation-jobs.jsonl"
    if plan_path.exists() and not args.resume:
        raise ValueError("Output already contains a plan. Use a new folder or --resume.")
    manifest = make_plan(args) if not plan_path.exists() else json.loads(plan_path.read_text(encoding="utf-8"))
    write_json(plan_path, manifest)
    jobs_path.write_text("\n".join(json.dumps(job, ensure_ascii=False) for job in manifest["jobs"]) + "\n", encoding="utf-8")
    if args.dry_run:
        manifest["status"] = "planned"
        write_json(output / "generation-manifest.json", manifest)
        print(json.dumps({"dry_run": True, "jobs": len(manifest["jobs"]), "output": str(output),
                          "target_pixels": manifest["target_pixels"]}, ensure_ascii=False))
        return 0
    if not RUNTIME.is_file():
        raise ValueError(f"Shared image runtime not found: {RUNTIME}")
    command = [sys.executable, str(RUNTIME), "--input", str(jobs_path), "--out-dir", str(output),
               "--concurrency", str(args.concurrency), "--quality", args.quality, "--skip-existing"]
    result = subprocess.run(command, check=False)
    if result.returncode:
        manifest["status"] = "generation_failed"
        write_json(output / "generation-manifest.json", manifest)
        return result.returncode
    normalize_outputs(output, manifest)
    write_json(output / "generation-manifest.json", manifest)
    make_preview(output, manifest)
    readme = (
        f"产品：{manifest['product']}\n主题：{'、'.join(manifest['themes'])}\n"
        f"输出：{len(manifest.get('results', []))}张，最终尺寸：{manifest['target_pixels'][0]}×{manifest['target_pixels'][1]}\n"
        "本批图像是视觉参考概念，不代表已验证的商品详情、包装、性能或工厂生产稿。\n"
        "请目视检查主题一致性、主体完整性、版权风险和后续印刷适用性。\n"
    )
    (output / "README.txt").write_text(readme, encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "output": str(output),
                      "images": len(manifest.get("results", [])), "preview": str(output / "index.html")},
                     ensure_ascii=False))
    return 0 if manifest["status"] == "completed" else 1


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--product", default="商品视觉参考图")
    result.add_argument("--theme", action="append", default=[])
    result.add_argument("--references", action="append", default=[])
    result.add_argument("--output", required=True)
    result.add_argument("--count", type=int, default=4)
    result.add_argument("--width", type=int, default=1145)
    result.add_argument("--height", type=int, default=1374)
    result.add_argument("--native-size", choices=("auto", "1024x1024", "1024x1536", "1536x1024"), default="1024x1536")
    result.add_argument("--quality", choices=("low", "medium", "high", "auto"), default="high")
    result.add_argument("--style", default="")
    result.add_argument("--palette", default="")
    result.add_argument("--concurrency", type=int, choices=range(1, 6), default=2)
    result.add_argument("--dry-run", action="store_true")
    result.add_argument("--resume", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if not 1 <= args.count <= 24:
        parser().error("--count must be between 1 and 24")
    if not 128 <= args.width <= 4096 or not 128 <= args.height <= 4096:
        parser().error("target dimensions must be between 128 and 4096 pixels")
    try:
        return run(args)
    except (OSError, ValueError, TypeError) as exc:
        print(f"Local input or configuration validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
