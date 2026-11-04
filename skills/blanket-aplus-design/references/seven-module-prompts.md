# 新版七模块提示词与分工

默认visual-v4，引擎和high质量不变。成品无字场景使用[scene-prompts-v4.json](scene-prompts-v4.json)，scene_context写当前图案、尺寸与家具参照。定制按[custom-seven.md](custom-seven.md)单独编写，保留实际照片、格数与分隔线。

## 共用要求

```text
Create one coherent A+ campaign for this actual blanket parent. Preserve supplied
designs, photo layouts, colors and borders. Final images are 970x600 with exact
English typography composed locally. No brands, logos or watermarks. Generate
photographic scene materials without text or graphic sidebars. Reserve natural
quiet background at the specified text coordinates. Match actual product size.
Never invent construction, packaging, care claims or customization features.
```

## 01 主视觉

完整家居摄影，毛毯是第一焦点；保留家具未覆盖区域作为比例参照。文字区域默认`[100,25,345,170]`，可用text_layout调整，prepare同步写入场景提示词。成品标题示例`Printed flannel\nblankets.`，副标题按实际款数写`4 prints. 4 sizes.`。秋收图案、50×60场景、灰沙发均不是固定产品参数。

## 02 细节

成品标题示例`The print,\nup close.`；`labels[1]`写已确认材质，如`Polyester flannel`。左侧完整正面标出选区，右侧大幅放大原图像素，标`Enlarged print detail`。有实物微距时登记detail_photo，改为独立`Fabric detail`，不画虚假选区对应。不生成虚构绒毛或工艺。定制仍展示布局/照片/尺寸选择说明，保留示例声明。

## 03 款式

成品标题示例`Find your favorite print.`，副标题按实际款数，如`Four designs. Four sizes for each.`。原正面图不重绘、不裁主体；1–4款一行、5–10款两行，末行居中。四款短名称可两行，多款用稳定Style编号。定制标真实照片数，同照片数不同布局加Layout A/B；不暗示购买整套。

## 04 场景

左右两张独立场景，标题和尺寸本地合成。写清家具尺寸、毯子尺寸、折叠方式、下摆终点和露出的身体部位；床面按床垫尺寸判断覆盖。小毯不画成全身款，只返工不合格场景。

## 05 尺寸

同一款四张实际原稿，同一像素/英寸比例、底边对齐；30×40、40×50、50×60、60×80英寸，数字旁标in。不用生图模型画文字，不新增年龄、床型适用保证。

## 06 洗护

完整洗衣场景，无固定右侧面板；默认文字区域`[622,35,310,220]`。人物正在放入毛毯，开口与织物比例真实。标题示例`Machine\nwashable.`，副标题`Follow the care label.`，均基于已确认事实；不新增温度、烘干、漂白或不褪色承诺。

## 07 礼赠

完整场景、自然给予和接收动作，不拉成横幅。默认文字区域`[40,30,410,205]`，产品与人物避开。标题示例`A gift for\ntheir home.`，副标题`Choose a favorite print.`。包装未知不画礼盒丝带；定制按照片/记忆表达，不套成品选印花文案。

## 检查

集中检查焦点、层级、图案身份、比例、文字、款式覆盖与375px可读性。不要默认循环调用多个审图Skill或收费接口。排版问题只改排版，场景问题只修对应素材。默认仅交付七张PNG。
