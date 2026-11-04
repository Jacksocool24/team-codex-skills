# 执行约定

先用[设计适配](design-review.md)确定当前要改变的部件；仅改配色/文字时走现有本地风格分支，不发起背景或产品融合请求。

## 工程与模型调用

每次新工程放`<WORKSPACE_ROOT>/output/scene-components/<日期>/<任务>/`，不要覆盖历史。输入使用绝对路径并记录SHA256，保留来源类别和授权状态。首次生成后将背景规范到970×600再用于下一阶段，避免坐标随分辨率变化。

共享入口：`<CODEX_HOME>/skill-library/image-runtime/generate.py`。JSONL每行格式如下，使用真实路径和根据该图编写的英文提示词：

```json
{"out":"01-background.png","prompt":"...","quality":"high","size":"1536x1024","images":["D:/.../inspiration.png"]}
```

先运行`--input <jobs.jsonl> --out-dir <raw> --quality high --concurrency 2 --dry-run`，实际生成去掉`--dry-run`并使用`--skip-existing`。背景验收后才发起融合；融合引用数组为`[规范化背景, 指定产品参考图]`。失败后先检查共享运行记录，不盲目重复请求。不要读取或输出provider内的密钥。

背景提示词核心：灵感图只提供色调、材质、光线方向；生成不同空间。具体描述家具和机位，以970×600坐标预留产品区域与自然墙面文字区。无毛毯、人物、品牌、水印、文字或装饰图形侧栏。

融合提示词核心：第一张是待编辑背景，第二张为权威产品参考。仅改变指定产品和接触区域，保持机位家具；说明展示尺寸是视觉目标，家具未经测量不承诺精确比例。逐项写出实际照片/格序/边线，保留产品姿态、浅褶皱、可见下缘，禁止印花里的皮毛或衣物变成织物结构。仍须目视检查。

## 本地合成

调用：`<PYTHON> -X utf8 <本技能>/scripts/compose.py --config <绝对路径JSON> --out <不存在的新部件目录>`。

配置格式（坐标均为最终970×600像素；polygon必须根据实际生成图检查后填写）：

```json
{
  "id":"gray-sofa-layout-one",
  "background":"D:/.../background.png",
  "integration":"D:/.../integration.png",
  "product_reference":"D:/.../product.png",
  "polygon":[[460,245],[820,245],[835,540],[400,535]],
  "feather_px":5,
  "text":[
    {"value":"Your photo.\nYour blanket.","xy":[40,36],"size":44,"line_height":52,"bold":true,"color":"#202b2d"},
    {"value":"1-photo custom blanket","xy":[40,151],"size":28,"color":"#344044"},
    {"value":"Example photos shown.","xy":[40,191],"size":24,"color":"#405154"}
  ],
  "mode":"custom",
  "source_notes":"Background generated from inspiration; product supplied mockup; no material macro.",
  "layout_notes":"One photo; preserve faces and hands; shallow drape."
}
```

只对定制产品写custom/example photos；成品按实际印花描述。输入背景必须精确970×600；融合原图按中心裁切统一，合成前先目视确认裁切不会切掉产品。文字大小不是可读性的充分条件，375px必须查看。配置必须有文本，否则按用户无字需求显式设`text: []`。

程序保存输入快照、配置、蒙版、产品接触图层、合成图、文字层、成图、375px图和校验JSON。它不调用模型，也不会自动把视觉审核标记通过。不得以自动检查无异常代替视觉审核。

审核后另写`review.json`，至少包含`final_sha256`、`layout_pass`、`photo_identity`、`drape_and_contact`、`mobile_readability`、`material_evidence`、`reuse_scope`及`status`。照片有重绘时记录`photo_identity: not_exact`，状态为`layout_trial_only`，不得记为exact。成图改动后旧审核失效。交付只复制已审核的`final.png`并按组合命名；不要移动内部部件。

## 复用规则

改字：原背景、融合图和polygon不变，修改text配置后运行到新版本目录，无生图请求。脚本会重建同一合成图，输出可比对哈希。

换款：复用独立背景及经过检查的位置约定，生成新的融合图，重新确认polygon及逐图审核；不能复用旧毛毯层冒充换款。

换背景：需重新评估机位、光源、接触区域，不能直接粘贴含旧家具阴影的透明层。

登记：将部件背景哈希、路径、关键词、产品位置、文字区域、来源、审核路径及适用限制加入本地背景索引。当前只建立文件索引，工作台展示的是技能入口，不是图层编辑器或图库管理器。
