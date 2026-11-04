"""Offline regression checks; no image API requests or live listing operations."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
import workflow as w


def fixture(folder, verified=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (1200, 900), "#eceff0")
    draw = ImageDraw.Draw(im)
    draw.rectangle((225, 0, 974, 899), fill="#28675c")
    for y in range(0, 900, 60):
        draw.rectangle((225, y, 974, y + 12), fill="#dbe7dd")
    im.save(folder / "test-product.png")
    spec = {"width": 970, "height": 600, "max_bytes": 2000000, "verified": verified}
    if verified:
        spec.update(source="TEST FIXTURE ONLY", checked_at="2026-10-28")
    base = {"id": "hero", "kind": "image", "purpose": "product_identity",
            "amazon_module": "Offline test canvas", "spec": spec, "text_mode": "native",
            "shown_size": [50, 60], "headline": "Printed throw blanket",
            "body": "Shown in the 50 x 60 inch size.", "alt": "Striped blanket illustration",
            "claims": [], "asset": "test-product.png"}
    chart = {"id": "sizes", "kind": "size_chart", "purpose": "size_selection",
             "amazon_module": "Offline test canvas", "spec": copy.deepcopy(spec), "text_mode": "native",
             "headline": "Choose your size", "body": "Dimensions in inches. Shapes show relative size.",
             "alt": "Four blanket sizes shown to the same scale", "claims": []}
    brief = {"schema_version": 1, "name": "offline-test", "brand": "Sample Brand", "marketplace": "US",
             "product_mode": "finished", "sizes": [[30,40],[40,50],[50,60],[60,80]],
             "asins": ["B000000001"] if verified else [], "identity_lock": "Preserve the striped illustration",
             "style": "Daylight, green and white", "facts": {}, "modules": [base, chart]}
    w.write(folder / "brief.json", brief)
    return brief


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.brief = fixture(self.root / "input")
        self.project = self.root / "project"
        self.silence = contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None, None, None)
        self.temp.cleanup()

    def prepare(self):
        w.write(self.root / "input/brief.json", self.brief)
        return w.prepare(self.root / "input/brief.json", self.project)

    def test_complete_draft_is_packaged_without_claiming_review(self):
        self.prepare()
        self.assertEqual(w.render(self.project)["status"], "review_required")
        path = w.package(self.project)
        with zipfile.ZipFile(path) as archive:
            self.assertIn("assets/hero.png", archive.namelist())
            self.assertIn("copy.json", archive.namelist())
            self.assertIsNone(archive.testzip())
        self.assertEqual(path.name, "aplus-draft.zip")
        with Image.open(self.project / "assets/hero.png") as image:
            self.assertEqual(image.size, (970,600))
        chart_copy = w.read(self.project / "copy.json")[1]["body"]
        for label in ["30 x 40", "40 x 50", "50 x 60", "60 x 80"]:
            self.assertIn(label, chart_copy)

    def test_unknown_claim_and_custom_workflow_fail_before_writing(self):
        self.brief["modules"][0]["claims"] = ["never_fades"]
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.project.exists())
        self.brief["modules"][0]["claims"] = []
        self.brief.update(product_mode="custom", customization={"photo_counts":[2], "source":"Fixture", "workflow_verified":False})
        self.brief["modules"][0]["purpose"] = "customization"
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertFalse(self.project.exists())

    def test_missing_generated_image_cannot_package(self):
        m = self.brief["modules"][0]
        m.pop("asset")
        m.update(prompt="Show the supplied blanket on part of a sofa", references=["test-product.png"])
        self.prepare()
        self.assertEqual(w.render(self.project)["status"], "invalid")
        with self.assertRaises(ValueError):
            w.package(self.project)
        self.assertFalse(list(self.project.glob("*.zip")))

    def test_job_tampering_cannot_send_request(self):
        m = self.brief["modules"][0]
        m.pop("asset")
        m.update(prompt="Retain product", references=["test-product.png"])
        self.prepare()
        with (self.project / "jobs.jsonl").open("a", encoding="utf-8") as stream:
            stream.write("\n")
        with patch.object(w.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                w.generate(self.project, execute=True)
            run.assert_not_called()

    def test_source_snapshot_and_render_changes_are_detected(self):
        p = self.prepare()
        w.render(self.project)
        Image.new("RGB", (970,600), "black").save(self.project / "assets/hero.png")
        self.assertEqual(w.check(self.project)["status"], "invalid")
        source = self.project / next(iter(p["sources"].values()))["file"]
        source.write_bytes(b"not an image")
        with self.assertRaises(ValueError):
            w.load_project(self.project)

    def test_review_is_bound_to_specific_image_and_project(self):
        self.brief = fixture(self.root / "input", verified=True)
        project = self.prepare()
        w.render(self.project)
        records = w.read(self.project / "render-manifest.json")["modules"]
        review = {"project_fingerprint": project["fingerprint"], "modules": {
            ident: {"sha256": r["sha256"], "identity":True, "scale":True, "text":True, "claims":True,
                    "notes":"Synthetic test only"} for ident,r in records.items()}}
        w.write(self.project / "review.json", review)
        self.assertEqual(w.check(self.project)["status"], "reviewed_for_manual_upload")
        review["modules"]["hero"]["sha256"] = "stale"
        w.write(self.project / "review.json", review)
        self.assertEqual(w.check(self.project)["status"], "review_required")

    def test_overlay_overflow_fails_instead_of_truncating(self):
        m = self.brief["modules"][0]
        m["text_mode"] = "overlay"
        m["body"] = "Important product information " * 100
        self.prepare()
        result = w.render(self.project)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(any("overflows" in e for e in result["errors"]))

    def test_short_overlay_renders_and_chart_text_limits_are_enforced(self):
        self.brief["modules"][0].update(text_mode="overlay", headline="Pattern & finish", body="Preserve the approved print.")
        self.brief["modules"][1]["text_limits"] = {"body":60}
        self.prepare()
        result = w.render(self.project)
        self.assertTrue((self.project / "assets/hero.png").exists())
        self.assertTrue(any("body exceeds" in e for e in result["errors"]))

    def test_batch_partial_failure_keeps_success_and_retries_only_failed(self):
        m=self.brief['modules'][0]; m.pop('asset')
        m.update(prompt='Keep supplied blanket',references=['test-product.png'])
        second=copy.deepcopy(m); second['id']='second'
        self.brief['modules'].append(second); self.prepare()
        def partial(command,check):
            self.assertEqual(command[command.index('--concurrency')+1],'2')
            raw=self.project/'raw'; raw.mkdir(exist_ok=True)
            Image.new('RGB',(1200,900),'green').save(raw/'hero.png')
            return type('Result',(),{'returncode':1})()
        with patch.object(w.subprocess,'run',side_effect=partial) as run:
            with self.assertRaises(ValueError): w.generate(self.project,execute=True,concurrency=2)
            self.assertEqual(run.call_count,1)
        state=w.read(self.project/'generation-state.json')
        self.assertEqual(state['hero']['status'],'completed')
        self.assertEqual(state['second']['status'],'needs_investigation')
        with patch.object(w.subprocess,'run') as run:
            with self.assertRaises(ValueError): w.generate(self.project,execute=True,concurrency=2)
            run.assert_not_called()
        def finish(command,check):
            jobs=[json.loads(s) for s in Path(command[command.index('--input')+1]).read_text(encoding='utf-8').splitlines()]
            self.assertEqual([j['out'] for j in jobs],['second.png'])
            Image.new('RGB',(1200,900),'blue').save(self.project/'raw/second.png')
            return type('Result',(),{'returncode':0})()
        with patch.object(w.subprocess,'run',side_effect=finish):
            w.generate(self.project,execute=True,concurrency=2,retry_note='Test fixture: failure confirmed')
        with patch.object(w.subprocess,'run') as run:
            w.generate(self.project,execute=True,concurrency=2)
            run.assert_not_called()

    def test_size_rectangles_use_one_scale_in_actual_pixels(self):
        m = self.brief["modules"][1]
        image, geometry = w.size_chart(m, self.brief["sizes"])
        for size, item in zip(self.brief["sizes"], geometry["rectangles"]):
            x,y,width,height = item["box"]
            self.assertLessEqual(abs(width / size[0] - height / size[1]), .04)
            colour = image.getpixel((x + width // 2, y + height // 2))
            self.assertNotEqual(colour, (255,255,255))
            self.assertEqual(image.getpixel((x-1, y+height//2)), (255,255,255))
            self.assertEqual(image.getpixel((x+width, y+height//2)), (255,255,255))


if __name__ == "__main__":
    unittest.main()
