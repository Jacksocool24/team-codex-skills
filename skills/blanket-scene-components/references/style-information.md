# 视觉风格配置与信息表达组件 v1.0

这是v2.1的可选本地后处理能力。构图库与背景库保持各自目录、版本和调用方式；不重绘商品，不改变背景像素。当前实际验证来自第三条链接的4款成品毛毯和固定扇形构图，不代表已验证全部主题、10款或定制照片。

## 两类配置

- `assets/visual-styles/catalog.json`：清爽家居、家居编辑风。记录字体、字号层级、文字与强调色、局部对比度门槛。商品与背景不可为配色而调色。色彩和字体是可选方向，不强制所有父体都用绿色或衬线。
- `assets/information-components/catalog.json`：产品识别标题、选款事实条、款式定位标签、尺寸规格条。内容来自已确认事实和实际款式矩阵；不得因为有组件就增加未知性能、洗护、认证或包装。

字体读取本机Windows Fonts。缺字体应选择已验证替代方案并重审，不静默回退，不复制字体到部署包。新增宿主或云端字体使用另核授权；本次仅使用已安装字体渲染PNG，无字体分发。

## 输入与运行

`<PYTHON> -X utf8 <技能>/scripts/style_information.py --config <config.json> --out <新工程目录>`。

config包含style_id、base_manifest和facts的绝对路径及SHA256、需要启用的components。组件id/variant见catalog。既有基线文案用baseline变体；产品类别用product-name变体；款数和尺寸数量用counts变体。size-line可选，不要求每张都显示四个尺寸。

base_manifest保存：
- parent_key、mode，必须与facts一致。
- frame：本地排版生成的无字products-composite.png及SHA256；不使用已经有字的成图作为底图。
- template：同构图template.json及SHA256。
- layers：每款970×600透明产品层的路径与SHA256，用来保护产品区域。
- products：与slot.index一一对应的id和label，另保留源图路径与SHA256。
- default_label_y及原始copy.headline/copy.subline。

facts包含同父体的事实条目和product_matrix。条目形如`{value:4,status:verified_from_assets,evidence:实际证据说明}`。product_name必须有用户确认；不能仅凭AI生成图猜材质。design_count和sizes_inches必须与矩阵的唯一设计×尺寸组合一致，不能重复或漏项。支持状态为user_confirmed、verified_from_assets、user_and_metadata_confirmed；状态是证据登记，不是脚本自行鉴定商品真实性。

每项矩阵记录design_id、size_inches、evidence。保留资产性质：原始图案参考、生成白底图、生成场景、真实实拍分开登记。名称含fabric-detail或factory-artwork不能证明实拍或可生产。

## 控制变量与验收

首轮基线来自原扇形成图；B版只改文字样式并保留文案；C版沿用B的风格，换为产品识别和精简事实表达；D版保留C的内容，用另一风格。C同时改变信息表达与该组件的强调层级，因此不声称单独测出了文案因素的贡献。

代码对比最终图与无字底图：文字区外和产品区域变化像素均应为0，保持产品位置、旋转、比例、叠放和阴影不变。记录输入、字体、配置、成图哈希；保护层与背景改变时须重做审核。采样文字覆盖处的前景/背景对比度，不能把算法通过等同于所有手机都可读。

检查970×600与375px，核对标题是否明确、信息是否重复、文字是否抢产品、标签是否对应正确、颜色是否有足够对比。质量通过与用户风格偏好分别记录；未经用户选择，不自动把试验中的某套风格替换所有默认输出。

输出仍为最终PNG；内部保留文字层、风格、组件、数字校验与简短视觉审核。已核验图册位于`<WORKSPACE_ROOT>/skill-library/visual-information/v1.0/`；产品素材档案位于`<WORKSPACE_ROOT>/skill-library/product-assets/third-listing-seasonal-four/v1.0/`。其他父体使用独立档案，不沿用这个父体的事实值。

## 已知资料缺口

本轮52项文件包含4张原始设计参考和16个款式×尺寸组合的白底、图案、生成细节图。没有核实材质实拍、背面、厚度、克重、洗标。文件名09-factory-artwork对应元数据print_ready=false，不能用于承诺工厂直接生产。素材档案逐项记录这些限制。
