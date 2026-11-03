# Complete blanket listing workflow

## Inputs and defaults

Reuse the user's selected design and confirmed product facts. If no design is selected, name the design assumption and proceed with a reasonable sample. Default to the primary 50 x 60 inch SKU. Product images are square; the print remains 5:6 within them. Do not stretch the print to make a square photograph.

Ask once for missing physical details that materially affect truthful depictions: reverse material/color, included packaging, actual care instructions and substantiation of colorfastness, factory pixel/bleed/profile specifications. Continue sample creation without blocking all work: use front-only close-ups, clearly identified gift styling, no unverified performance promises, and mark factory readiness as unconfirmed. Save the known facts in product.json. For confirmed packaging, pass --packaging with the factual description; a new packaging configuration needs a fresh output folder.

## Fixed nine deliverables

| Slot | Deliverable | Important constraint |
| --- | --- | --- |
| 01 | White-background front photograph | Exactly one fully unfolded blanket, complete artwork, pure white background, no text/props, realistic hem and short-pile texture. Check current marketplace/category requirements before claiming listing compliance. |
| 02 | Size image | Center the blanket itself on both canvas axes. Equal side margins; arrows and labels outside. Inches only (e.g. 50 in, 60 in), no centimeters. |
| 03 | Sofa scene | Declare sofa dimensions and calculate the selected blanket's width coverage and length consumed by back, seat, front drop and folds. Keep uncovered seating and sofa arms visible. |
| 04 | Bedroom scene | Reference a 60 x 80 inch queen mattress and compute margins/coverage from the actual SKU; do not turn a smaller throw into a bedspread. |
| 05 | Adult model usage | Use a 66-inch adult scale reference and approximately 40-inch lap-to-ankle surface path; allocate the actual fabric length to coverage and folds. |
| 06 | Textile detail | Raking light, a focused patch of fine short nap, narrow stitched hem and shallow supple fold; emphasize material rather than just magnifying the illustration. Front-only unless backing is confirmed. |
| 07 | Machine-wash illustration | An adult actively loads the blanket with both hands into an open washer. Use a 27-inch washer, 18-inch opening and 66-inch adult as scale references; gather the real-sized blanket rather than shrinking it. No unsupported care/performance claims. |
| 08 | Gift presentation | Include BOTH a ribbon/bow and a gift box, sized to a realistically folded blanket. Match confirmed packaging; extra elements remain styling props. Show a cropped part of the print on the folded top, not a miniature full design. |
| 09 | Flat factory artwork | Exact approved print without product scene, captions, folds or mockup texture. Retain original bytes and checksum. |

## Execution and consistency

These are standing user preferences, not one-batch suggestions. The 01 white-background prompt and 09 factory-artwork template remain as approved. Scene dimensions are explicit staging assumptions, not measured facts about the user's furniture. `scene-scale.json` records the anchors and calculated ratios for every selected SKU. At 50 x 60 inches, the blanket occupies about 69.4% of a 72-inch usable sofa width; on the queen mattress it leaves 5 inches on each side and 20 inches toward the head. Recompute for 30 x 40, 40 x 50 and 60 x 80 rather than reusing the 50 x 60 coverage.

Show scale anchors in the picture, but do not print those staging measurements on lifestyle images. Do not force the whole design to remain visible if physically realistic folds obscure it. Prompt ratios guide generation; they do not guarantee geometrically exact rendered dimensions. Inspect coverage against visible furniture/person references and revise images with implausible scale before accepting them.

1. Generate or reuse one approved flat artwork. Use print-master-prompt.txt for new designs and substitute the product's motif, palette, style and ratio. Record the exact prompt. Never derive the factory art by cropping a sofa photograph.
2. Prepare a fresh set folder with listing_set.py --stage prepare. The tool freezes the source checksum and product settings, expands all eight prompt templates and saves an identical factory copy. If parameters change, use a new folder; never silently mix designs under an old filename.
3. On first use of reference editing, run --stage primary and inspect the actual main photo. If the provider rejects image editing, stop the dependent batch; do not pretend text-only generation is an equivalent reference workflow.
4. Run --stage generate (or default --stage all for a working workflow). API images use the same approved artwork, provider and model; the gift photograph uses gift-top-reference.png, a crop matching the folded top, to avoid a miniature full design. Credentials stay in child-process environment; no secret goes into prompts or logs.
5. Run --stage finish if generation was staged. Size image measurements are rendered by Pillow rather than the image model. Build a nine-image contact sheet and gallery, plus a ZIP with the exact prompts and delivery notes.
6. Inspect all nine images. Compare motif count, major shapes, print placement/color, physical scale, hands, washer geometry, readable lettering, clipping and fabric claims. Request targeted new versions for actual defects. Save exact revision jobs as revision-*.jsonl, and put selected replacements in selected-images.json, e.g. {"06":"06-fabric-detail-v2.png"}. The finish stage uses those files in the gallery and ZIP, retaining originals. Do not regenerate accepted images merely for more variations.

## Factory handoff

For normal single-reference and folder requests, use `scripts/workflow.py run` as the unified entry point. It coordinates the preparation, generation and finish stages above. Use its `revise`, `select` and `summarize` commands for revisions and final packaging; see [execution.md](execution.md). The lower-level listing_set.py stages remain available for compatibility and troubleshooting.

Keep the native artwork. Record pixel dimensions and effective PPI at the chosen physical size, color mode and whether bleed/profile requirements are known. A 1145 x 1374 image at 50 x 60 inches is only 22.9 PPI; it is a design reference, not a verified production-ready master. Explicitly state that limitation.

When the printer supplies requirements, create a separate production export. For example, 50 x 60 inches at 150 PPI requires 7500 x 9000 pixels before bleed; 300 PPI requires 15000 x 18000. Do not silently upscale and advertise newly created fine detail. Label any interpolated file and recommend a physical proof. Do not assert that sRGB, CMYK or a DPI value is universally correct for every textile printer.

## Delivery

Show the contact sheet inline, link the gallery, nine-image ZIP and updated skill package. State which images are confirmed product representations versus concepts, the real native resolution and any unfulfilled factory specification. This skill creates local artifacts; it does not upload listings or submit a production order.
