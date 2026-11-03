import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw
import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "references"
        self.sources.mkdir()
        Image.new("RGB", (100, 120), "green").save(self.sources / "image2.png")
        Image.new("RGB", (120, 120), "blue").save(self.sources / "image10.png")
        self.args = types.SimpleNamespace(references=self.sources, output=self.root / "result", width=50., height=60., theme="", palette="", packaging="unknown", resume=False, dry_run=False)
        self.generated = []

    def fake_generate(self, path, folder):
        for line in path.read_text(encoding="utf-8").splitlines():
            job = json.loads(line)
            target = folder / job["out"]
            if target.exists():
                continue
            self.generated.append(str(target))
            if target.name == "adapted-artwork.png":
                Image.new("RGB", (100, 120), "blue").save(target)
            else:
                im = Image.new("RGB", (300, 300), "white")
                ImageDraw.Draw(im).rectangle((40, 20, 260, 280), fill="green")
                im.save(target)

    def test_dry_run_and_source_guard(self):
        self.args.dry_run = True
        with patch.object(workflow, "generate") as generate, contextlib.redirect_stdout(io.StringIO()):
            workflow.run(self.args)
        generate.assert_not_called()
        self.assertFalse(self.args.output.exists())
        self.assertEqual([r["title"] for r in workflow.plan(self.args)["sets"]], ["image2", "image10"])
        self.args.output = self.sources / "output"
        with self.assertRaises(ValueError):
            workflow.plan(self.args)

    def test_batch_resume_revisions_and_archives(self):
        with patch.object(workflow, "generate", side_effect=self.fake_generate), contextlib.redirect_stdout(io.StringIO()):
            workflow.run(self.args)
            generated = list(self.generated)
            self.args.resume = True
            workflow.run(self.args)
            self.assertEqual(self.generated, generated)
            folder = self.args.output / "set-001"
            Image.new("RGB", (300, 300), "red").save(folder / "08-revision-v2.png")
            workflow.select(folder, "08", "08-revision-v2.png")
            workflow.summarize(self.args.output)
            with Image.open(folder / "08-gift-presentation-labeled.png") as gift:
                self.assertEqual(gift.getpixel((10, 10)), (255, 0, 0))
            with zipfile.ZipFile(self.args.output / "all-listing-sets.zip") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(sum(n.endswith(".png") for n in archive.namelist()), 18)
                self.assertNotIn('href="listing-set.zip"', archive.read("set-001/gallery.html").decode())
            self.assertEqual((folder / "09-factory-artwork.png").read_bytes(), (self.sources / "image2.png").read_bytes())
            Image.new("RGB", (100, 120), "red").save(self.sources / "image2.png")
            with self.assertRaisesRegex(ValueError, "Sources or product parameters changed"):
                workflow.run(self.args)


if __name__ == "__main__":
    unittest.main()
