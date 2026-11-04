# 商品参考图提示词规则

## 主题扩展

主题扩展只补充与用户输入直接相关的元素，不替用户改变产品定位。常用扩展如下：

| 用户元素 | 可补充的视觉元素 |
| --- | --- |
| 万圣节 | 黑猫、月亮、南瓜、友好幽灵、秋叶、夜色花园 |
| 秋季丰收 | 南瓜、玉米、苹果、稻草人、向日葵、麦穗、暖色落叶 |
| 冬日 | 木屋、雪松、松果、雪地、壁炉、暖灯、冬季夜空 |
| 春夏 | 野餐、花朵、蝴蝶、樱桃、格纹、草地、晴天 |
| 海岸 | 贝壳、海浪、灯塔、沙滩植物、蓝绿色和沙色 |

如果用户只给出产品名，使用“适合美国市场的家居装饰主题”作为弱默认，并优先生成产品表面设计，不臆造具体品牌或性能。

## 每张图的变化轴

按输出序号轮换以下构图方向：

1. 中央主视觉：一个清晰主题主体，四周有协调装饰。
2. 平衡重复纹样：多个中小元素均匀分布，适合观察满幅覆盖效果。
3. 故事性插画：前景、中景和背景有层次，但主元素仍然清楚。
4. 边框或徽章构图：中心焦点和外围装饰形成稳定边界。

数量超过 4 时循环使用构图方向，同时改变配色深浅、元素密度和留白比例。变化不能破坏主题一致性。

## 提示词骨架

配合[参考图设计适配](design-review.md)确定本批次的焦点、配色和密度。用户明确要求单幅完整画面时，不应用默认重复纹样/徽章等轮换；将约束写进`--style`并检查dry-run任务。脚本已附加主次、单画布和保留配色的基础要求，具体元素关系仍须按图填写。

每个任务提示词至少包含以下信息：

```text
Create a high-quality visual reference concept for [product].
Core theme: [user themes and carefully related extensions].
Composition variation: [one variation axis].
Market direction: appealing to US home-decor shoppers, clear hierarchy, balanced palette.
Surface suitability: [flat full-bleed artwork or product-appropriate surface design].
Keep the core motifs recognizable and inside a safe central area. Use no readable text,
logos, trademarks, celebrity likenesses, copyrighted characters, watermark, price or UI.
Do not present unsupported packaging, care claims or product performance.
```

对毛毯、地垫、地毯等印花类产品，将 `Surface suitability` 写为：`flat full-bleed textile artwork, coherent repeat-friendly decorative composition, no folds or mockup texture`。对需要展示实物形态的其他产品，改为保留真实产品轮廓和材质，不强行套用平面印花规则。

## 参考图使用

先说明参考图只用于提取主题、色彩、构图和质感方向。不要复刻品牌标识、可读文字、独特角色或其他明显受保护元素。生成前记录参考图文件路径和 SHA-256，生成后把其路径写进 manifest，便于回看来源。
