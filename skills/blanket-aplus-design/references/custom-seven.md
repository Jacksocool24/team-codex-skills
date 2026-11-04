# 定制照片毛毯七图

用户明确要求定制时使用。保留共享引擎、五张无字场景、两并发、七张970×600及哈希审阅；不能把product_mode写成finished绕过检查。实际任务提示词和证据写入当次brief，不复制上一父体的示例照片。

## 输入与验证

- `product_mode: custom`、`layout: visual-v4`；`customization.confirmed: true`及`source`记录用户确认。旧lean-v3仅恢复历史工程时使用。
- `customization.photo_counts`是实际非重复照片数量列表，当前支持1至10；每个design有`photo_count`，与正面/四尺寸原稿目视格数对应。可有同一照片数的不同布局，不把文件序号自动当照片数。
- `instruction_scope: selection-only`，`example_disclosure: Example photos shown.`。当前七图只提供布局、照片、尺寸选择信息。`workflow_verified`如为false，检查保留后台待核实项。
- 核对每种尺寸下的照片格数、分隔线、裁切和边框。无来源的新增名字、文字、可编辑背景、即时预览、订单按钮、交期和打印清晰度承诺不写。
- 示例图不视为实际客户评价或真实订单实拍。未获得实拍面料细节时，不声称照片里的毛衣、皮毛或花纹是毯子真实立体工艺。

## 七模块

1. **定制主视觉**：标题明确Custom Photo Blankets，示例单照片毛毯在局部沙发上，强调Your photos。使用新版完整场景与自然墙面放字，无固定侧栏；标题尽量两行。保留原照片人物、颜色与位置，真实人物与印花人物不混淆。
2. **选择说明**：原正面示例＋`Choose a layout`、`Pick your photos`、`Choose a size`三项，非下单步骤，不加数字、按钮或模拟屏幕。`copy.details.selection_labels`固定上述三项；`labels[1]`填已确认材质。展示Example photos shown.
3. **布局总览**：使用实际正面图，逐款标注`1 photo`、`2 photos`等实际格数，不再标Style序号。十款两行五列，底部注明Example photos shown.。同照片数不同布局加Layout A/B，不丢失款式。
4. **生活场景**：少照片/宠物款用于盖膝，多照片家庭布局用于床面；示例人物或宠物保持在布料上，不变成立体物体。折叠可以遮住照片，不得增减或重新排布原有格子来填满可见区域。
5. **尺寸**：同一布局四尺寸原稿、统一像素/英寸，标题可以为4 sizes. Every layout.；不是婴儿床或具体年龄使用保证。
6. **洗护**：已确认可机洗才使用Machine washable；Follow the care label，不新增永不褪色、温度或烘干保证。
7. **礼赠**：一条示例照片毯的自然交接，强调记忆与个人情感，例如Their memories. On a blanket.；无包装证据不放礼盒丝带。

## 场景提示词约束

为五个scene提供完整`prompt`，不用含finished-print字样的成品模板原文。注明本次示例照片的人物/宠物、实际格数、行列结构及各格内容；保持照片在布料上为平面印刷。照片人数不等于照片格数。禁止增加图中文字、UI、实物照片拼贴或分隔线。场景每条绑定具体尺寸和对应原稿。

## 验收

核对新child项目确为custom并传递photo_counts；所有布局和照片数量与输入对应；说明是选款建议，未暗示已经验证在线定制功能；四尺寸、无品牌、手机关键文字、场景比例及输出哈希沿用公共检查。成品模式的输出不应因新增分支改变。
