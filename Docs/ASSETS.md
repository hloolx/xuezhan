# 素材公开范围

本仓库是从本地完整版导出的源码版本。完整来源和许可证见 [CREDITS.md](../CREDITS.md)。

| 路径 / 内容 | 发布状态 | 授权 |
|---|---|---|
| `Source/`、`Tools/`、`Tests/`、规则数值、项目文档 | 公开 | 项目自有部分 MIT |
| `Content/Art/M_CWStylized.uasset`、`M_CWWarning.uasset` | 公开：脚本生成的基础材质 | MIT |
| `Content/Maps/Battlefield.umap` | 公开：基础空关卡，战场由 C++ 构建 | MIT |
| `Content/Audio/SFX_*.uasset` | 公开：程序化合成音效 | MIT |
| `Content/Audio/Music/MUS_*.uasset` | 公开：Scott Buckley 三首配乐 | CC BY 4.0，保留署名与修改说明 |
| `Content/UI/EpicBorders/T_CommandFrame.uasset` | 公开：Kenney 边框 | CC0 |
| `Content/Fonts/` | 公开：Noto Sans SC 字体与许可 | SIL OFL 1.1 |
| `Content/ArtPilot/` | **不公开**：模型、贴图、骨架、动画等 | 作者私有，未在本次发布中授权 |
| `RawAssets/Art/`、专用美术映射、自然地形派生材质 | **不公开**：参考图、源模型、生产输入与派生美术 | 作者私有 |
| `Content/Audio/ThirdParty/`、`RawAssets/Audio/ThirdParty/` | **不公开**：Sonniss 录音及派生采样 | 第三方限制素材再分发 |
| `Binaries/`、`Intermediate/`、`Saved/`、`DerivedDataCache/`、`reviews/`、`.tripo/` | 不公开 | 构建结果、缓存或本地运行记录 |

## 公开版本如何显示

`CWModels.cpp` 使用 Unreal Engine 自带基础形体在运行时拼装角色、基地和炮塔；战场地形与环境也有程序化回退。引擎基础形体由用户安装的 Unreal Engine 提供，仓库不复制它们。私有模型未提交，因此公开源码不等同于完整版美术包。

`Tools/civwar.ps1 run/host/join/nettest` 检测不到 `Content/ArtPilot/` 时自动附加 `-cwlegacyart`。直接启动编辑器游戏或打包程序时也可以指定这个参数。私有美术映射未发布；公开打包配置已去掉对应的强制 Cook 目录。

## 扩展与工具

美术导入和处理脚本作为实现参考公开。它们经常需要自备 Blender、NumPy/Pillow 等依赖、符合脚本契约的输入和本地路径配置；仅克隆仓库不能复现作者私有资产生产流程。AI 生成工具需要使用者自己的账号和额度，某些 `--submit` 操作会消耗额度，规则测试和普通游戏启动不会调用这些服务。

新增资源请登记作者、官方下载链接、许可证、修改情况和工程路径。不要将私有模型、任务回执、带签名的下载链接、账号凭据或受限采样提交进来。
