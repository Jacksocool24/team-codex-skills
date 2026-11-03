# 执行、检查与恢复

`scripts/workflow.py` 是单图和文件夹批量的统一入口。支持run、finish、summarize、revise、select五个子命令，`--help`显示各项参数。

## 文件夹批次

run递归扫描所有支持的图片扩展名，按文件名自然排序，保存batch-plan.json，将参考图与set-001等目录绑定。输出目录不能放在输入文件夹内，避免下次扫描把结果再次当成参考图。
每次恢复检查源文件哈希、文件清单、宽高、主题、颜色和包装配置，变化则要求新输出目录。

比率适配完成后会检查目标比例；模型输出比例不符合时停止，以便单独修正适配印花。不要通过直接拉伸或无审查裁切继续生成。
`--dry-run`只扫描输入、验证配置并输出任务计划，不创建目录、不读取密钥、不发请求。

## 局部返工

先检查不合格图片，保存准确的修订提示词为UTF-8文件。使用原印花或实际局部裁切作为参考，只重做问题槽位：

```powershell
python -X utf8 <skill>/scripts/workflow.py revise --folder 'D:\path\套装\set-001' --slot 08 --prompt-file 'D:\path\gift-revision.txt' --reference 'D:\path\套装\set-001\gift-top-reference.png'
```

返工自动使用新版本文件名，不覆盖原图，也不自动采用。查看生成文件后，确认图案、比例、材质、手部和构图正确，再执行：

```powershell
python -X utf8 <skill>/scripts/workflow.py select --folder 'D:\path\套装\set-001' --slot 08 --image '08-revision-v2.png'
python -X utf8 <skill>/scripts/workflow.py summarize --output 'D:\path\套装'
```

select仅保存本地选择并重新生成九图预览/压缩包，不调用付费接口。礼品图的说明条基于选中的版本生成。
第09张不作为普通照片返工；修改印花等于修改整套产品来源，必须新建套装，以免旧照片对应新印花。

## 交付检查

每款的delivery-notes.json列出实际交付九个文件。最终ZIP恰好包含每款九张PNG，辅助参考图与未采用返工图保留在本地工作目录，不混入交付九图。
检查全部图片可读取、每套图案一致、尺寸图居中并仅英寸、场景比例合理、机洗有实际放入动作、礼品图只露出折叠局部。
核对源图和第09张的哈希、真实像素；总览和压缩包中的链接必须可用。
图像是AI商品效果图，实际材质、洗护、包装及生产清晰度需要实物核实。不要用DPI元数据或插值放大冒充新增细节。
