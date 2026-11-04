"""Prepare, generate, render and review blanket A+ using the shared image runtime."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

from PIL import Image, ImageDraw, ImageFont, ImageOps

SKILL = Path(__file__).resolve().parents[1]
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
RUNTIME = Path(os.environ.get(
    "CODEX_IMAGE_RUNTIME",
    CODEX_HOME / "skill-library" / "image-runtime" / "generate.py",
)).expanduser()
SIZES = {(30, 40), (40, 50), (50, 60), (60, 80)}
REVIEW_KEYS = ("identity", "scale", "text", "claims")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value, label):
    require(isinstance(value, str) and value.strip(), f"{label}: nonempty text required")
    return value.strip()


def picture(path):
    with Image.open(path) as im:
        require(im.width > 0 and im.height > 0, "Empty image")
        size = list(im.size)
        im.verify()
    return size


def validate(brief, base):
    require(brief.get("schema_version") == 1, "schema_version must be 1")
    for field in ("name", "brand", "identity_lock", "style"):
        text(brief.get(field), field)
    require(brief.get("marketplace") == "US", "v1 supports US only")
    require(brief.get("product_mode") in ("finished", "custom"), "Choose finished or custom")
    sizes = brief.get("sizes", [])
    require(isinstance(sizes, list) and sizes, "At least one confirmed size required")
    require(all(isinstance(s, list) and len(s) == 2 and all(type(v) is int for v in s)
                and tuple(s) in SIZES for s in sizes), "Unsupported blanket dimensions")
    require(len({tuple(s) for s in sizes}) == len(sizes), "Duplicate sizes")
    require(isinstance(brief.get("asins", []), list), "asins must be a list")
    require(all(isinstance(a, str) and re.fullmatch(r"[A-Z0-9]{10}", a)
                for a in brief.get("asins", [])), "Invalid ASIN")
    facts = brief.get("facts", {})
    require(isinstance(facts, dict), "facts must be a mapping")
    for key, fact in facts.items():
        require(isinstance(fact, dict), f"Invalid fact {key}")
        text(fact.get("value"), key)
        text(fact.get("source"), f"{key}.source")
        require(type(fact.get("confirmed")) is bool, f"{key}.confirmed required")
    custom = brief.get("customization", {})
    if brief["product_mode"] == "custom":
        counts = custom.get("photo_counts", [])
        require(isinstance(counts, list) and counts and all(type(c) is int and 1 <= c <= 10 for c in counts),
                "Custom mode needs actual photo_counts (1..10)")
        text(custom.get("source"), "customization.source")
    modules = brief.get("modules", [])
    require(isinstance(modules, list) and 1 <= len(modules) <= 20, "Need 1..20 module assets")
    ids, paths = set(), {}
    for m in modules:
        ident = m.get("id", "")
        require(isinstance(ident, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,39}", ident), "Invalid module id")
        require(ident not in ids, "Duplicate module id")
        ids.add(ident)
        text(m.get("purpose"), f"{ident}.purpose")
        text(m.get("amazon_module"), f"{ident}.amazon_module")
        require(m.get("kind") in ("image", "size_chart"), "Unknown module kind")
        require(m.get("text_mode", "native") in ("native", "overlay"), "Unknown text mode")
        spec = m.get("spec", {})
        require(all(type(spec.get(k)) is int and 320 <= spec[k] <= 4000 for k in ("width", "height")),
                "Module canvas must be 320..4000 px each side")
        require(type(spec.get("max_bytes")) is int and spec["max_bytes"] > 0, "Specify max_bytes")
        require(type(spec.get("verified")) is bool, "spec.verified required")
        if spec["verified"]:
            text(spec.get("source"), "Verified spec needs source")
            dt.date.fromisoformat(spec.get("checked_at", ""))
        for key in ("headline", "body", "alt"):
            value = m.get(key, "")
            require(isinstance(value, str), "Copy fields must be strings")
            if key != "body":
                text(value, f"{ident}.{key}")
            require(not re.search(r"[\u4e00-\u9fff]", value), "Buyer-facing copy must be English")
            limit = m.get("text_limits", {}).get(key)
            if limit is not None:
                require(type(limit) is int and limit > 0 and len(value) <= limit, f"{ident}.{key} exceeds limit")
        require(isinstance(m.get("claims", []), list), "claims must be a list")
        for key in m.get("claims", []):
            require(key in facts and facts[key]["confirmed"] is True, f"Unconfirmed claim: {key}")
        if m.get("purpose") == "customization":
            require(brief["product_mode"] == "custom" and custom.get("workflow_verified") is True,
                    "Customization instructions require verified real workflow")
            text(custom.get("workflow_evidence"), "customization.workflow_evidence")
        if m["kind"] == "size_chart":
            require(m.get("text_mode", "native") == "native", "Size chart uses native copy")
            continue
        require(m.get("shown_size") in sizes, "Image module needs shown_size in actual sizes")
        require(bool(m.get("asset")) != bool(m.get("prompt")), "Choose exactly one asset or generation prompt")
        refs = m.get("references", [])
        require(isinstance(refs, list), "references must be a list")
        if m.get("prompt"):
            text(m["prompt"], "prompt")
            require(refs, "Generated product images require references")
        for raw in ([m["asset"]] if m.get("asset") else refs):
            p = Path(raw)
            p = (base / p).resolve() if not p.is_absolute() else p.resolve()
            require(p.is_file(), f"Missing image: {p}")
            picture(p)
            paths[raw] = p
    return paths


def prepare(brief_path, out):
    brief_path, out = Path(brief_path).resolve(), Path(out).resolve()
    brief = read(brief_path)
    paths = validate(brief, brief_path.parent)
    require(not out.exists() or not any(out.iterdir()), "Use a new empty output directory")
    out.mkdir(parents=True, exist_ok=True)
    sources = {}
    for raw, original in paths.items():
        sha = digest(original)
        relative = "sources/" + sha + original.suffix.lower()
        target = out / relative
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(original, target)
        sources[raw] = {"original": str(original), "file": relative, "sha256": sha}
    project = {"brief": brief, "sources": sources, "created_at": now()}
    jobs = []
    for m in brief["modules"]:
        if not m.get("prompt"):
            continue
        prompt = ("Create a text-free photograph for one Amazon Basic A+ asset. No brand names, logos or watermarks anywhere. "
                  f"Product mode: {brief['product_mode']}. Product identity: {brief['identity_lock']}\n"
                  f"Campaign style (must not recolour the product): {brief['style']}\n"
                  f"Blanket shown: {m['shown_size'][0]} x {m['shown_size'][1]} inches. "
                  f"Final image canvas: {m['spec']['width']} x {m['spec']['height']} pixels.\n"
                  f"{m['prompt']}\nNo text, dimension numbers, badges, invented accessories or certifications. "
                  "Preserve the supplied print, border, orientation and colours. Keep the full required product area in frame.")
        if brief["product_mode"] == "custom":
            prompt += f"\nPreserve the supplied photo layout; available photo counts: {brief['customization']['photo_counts']}."
        jobs.append({"out": m["id"] + ".png", "prompt": prompt, "size": "auto", "quality": "high",
                     "images": [str(out / sources[r]["file"]) for r in m["references"]]})
    (out / "jobs.jsonl").write_text("".join(json.dumps(j, ensure_ascii=False) + "\n" for j in jobs), encoding="utf-8")
    project["jobs_sha256"] = digest(out / "jobs.jsonl")
    project["fingerprint"] = signature(project)
    write(out / "project.json", project)
    write(out / "review.json", {"project_fingerprint": project["fingerprint"], "modules": {}})
    print(f"Prepared {len(brief['modules'])} assets, {len(jobs)} image jobs: {out}")
    return project


def load_project(root):
    project = read(root / "project.json")
    fingerprint = project["fingerprint"]
    require(signature({k: v for k, v in project.items() if k != "fingerprint"}) == fingerprint,
            "Project changed; prepare a new revision instead of reusing previous outputs")
    for source in project["sources"].values():
        p = (root / source["file"]).resolve()
        require(p.is_relative_to(root.resolve()) and p.is_file() and digest(p) == source["sha256"],
                "Source snapshot changed or missing")
    return project


def generate(root, module=None, execute=False, retry_note=None, concurrency=1):
    if concurrency != 1:
        return generate_batch(root,module,execute,retry_note,concurrency)
    project = load_project(root)
    require(digest(root / "jobs.jsonl") == project["jobs_sha256"], "Job prompts or references changed; prepare a new revision")
    jobs = [json.loads(s) for s in (root / "jobs.jsonl").read_text(encoding="utf-8").splitlines() if s]
    expected = {m["id"] for m in project["brief"]["modules"] if m.get("prompt")}
    require({j["out"][:-4] for j in jobs} == expected and len(jobs) == len(expected), "Job mapping changed")
    if module:
        require(module in expected, "Selected module has no generation task")
        jobs = [j for j in jobs if j["out"] == module + ".png"]
    require(RUNTIME.is_file(), "Shared image runtime is unavailable")
    state_path = root / "generation-state.json"
    state = read(state_path) if state_path.exists() else {}
    for job in jobs:
        ident = job["out"][:-4]
        state_entry = state.get(ident, {})
        output = root / "raw" / job["out"]
        if output.exists():
            require(state_entry.get("status") == "completed" and digest(output) == state_entry.get("sha256"),
                    "Existing output is not a verified completed task; inspect before retrying")
            picture(output)
            continue
        if execute and state_entry:
            require(bool(retry_note and retry_note.strip()),
                    "Previous attempt unresolved. Inspect provider/runtime state before supplying --retry-note")
        jobfile = root / "tasks" / (ident + ".jsonl")
        jobfile.parent.mkdir(exist_ok=True)
        jobfile.write_text(json.dumps(job, ensure_ascii=False) + "\n", encoding="utf-8")
        command = [sys.executable, "-X", "utf8", str(RUNTIME), "--input", str(jobfile),
                   "--out-dir", str(root / "raw"), "--concurrency", "1"]
        if not execute:
            command.append("--dry-run")
        else:
            state[ident] = {"status": "submitted", "at": now(), "retry_note": retry_note}
            write(state_path, state)
        result = subprocess.run(command, check=False)
        if execute:
            state[ident]["status"] = "needs_investigation"
            if result.returncode == 0 and output.exists():
                picture(output)
                state[ident].update(status="completed", sha256=digest(output))
            write(state_path, state)
            require(state[ident]["status"] == "completed", "Generation incomplete; inspect runtime logs before retry")
        require(result.returncode == 0, "Shared runtime validation failed")
    print("Generation complete" if execute else "Dry-run complete; no image-generation request sent")


def generate_batch(root,module,execute,retry_note,concurrency):
    require(concurrency==2,'Use at most two concurrent image requests')
    project=load_project(root)
    require(digest(root/'jobs.jsonl')==project['jobs_sha256'],'Job prompts or references changed')
    jobs=[json.loads(s) for s in (root/'jobs.jsonl').read_text(encoding='utf-8').splitlines() if s]
    expected={m['id'] for m in project['brief']['modules'] if m.get('prompt')}
    require({j['out'][:-4] for j in jobs}==expected and len(jobs)==len(expected),'Job mapping changed')
    if module:
        require(module in expected,'Selected module has no generation task')
        jobs=[j for j in jobs if j['out']==module+'.png']
    state_path=root/'generation-state.json'; state=read(state_path) if state_path.exists() else {}
    pending=[]
    for job in jobs:
        ident=job['out'][:-4]; output=root/'raw'/job['out']; entry=state.get(ident,{})
        if output.exists():
            require(entry.get('status')=='completed' and digest(output)==entry.get('sha256'),'Existing output is not a verified completed task')
            picture(output)
            continue
        if execute and entry:
            require(bool(retry_note and retry_note.strip()),'Previous attempt unresolved; inspect before retry')
        pending.append(job)
    if not pending:
        print('All scene assets already complete; no requests sent')
        return
    require(RUNTIME.is_file(),'Shared image runtime unavailable')
    jobfile=root/'tasks/pending-batch.jsonl'; jobfile.parent.mkdir(exist_ok=True)
    jobfile.write_text(''.join(json.dumps(j,ensure_ascii=False)+'\n' for j in pending),encoding='utf-8')
    command=[sys.executable,'-X','utf8',str(RUNTIME),'--input',str(jobfile),'--out-dir',str(root/'raw'),'--concurrency','2']
    if execute:
        for job in pending:
            state[job['out'][:-4]]={'status':'submitted','at':now(),'retry_note':retry_note}
        write(state_path,state)
    else:
        command.append('--dry-run')
    result=subprocess.run(command,check=False)
    if execute:
        for job in pending:
            ident=job['out'][:-4]; output=root/'raw'/job['out']
            state[ident]['status']='needs_investigation'
            if output.is_file():
                try:
                    picture(output)
                    state[ident].update(status='completed',sha256=digest(output))
                except (OSError,ValueError):
                    pass
        write(state_path,state)
        require(all(state[j['out'][:-4]]['status']=='completed' for j in pending),'Batch incomplete; inspect logs, keep completed assets and do not blindly resend')
    require(result.returncode==0,'Shared runtime returned an error; inspect logs')
    print('Batch complete' if execute else 'Dry-run complete; no image-generation request sent')


def font(size, bold=False):
    path = Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    require(path.is_file(), "Arial font unavailable; configure a licensed local font before rendering")
    return ImageFont.truetype(str(path), size)


def lines(draw, value, face, width):
    result = []
    for paragraph in value.splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            require(draw.textlength(word, font=face) <= width, "Word cannot fit text area")
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=face) > width:
                result.append(current)
                current = word
            else:
                current = candidate
        result.append(current)
    return result


def render_image(m, asset):
    width, height = m["spec"]["width"], m["spec"]["height"]
    canvas = Image.new("RGB", (width, height), "white")
    overlay = m.get("text_mode", "native") == "overlay"
    image_height = int(height * .58) if overlay else height
    with Image.open(asset) as opened:
        rgba = ImageOps.exif_transpose(opened).convert("RGBA")
        source = Image.new("RGBA", rgba.size, "white")
        source.alpha_composite(rgba)
        source = source.convert("RGB")
        require(source.width >= width or source.height >= image_height, "Source too small for this canvas")
        scale = min(width / source.width, image_height / source.height)
        require(scale <= 1.01, "Source would need upscaling")
        resized = source.resize((max(1, round(source.width * scale)), max(1, round(source.height * scale))), Image.Resampling.LANCZOS)
        canvas.paste(resized, ((width - resized.width) // 2, (image_height - resized.height) // 2))
    if overlay:
        draw = ImageDraw.Draw(canvas)
        pad = max(16, width // 40)
        y = image_height + pad
        # Keep raster copy legible when displayed in a 343px mobile content area.
        for value, face in [(m["headline"], font(max(22, math.ceil(width * 18 / 343)), True)),
                            (m.get("body", ""), font(max(18, math.ceil(width * 14 / 343))))]:
            for line in lines(draw, value, face, width - 2 * pad):
                step = face.size + 8
                require(y + step <= height - pad, "Text overflows; shorten text or use native text mode")
                draw.text((pad, y), line, fill="#253633", font=face)
                y += step
            y += 5
    return canvas


def size_chart(m, sizes):
    width, height = m["spec"]["width"], m["spec"]["height"]
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    pad, gap = 24, max(16, width // 40)
    scale = min((width - 2 * pad - gap * (len(sizes) - 1)) / sum(s[0] for s in sizes),
                (height - 130) / max(s[1] for s in sizes))
    require(scale > 0, "Size chart cannot fit canvas")
    label_font = font(max(16, min(24, width // 40)))
    total = sum(round(s[0] * scale) for s in sizes) + gap * (len(sizes) - 1)
    x = (width - total) // 2
    bottom = height - 75
    geometry = []
    for (w, h), colour in zip(sizes, ["#28675C", "#466D85", "#9B5369", "#9B7536"]):
        rw, rh = round(w * scale), round(h * scale)
        draw.rectangle((x, bottom - rh, x + rw - 1, bottom - 1), fill=colour)
        label = f'{w}" x {h}"'
        tw = draw.textlength(label, font=label_font)
        require(tw <= rw + gap - 4, "Size labels collide; use a wider module")
        draw.text((x + (rw - tw) / 2, bottom + 12), label, fill="#253633", font=label_font)
        geometry.append({"inches": [w, h], "box": [x, bottom - rh, rw, rh]})
        x += rw + gap
    return canvas, {"pixels_per_inch": scale, "rectangles": geometry}


def preview(root, brief, records):
    sections = []
    for m in brief["modules"]:
        record = records[m["id"]]
        photo = (f'<img src="{record["file"]}" alt="{html.escape(m["alt"], quote=True)}">'
                 if record.get("file") else '<p class="missing">Image not yet available</p>')
        copy = "" if m.get("text_mode", "native") == "overlay" else (
            f'<h2>{html.escape(m["headline"])}</h2><p>{html.escape(m.get("body", ""))}</p>')
        sections.append(f'<section>{photo}{copy}</section>')
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>A+ review</title><style>*{box-sizing:border-box}body{margin:0;background:#fff;color:#253633;font:16px Arial,sans-serif;letter-spacing:0}'
            'main{max-width:970px;margin:auto;padding:16px}header{border-bottom:1px solid #ddd;padding:12px 0;margin-bottom:24px}'
            'section{margin:0 0 32px}img{display:block;width:100%;height:auto}h1{font-size:24px}h2{font-size:22px;line-height:1.3}'
            'p{line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}.missing{padding:24px;background:#f6eeee}</style>'
            f'<main><header><h1>{html.escape(brief["brand"])} / A+ review</h1><p>Design preview. Check checks.json for review status. Amazon rendering may differ.</p></header>'
            + "".join(sections) + '</main></html>')
    (root / "preview.html").write_text(page, encoding="utf-8")


def render(root):
    project = load_project(root)
    brief = json.loads(json.dumps(project["brief"]))
    records, copies = {}, []
    for m in brief["modules"]:
        if m["kind"] == "size_chart":
            labels = [f"{w} x {h}" for w, h in brief["sizes"]]
            if not all(label in m.get("body", "") for label in labels):
                m["body"] = m.get("body", "").rstrip() + "\nSizes in inches: " + "; ".join(labels) + "."
    (root / "assets").mkdir(exist_ok=True)
    for m in brief["modules"]:
        ident = m["id"]
        record = {"errors": []}
        try:
            for key, limit in m.get("text_limits", {}).items():
                require(len(m.get(key, "")) <= limit, f"{key} exceeds specified limit after layout")
            if m["kind"] == "size_chart":
                canvas, geometry = size_chart(m, brief["sizes"])
                record["geometry"] = geometry
            else:
                asset = (root / project["sources"][m["asset"]]["file"] if m.get("asset")
                         else root / "raw" / (ident + ".png"))
                require(asset.is_file(), "Image not yet available")
                if m.get("prompt"):
                    state = read(root / "generation-state.json") if (root / "generation-state.json").exists() else {}
                    require(state.get(ident, {}).get("status") == "completed" and
                            state[ident].get("sha256") == digest(asset), "Generated image lacks matching completion record")
                canvas = render_image(m, asset)
                record["asset_sha256"] = digest(asset)
            relative = "assets/" + ident + ".png"
            canvas.save(root / relative, optimize=True)
            record.update(file=relative, sha256=digest(root / relative), pixels=list(canvas.size))
            if (root / relative).stat().st_size > m["spec"]["max_bytes"]:
                record["errors"].append("Image exceeds specified byte limit")
        except (ValueError, OSError) as exc:
            record["errors"].append(str(exc))
        records[ident] = record
        copies.append({k: m.get(k, "") for k in ("id", "amazon_module", "headline", "body", "alt", "claims")})
    write(root / "copy.json", copies)
    write(root / "layout.json", {"modules": brief["modules"], "sizes": brief["sizes"]})
    preview(root, brief, records)
    write(root / "render-manifest.json", {"fingerprint": project["fingerprint"], "modules": records,
          "copy_sha256": digest(root / "copy.json"), "layout_sha256": digest(root / "layout.json"),
          "preview_sha256": digest(root / "preview.html")})
    return check(root)


def check(root):
    project = load_project(root)
    manifest = read(root / "render-manifest.json") if (root / "render-manifest.json").exists() else {}
    review = read(root / "review.json") if (root / "review.json").exists() else {}
    errors, pending = [], []
    if manifest.get("fingerprint") != project["fingerprint"]:
        errors.append("Missing or stale render manifest")
    for file, key in [("copy.json", "copy_sha256"), ("layout.json", "layout_sha256"), ("preview.html", "preview_sha256")]:
        p = root / file
        if not p.is_file() or digest(p) != manifest.get(key):
            errors.append(f"Missing or changed {file}")
    review_valid = review.get("project_fingerprint") == project["fingerprint"]
    for m in project["brief"]["modules"]:
        ident = m["id"]
        r = manifest.get("modules", {}).get(ident, {})
        errors.extend(f"{ident}: {e}" for e in r.get("errors", []))
        p = root / "assets" / (ident + ".png")
        try:
            require(r.get("file") == f"assets/{ident}.png" and p.is_file(), "Missing expected image")
            require(digest(p) == r.get("sha256"), "Rendered image changed")
            require(picture(p) == [m["spec"]["width"], m["spec"]["height"]], "Wrong image dimensions")
            require(p.stat().st_size <= m["spec"]["max_bytes"], "Image exceeds byte limit")
        except (ValueError, OSError) as exc:
            errors.append(f"{ident}: {exc}")
        if not m["spec"]["verified"]:
            pending.append(f"{ident}: confirm actual Seller Central module specification")
        rv = review.get("modules", {}).get(ident, {})
        if not (review_valid and rv.get("sha256") == r.get("sha256") and rv.get("sha256")
                and all(rv.get(k) is True for k in REVIEW_KEYS) and str(rv.get("notes", "")).strip()):
            pending.append(f"{ident}: visual and factual review required")
    if not project["brief"].get("asins"):
        pending.append("Confirm target ASIN scope before upload")
    if project["brief"]["product_mode"] == "custom" and not project["brief"].get("customization", {}).get("workflow_verified"):
        pending.append("Custom upload workflow not verified; do not imply a working customization UI")
    status = "invalid" if errors else "review_required" if pending else "reviewed_for_manual_upload"
    result = {"status": status, "errors": errors, "pending": pending, "checked_at": now(),
              "scope": {"brand": project["brief"]["brand"], "asins": project["brief"].get("asins", [])},
              "limitation": "Local review is not Amazon approval or a product laboratory test."}
    write(root / "checks.json", result)
    print(json.dumps(result, ensure_ascii=False))
    return result


def package(root):
    result = check(root)
    require(not result["errors"], "Resolve structural errors before packaging")
    project = load_project(root)
    suffix = "reviewed" if result["status"] == "reviewed_for_manual_upload" else "draft"
    target = root / f"aplus-{suffix}.zip"
    files = ["preview.html", "copy.json", "layout.json", "checks.json", "review.json", "project.json", "render-manifest.json"]
    files.extend(f"assets/{m['id']}.png" for m in project["brief"]["modules"])
    files.extend(s["file"] for s in project["sources"].values())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(set(files)):
            require((root / relative).is_file(), f"Missing deliverable: {relative}")
            archive.write(root / relative, relative)
    print(target)
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    prep = subs.add_parser("prepare")
    prep.add_argument("--brief", required=True, type=Path)
    prep.add_argument("--out", required=True, type=Path)
    for name in ("generate", "render", "check", "package"):
        sub = subs.add_parser(name)
        sub.add_argument("--project", required=True, type=Path)
        if name == "generate":
            sub.add_argument("--module")
            sub.add_argument("--execute", action="store_true")
            sub.add_argument("--retry-note", help="Only after resolving prior task/provider status")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.brief, args.out)
        else:
            root = args.project.resolve()
            if args.command == "generate":
                generate(root, args.module, args.execute, args.retry_note)
            else:
                result = globals()[args.command](root)
                if isinstance(result, dict) and result.get("errors"):
                    return 1
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"A+ workflow stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
