import contextlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image, ImageDraw, ImageChops

import listing_set


class ListingSetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.art=self.root / "art.png"
        Image.new("RGB",(100,120),"green").save(self.art)
        self.args=types.SimpleNamespace(artwork=self.art,out_dir=self.root / "set",width=50.,height=60.,packaging="unknown")

    def test_fixed_set_uses_same_artwork_and_preserves_factory_bytes(self):
        out,config,jobs=listing_set.prepare(self.args)
        self.assertEqual([job["id"] for job in jobs],[f"{i:02d}" for i in range(1,9)])
        self.assertEqual((out / "09-factory-artwork.png").read_bytes(),self.art.read_bytes())
        self.assertTrue(all(job["images"]==[str(out / "09-factory-artwork.png")] for job in jobs[:-1]))
        self.assertEqual(jobs[-1]["images"], [str(out / "gift-top-reference.png")])
        with Image.open(out / "gift-top-reference.png") as crop:
            self.assertEqual(crop.size, (25, 30))
        self.assertIn("50 in",jobs[1]["prompt"])
        self.assertIn("60 in",jobs[1]["prompt"])
        self.assertNotIn(" cm",jobs[1]["prompt"])
        self.assertEqual(len((out / "generation-jobs.jsonl").read_text().splitlines()),7)
        self.assertFalse(config["print_ready"])

    def test_rejects_changed_product_or_wrong_aspect_ratio(self):
        listing_set.prepare(self.args)
        self.args.width,self.args.height=60.,80.
        with self.assertRaises(ValueError):
            listing_set.prepare(self.args)
        self.args.width,self.args.height=50.,60.
        self.args.packaging="actual plain cardboard box"
        with self.assertRaises(ValueError):
            listing_set.prepare(self.args)

    def test_finish_packages_nine_images_and_truthful_notes(self):
        out,config,jobs=listing_set.prepare(self.args)
        for job in jobs:
            if job["id"]=="02":
                continue
            im=Image.new("RGB",(500,500),"white")
            ImageDraw.Draw(im).rectangle((80,30,420,470),fill="#3f7256")
            im.save(out / job["out"])
        with contextlib.redirect_stdout(io.StringIO()):
            Image.new("RGB", (500, 500), "red").save(out / "08-revision-v2.png")
            (out / "selected-images.json").write_text(json.dumps({"08": "08-revision-v2.png"}))
            listing_set.finish(out,config,jobs)
        with Image.open(out / "08-gift-presentation-labeled.png") as gift:
            self.assertEqual(gift.getpixel((10, 10)), (255, 0, 0))
        notes=json.loads((out / "delivery-notes.json").read_text())
        self.assertEqual(len(notes["images"]),9)
        self.assertFalse(notes["production_ready"])
        self.assertEqual(notes["factory_native_ppi_at_selected_size"],[2.,2.])
        self.assertEqual(notes["images"][7],"08-gift-presentation-labeled.png")
        with zipfile.ZipFile(out / "listing-set.zip") as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(sum(name.endswith(".png") for name in archive.namelist()),9)
        with Image.open(out / "02-size-guide.png") as im:
            self.assertEqual(im.size,(1600,1600))

    def test_size_image_centers_blanket_and_draws_inches_only(self):
        out,config,_=listing_set.prepare(self.args)
        Image.new("RGB",(100,120),(0,128,0)).save(out / "01-white-background.png")
        drawn=[]
        original=ImageDraw.ImageDraw.text
        def record(draw,xy,text,*args,**kwargs):
            drawn.append(text)
            return original(draw,xy,text,*args,**kwargs)
        with patch.object(ImageDraw.ImageDraw,"text",record):
            listing_set.size_image(out,config)
        self.assertEqual(drawn,["BLANKET SIZE","50 in","60 in"])
        with Image.open(out / "02-size-guide.png") as image:
            difference=ImageChops.difference(image.convert("RGB"),Image.new("RGB",image.size,(0,128,0))).convert("L")
            bbox=difference.point(lambda value: 255 if value==0 else 0).getbbox()
        self.assertIsNotNone(bbox)
        self.assertAlmostEqual((bbox[0]+bbox[2])/2,800,delta=0.5)
        self.assertAlmostEqual((bbox[1]+bbox[3])/2,800,delta=0.5)

    def test_scene_scale_accounts_for_all_four_skus(self):
        for width,height in [(30,40),(40,50),(50,60),(60,80)]:
            with self.subTest(size=(width,height)):
                scale,prompts=listing_set.scene_scale(width,height)
                sofa=scale["sofa"]
                self.assertEqual(sum(sofa[k] for k in ("back_run","seat_run","front_drop","folded_length")),height)
                self.assertAlmostEqual(sofa["width_fraction"],width/72)
                self.assertLess(sofa["front_drop"],sofa["seat_height"])
                self.assertEqual(2*scale["bed"]["side_margin_each"]+width,60)
                self.assertEqual(scale["bed"]["uncovered_head_length"]+height,80)
                self.assertLess(scale["washer"]["gathered_width"],scale["washer"]["door_opening"])
                self.assertEqual(set(prompts),{"sofa_scale","bed_scale","person_scale","wash_scale"})


if __name__=="__main__":
    unittest.main()
