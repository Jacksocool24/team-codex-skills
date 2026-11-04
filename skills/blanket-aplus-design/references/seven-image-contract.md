# 七图项目合同

## v4 新版视觉与精简交付

新简报使用`layout: visual-v4`，省略时也默认此值。旧版仅显式历史恢复可用。默认render不生成文案、HTML、CSV或ZIP；用户交付用export，仅输出七张PNG。以下文件说明中copy/preview/CSV/package均为按需扩展。

scene可提供`reuse_from: 旧campaign工程绝对路径`。仅复用同名已完成场景，核对品牌、父体、成品模式、整体风格、款式、尺寸、画布、完整提示词与参考图哈希。原结果复制后记录源工程指纹和文件哈希。更改提示词或产品不能复用。

默认最多2并发，单进程统一写状态。一个任务失败保留其他成功结果，先调查再局部重试。模型及high质量不变。使用export前要求逐图review有匹配哈希和通过记录，尚未解决的问题不能标true；后台适配待核对不等于设计缺图。

新版detail_crop基于裁掉外侧白边的front归一化裁切，默认选下部含边缘区域，并显示对应选区。不能沿用旧版相对于未裁边图的坐标。可选detail_photo需path/confirmed/source。裁切不能当作实拍微距。文字区域和证据要求见[visual-v4.md](visual-v4.md)。

新项目使用scripts/campaign.py，prepare需新空目录。内部借用workflow生成，但最终七图由新排版器输出。

## 简报

- schema_version=2、profile=parent-seven、layout=visual-v4、product_mode=finished或custom。custom按[定制七图分支](custom-seven.md)提供customization和design.photo_count；将模式与照片数量传给底层生成项目，不沿用成品identity_lock。
- name、brand、parent_key、style为非空文本。
- brand仅保留于内部记录，七图禁止显示品牌名、商标和水印；style及scene提示词不携带品牌名，可见文案校验拦截当前品牌名，最终还需目视核对。
- sizes严格为`[[30,40],[40,50],[50,60],[60,80]]`。
- palette含ink/accent/paper三个十六进制颜色。
- designs每项有唯一id、英文name、可选换行short_name、front/detail图片路径、artwork字典。artwork键为30x40/40x50/50x60/60x80，值为该款该尺寸原稿路径。
- detail_design_id和size_design_id来自实际designs。
- facts按id记录value/source/confirmed，copy.claims引用的事实必须确认。
- copy恰好包含hero/details/designs/lifestyle/sizes/care/gift，每项有英文headline、alt（内部上限100字符）、可选subline/labels/footer/claims。
- hero/gift支持手工换行标题与subline；details.labels两行；lifestyle.labels对应living/bedroom；sizes.footer为系列说明；care.labels为已确认规则。
- scenes含hero/living/bedroom/care/gift，每项有design_id、shown_size、references、可选canvas。提供prompt，或prompt_template及prompt_params.scene_context。

scene示例（不是完整简报）：

```json
{
  "design_id":"01", "shown_size":[50,60], "canvas":[970,600],
  "prompt_template":"hero",
  "prompt_params":{"scene_context":"Show the supplied blanket over part of an 84-inch-wide sofa with both arms visible."},
  "references":["实际50x60白底图.png","实际50x60印花原稿.png"]
}
```

## 文件

campaign.json保存简报、来源快照和生成子项目指纹；sources保存输入；generation含任务、状态、raw和日志；assets恰好7张最终PNG。render-manifest.json、checks.json、提示词和审核留在内部工程；copy.json、english-copy.md、design-map.csv、preview.html仅按需生成，不随默认七图交付。

review.json的project_fingerprint绑定campaign；modules按七个id保存sha256、identity/scale/text/claims布尔值及具体notes。图像变化使旧审核失效。

## 恢复与修订

生成只跳过completed且哈希匹配的输出。状态不明先调查，确认失败才retry-note重试。资料/文案/提示词修订需新建目录，不能编辑campaign.json绕过指纹。纯排版代码修订可对同一输入重新render并审阅。

当前默认创建五个scene任务；复用其他已完成scene需保留可验证完成来源，不能将任意图片改名冒充API结果。ZIP为图片文案交付包，完整快照与恢复记录保留在本机，不宣称解压后可跨机器直接重跑。

## 状态

结构错误invalid禁止打包。完整设计仍标design_draft；pending列出未完成视觉审阅及后台模块/ASIN检查。该程序不发布。
