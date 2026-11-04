# v1.0 本机验证记录

2026-10-30，Python 3.14、Pillow 12.2.0、numpy 2.4.6。

- 三种模式artwork/background/both通过本地合成检查；非矩形画稿透视方向检查通过。
- 过期原图哈希、画稿碰到保护区、交叉四边形、产品蒙版遗漏保护结构和覆盖已有输出目录均被拒绝。
- 当前用户加厚标准款、纲丝脚、银色磨砂、黑色磨砂的主图1逐一完成技术回归：底座及右侧背面展示像素未变。
- 使用合成色块作测试画稿，未调用付费生成；不是婚礼/展会商业样张。第一款成图已目视检查基础贴图与结构保留，生产级画面边界仍须细化，不能把保守测试坐标当成正式模板。
- 换背景与双替换模式通过合成夹具测试，尚未在真实婚礼/展会背景上验收光照、透明边缘及接触阴影。自动抠图、产品换角度、移动/缩放产品不属于已验证能力。

证据目录：`<WORKSPACE_ROOT>/output/product-image-restyle/2026-10-30/skill-verification-02/`。配置与逐图报告在对应run的`.work/`，总记录为`verification.json`。此目录不是交付图库。

重测命令：

```powershell
& '<PYTHON>' -X utf8 '<CODEX_HOME>/skills/product-image-restyle/scripts/verify.py' --out '<WORKSPACE_ROOT>/output/product-image-restyle/<新任务目录>' --real-root 'D:/涂总项目/易拉宝/易拉宝4款1030/原图'
```

real-root可省略，此时只验证确定性本地合成。若原图已经改变，实图回归需重新识图确认坐标，不将测试脚本中的旧坐标自动用于新图。
