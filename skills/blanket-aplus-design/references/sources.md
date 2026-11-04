# 设计来源与边界

2026-10-28完成公开源码研究。本技能脚本独立实现，没有复制无许可项目的代码或模板。

- [xianyu110 / ecommerce-image-skills](https://github.com/xianyu110/ecommerce-image-skills/tree/f4566fdc812584425728862ad8e08c90883d81ee/skills/amazon-a-plus)：借鉴商品锁定、风格一致与模块拆分思想。上游MIT。未采用其供应商配置与无条件中心裁切。
- [LinkFox 商品图流程](https://github.com/linkfox-ai/linkfox-skills/tree/ea5581c8c727f259a4fa5ea3df00e7cec77bf5ce/skills/linkfox-aigc-imagegen-product)：借鉴卖点转具体画面、品牌视觉与商品颜色分离。上游MIT。没有接入其账户或付费网关。
- [Strict Model](https://github.com/wutaiyi815-code/amazon-aplus-strict-model-placeholder-v4-7-2)：学习语义分配参考图与恢复思路，未发现许可证，不复制实现。
- [Photoshop A+](https://github.com/wutaiyi815-code/amazon-aplus-photoshop-beta)：学习文字与素材分层，未发现许可证，不复制实现。本版不交付PSD。
- [Amazon A+介绍](https://sell.amazon.com/tools/a-content)：Basic、Premium及Brand Story不同；资格和实际模块要求需回到店铺确认。

详细检索报告位于 `<WORKSPACE_ROOT>/output/github-research/2026-10-28/blanket-aplus/毛毯A+设计Skill_检索与源码拆解.md`。该报告是背景资料，不是执行依赖。
