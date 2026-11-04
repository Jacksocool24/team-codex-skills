# 项目合同与命令

仅用于旧v1/schema1项目及内部scene任务；新七图项目使用seven-image-contract.md与scripts/campaign.py。

所有命令运行 `<skill>/scripts/workflow.py`。用UTF-8 JSON保存简报；相对图片路径相对简报文件解析。先查看图片并分析事实，再写简报，脚本不自动猜商品事实。

## 简报格式

下例是两个模块资产的完整结构示例。图片路径必须替换为实际文件；品牌、事实、尺寸和文案由当前任务确认，示例不是默认产品资料。`source`可以是文件加字段位置、用户确认或API快照位置，不能写虚构的“已验证”。

```json
{
  "schema_version": 1,
  "name": "blanket-basic-aplus",
  "brand": "Vxzora",
  "marketplace": "US",
  "product_mode": "finished",
  "sizes": [[30,40],[40,50],[50,60],[60,80]],
  "asins": [],
  "identity_lock": "Keep the exact approved print, border and colours from the supplied photo. No extra accessories.",
  "style": "Clear daylight, a restrained green and white room palette, uncluttered composition.",
  "facts": {},
  "modules": [
    {
      "id": "hero",
      "kind": "image",
      "purpose": "product_identity",
      "amazon_module": "Standard image header with text (design assumption)",
      "spec": {"width":970,"height":600,"max_bytes":2000000,"verified":false},
      "text_mode": "native",
      "shown_size": [50,60],
      "headline": "A pattern for your everyday space",
      "body": "Shown in the 50 x 60 inch size. Choose the dimensions that suit your space.",
      "alt": "Printed blanket draped over part of a sofa",
      "claims": [],
      "references": ["product.png"],
      "prompt": "Show this exact 50 x 60 inch blanket draped over part of an 84-inch-wide sofa. Preserve its print and border; do not cover the entire sofa. No text."
    },
    {
      "id": "sizes",
      "kind": "size_chart",
      "purpose": "size_selection",
      "amazon_module": "Standard image header with text (design assumption)",
      "spec": {"width":970,"height":600,"max_bytes":2000000,"verified":false},
      "text_mode": "native",
      "headline": "Choose your blanket size",
      "body": "Compare dimensions in inches. Shapes illustrate relative size, not print placement.",
      "alt": "Four blanket sizes drawn to the same scale: 30 x 40, 40 x 50, 50 x 60 and 60 x 80 inches",
      "claims": []
    }
  ]
}
```

增加其他模块时使用唯一的`id`，对应实际A+模块而不是强行用同样像素。一个多图模块可拆为多个资产ID，`amazon_module`记录它们属于哪个模块和槽位；交付时依此填回后台。

## 字段说明

- `facts`：`{"material":{"value":"Polyester flannel","source":"当前用户确认/资料位置","confirmed":true}}`。`claims`列出本模块引用的事实ID；未确认事实不能被引用。尺寸/品牌由顶层资料提供。代理仍需逐句检查是否遗漏声明，程序不能理解全部文案。
- `asins`：当前品牌适用的ASIN数组。未知可为空，设计不会被阻断，但不能标为已审阅可手工上传。可额外记录`skus`供人员追踪，不会自动建立Amazon关联。
- `asset`：直接使用已有图片的路径。与`prompt`二选一。`prompt`模式必须有`references`，每模块仅选必要参考。
- `shown_size`：图片中展示的一种实际售卖尺寸。尺寸图由顶层`sizes`决定。
- `text_mode`：`native`把文案输出到`copy.json`及预览；`overlay`由本地字体排到图片下方独立文字区域。后者若溢出则失败，不裁切正文。尺寸图只用native。
- 尺寸图的原生body会自动补充全部英寸尺寸，避免手机上只靠图片小数字。补充后仍检查实际字段长度限制。图内文字按手机显示宽度保留最低可读字号，放不下时缩短文案或改native，不通过无限缩字强塞。
- `spec`：必须提供width、height、max_bytes、verified。verified为true时必须有`source`与ISO日期`checked_at`；只有实际核对过店铺后台才能设true。示例970×600、2MB只是未核实设计参数。
- `text_limits`：可选headline/body/alt字符上限，来自当前真实模块。省略时不虚构通用上限；发布前补查。
- `customization`：custom模式必需，如`{"photo_counts":[1,2],"source":"用户提供的布局资料","workflow_verified":false}`。制作`purpose:"customization"`的操作模块时还须`workflow_verified:true`和`workflow_evidence`。不得只为通过校验填写true。

## 日常操作

1. `prepare --brief brief.json --out 新目录`：验证输入后建立来源快照、project.json、jobs.jsonl、空review.json；不会读取API密钥或生图。
2. `generate --project 目录`：把任务交给共享运行时dry-run，校验引用和任务格式，无付费请求。
3. 用户要求实际出图时，`generate --project 目录 --module hero --execute`。查看首模块，再继续其他模块。省略module会顺序完成所有剩余任务。已完成且哈希相符的图自动跳过。
4. `render --project 目录`：复用已有图或生成图，加独立文案，生成等比例尺寸图、预览、文案/布局与检查。部分缺图时仍写预览，退出码1并标invalid。
5. 查看图片与预览后填写review.json，再执行`check --project 目录`。未完成视觉审阅为review_required，结构错误为invalid。
6. `package --project 目录`：完整但待审阅的结果生成aplus-draft.zip；满足检查为aplus-reviewed.zip。任何结构错误禁止打包。

静态HTML双击即可打开，不需要新建开发服务器。手机/桌面检查可用Playwright打开file路径，分别设置375×812与1440×1000，检查横向溢出、文字及图片可见，并截图审阅。该预览不模拟Amazon全部响应式行为。

## 审阅记录

每个模块实际查看后，在prepare创建的review.json里增加记录；sha256来自render-manifest.json，不能凭文件存在填写通过。

```json
{
  "project_fingerprint": "原文件中的值保持不变",
  "modules": {
    "hero": {
      "sha256": "该模块当前PNG的实际SHA256",
      "identity": true,
      "scale": true,
      "text": true,
      "claims": true,
      "notes": "记录具体对照素材、尺寸依据、文字与事实检查结果；不适用项说明原因。"
    }
  }
}
```

任何一项不通过或未完成就设false，后续返工。不能将自动检查、AI自评当作产品检测或平台批准。

## 恢复与修订

`generation-state.json`记录submitted/completed/needs_investigation，收费请求前即保存。中断后先检查raw图片、共享运行日志及服务商任务状态。不要因为超时就认定服务没有执行。

若确认旧任务已经结束/失败且需要重试，在相同项目只针对该模块执行`generate --module hero --execute --retry-note "旧任务核对结果及允许重试的依据"`。仍在运行或状态不明时不要重试。已存在但无完成记录的图片需人工核实来源后恢复完成记录，不能静默认领。

修改文案、提示词、参考图、品牌或规格：从brief创建新修订目录。project/jobs/来源快照哈希变更会阻断复用；输出图片改变会使旧审阅失效。新旧交付包分开保存。

仅改文字时，将上一版确认过的raw图片作为新简报的asset，移除该模块的prompt/references，然后prepare与render。这样会复用画面，只重排文字，不再次调用生图接口。

不在项目中存API密钥。共享提供商配置和密钥路径由现有image-runtime维护，本技能不读取或输出凭证。
