# 标定、合成与复用

标定和新画稿/背景设计先按[设计适配](design-review.md)明确焦点与允许改动区域；这是原有合成流程的设计约定，不是额外模型调用。

工程放 `<WORKSPACE_ROOT>/output/product-image-restyle/<日期>/<任务>/`，每次输出到不存在的新目录。原商品文件不改写。输出目录的`final.png`仍需视觉验收，工程中的`check.json`不会自动标成可交付。

## 配置

全部输入路径使用绝对路径；source_sha256用`Get-FileHash -Algorithm SHA256`获取。坐标基于EXIF归正后的源图像素，顺序为左上、右上、右下、左下，坐标不得超出画布。每张图单独标定，不因文件名相同就复用。

```json
{
  "mode": "artwork",
  "source": "D:/project/source.jpg",
  "source_sha256": "实际64位SHA256小写值",
  "canvas": [1600, 1600],
  "protected_mask": {"polygons": [[[170,1425],[720,1425],[720,1490],[170,1490]]]},
  "artwork": "D:/project/artwork.png",
  "quad": [[180,166],[707,166],[707,1423],[180,1423]],
  "artwork_ratio": 0.42083,
  "artwork_fit": "contain",
  "artwork_matte": "#ffffff",
  "source_notes": "产品原图由用户提供；画稿自行设计；规格按本次资料确认。"
}
```

坐标仅解释格式，不是可直接套用的通用模板。默认contain留边、不裁文字；cover会中心裁切，必须视觉检查。artwork_ratio是本次画稿宽/高的实际设计比例，可省略以沿用画稿自身比例，不能把示例比例当成所有易拉宝规格。

`protected_mask`必填，标注所有不能改变的产品结构；由`polygons`填充，可通过`exclude_polygons`挖空。也可以用`path`指定同尺寸L模式灰度PNG，255为保护，0为不保护；工具将非零值都视为硬保护。四边形画面不可碰到任何保护像素。保护区不是自动识别结果。

background/both另需：

```json
{
  "background": "D:/project/background.png",
  "product_mask": {"path": "D:/project/product-alpha.png"},
  "shadow": "D:/project/contact-shadow.png"
}
```

product_mask用同尺寸灰度PNG，255保留产品、0换背景，边缘灰度抗锯齿。也支持polygons/exclude_polygons（4倍超采样）。保护区必须完全在实心产品内，both模式广告四角内也须为实心产品，避免广告贴到背景。阴影可省略；如提供必须是同尺寸透明RGBA PNG，合成在背景之上、产品之下。没有合适阴影时不能把技术通过当成视觉通过。保留源图光照条件，背景应匹配产品，不对保护区做整体调色。

```powershell
& '<PYTHON>' -X utf8 '<CODEX_HOME>/skills/product-image-restyle/scripts/compose.py' --config 'D:/project/edit.json' --out 'D:/project/run-01'
```

输出final.png、.work/source.png、product.png、protected.png、edit-mask.png、可选product-alpha.png、mobile.png及配置/校验。不会覆盖已存在输出目录。先完成校验再写结果。保存输入文件哈希；素材变化就重做校验。

## 新背景及画稿

复用 `<CODEX_HOME>/skill-library/image-runtime/generate.py`，不复制提供商配置、密钥处理或请求代码。JSONL每行：

```json
{"out":"background.png","prompt":"Create an original wedding reception interior, eye-level camera, soft frontal daylight. Keep a clear floor area in the specified product position. No banner stand, no text, no logos. Use the reference only for broad color and lighting direction, with a different room layout.","quality":"high","size":"1024x1024","images":["D:/project/inspiration.jpg"]}
```

按实际产品位置、相机高度、场景主题改写提示词。商业素材优先使用授权资产；未明确授权的灵感参考不直接粘进输出。制作新画稿时只生成画面所需插图，名字、日期、标题等本地排版。已有可用画稿直接贴入，不再次生成。

共享运行入口：`--input <jobs.jsonl> --out-dir <raw> --quality high --concurrency 2 --dry-run`，明确作图请求下检查通过后去掉dry-run，使用skip-existing恢复。新背景先裁切/规范到源图尺寸并验收，不让合成器暗中拉伸。本地贴图不需要调用模型。

## 验收与再利用

查看原图、final、375px图，检查支脚/背杆/横杆、白边、画面与金属遮挡关系、文字、接触阴影；源图有失真时指出，不能承诺修复成真实产品。新建review.json记录final_sha256、product_structure、artwork_text_and_crop、edges、perspective、lighting_and_contact、mobile_readability、source_rights和status。只有实看后写结论，失败项不得全标通过。

同源图换画稿：保留坐标/保护区，更新画稿与来源，无须新生图。换背景：保留已审核的产品蒙版，核对新背景角度光线及阴影。换原图：SHA不同必须重新标定，不绕过校验。需要旋转、移动或缩放产品是未来单独验证的操作，v1.0不隐式执行。
