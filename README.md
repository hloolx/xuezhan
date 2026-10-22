# 血战文明 · CivWar

一款受 Flash 小游戏 **《战争进化史》（Age of War）** 启发的 3D 战争进化策略游戏，使用 **Unreal Engine 5.8 + C++** 开发。沿一条战线训练部队、守住基地、建造炮塔，在扩军与升级时代之间做选择。

**这是源码开源版。代码采用 MIT 许可证；作者的 3D 模型、贴图、骨骼、动画和美术源文件属于私有资产，不随仓库发布，也不在 MIT 授权范围内。** 公开版本使用程序化占位外观，可以研究和修改完整的游戏规则、界面及联机实现。

**[学 AI，上 linux.do](https://linux.do/u/hlool/)** · 作者：[hloolx](https://github.com/hloolx)

## 玩法

- 五个时代：石器、中世纪、工业、现代、未来；15 种常规兵种、5 名时代统帅、9 种炮塔。
- 自动行军和交战，玩家决定出兵、炮塔建设、经济升级和进化时机。
- 统帅可以随军或坚守，主动释放战吼；每个时代选择国策，击杀积累老兵等级，基地危急时发动背水一战。
- 单人 AI，以及服务器权威的 1v1 IP 直连实现；中文 Slate 界面、时代展示、音量设置和配乐。
- 规则核心是独立 C++20 模块，不安装 Unreal Engine 也能编译并运行模拟测试。

## 参考了哪些游戏

| 作品 | 本项目参考的方向 |
|---|---|
| [《战争进化史》Age of War — Louissi](https://www.kongregate.com/games/louissi/age-of-war) | **主要玩法灵感**：单线基地对抗、出兵自动战斗、炮塔防守、从原始时代向未来进化。 |
| [《吸血鬼狂刀》Vampire Slasher — Kingkong Games](https://www.moddb.com/games/vampire-slasher) | 角色与部队配合、主动技能和成长的设计参考。这里指原版 Vampire Slasher。 |
| [《帝国时代》系列](https://www.ageofempires.com/) | 资源投入、兵种克制、升时代时机的策略取舍。 |
| [Thronefall](https://store.steampowered.com/app/2239150/Thronefall/) | 精简建设操作、突出指挥和守城决策的设计思路。 |

本项目为独立实现，与上述作品及其开发商没有官方关联。上述名称用于说明玩法和设计灵感；本仓库不提供这些游戏的源码、美术或音乐，相关权利归各自权利人所有。

## AI 参与和素材来源

本项目在设计、编码、工具脚本和调试过程中使用了 AI 辅助。美术制作采用 **AI 参考图 → Tripo 生成 3D 网格/PBR 纹理 → Blender 整理与动作制作 → Unreal 集成** 的流程。模型并非全部手工从零建模，也不是生成后不经处理即可使用。

| 内容 | 来源与公开范围 |
|---|---|
| 游戏代码、工具脚本、数值与文档 | AI 辅助开发，由项目维护者整理；本仓库项目自有部分按 MIT 开源。 |
| 完整版角色、基地、炮塔、载具、环境模型和纹理 | Tripo AI 生成，后续进行了网格清理、尺寸与 UV 整理、绑定修复、队色材质和动画处理；**作者私有资产，不上传、不授权再分发**。 |
| 设计参考图 | 制作记录使用 ImageGen 辅助确定外观与多视图；参考图和提示词生产包不公开。 |
| 源码版占位外观与基础音效 | 由项目代码、基础形体和音效合成脚本生成；不是从参考游戏提取的素材。 |
| 背景音乐 | Scott Buckley 的 Titan、Legionnaire (Original)、Juggernaut，**CC BY 4.0**。 |
| UI 边框 | Kenney 的 Fantasy UI Borders，**CC0**。 |
| 中文字体 | Noto Sans SC，**SIL OFL 1.1**。 |
| 完整版部分战斗采样 | 344 Audio / Sonniss GDC 2026；许可限制素材再分发，**本仓库不包含原件或派生采样**，使用已有合成音效回退。 |

完整作者、来源链接、加工记录和许可证边界见 [CREDITS.md](CREDITS.md) 与 [素材说明](Docs/ASSETS.md)。**音乐、字体、UI 边框分别遵循原许可证，不能统一按 MIT 使用。** 引擎自身也不属于本仓库的 MIT 授权内容。

## 快速开始

### 只运行规则测试

需要 Windows、Visual Studio 2022 C++ 工具链、CMake 3.20+ 和 Python 3。不需要 Unreal Engine，不需要私有模型。

```powershell
git clone https://github.com/hloolx/xuezhan.git
cd xuezhan
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 simtest
```

测试会校验数值表结构、编译规则核心，并运行自动测试和 AI 对局。GitHub Actions 使用同一套规则测试。其他平台可以用 `Tests/SimHarness/CMakeLists.txt` 构建，尚未在本次发布中验证。

### 启动游戏

需要 **Unreal Engine 5.8**、VS 2022 C++ 工具链、Windows SDK；本地原工程使用 UE 5.8.3，构建环境还安装了 .NET Framework 4.8.1 SDK。建议克隆到纯英文路径，如 `D:\Projects\xuezhan`。

```powershell
# 按你的实际安装位置修改；也可以向脚本传入 -EngineRoot
$env:UE_ROOT = 'C:\Program Files\Epic Games\UE_5.8'

# 编译编辑器目标，并准备地图、基础材质与音频
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 setup

# 启动主菜单；无私有资源时，脚本自动添加 -cwlegacyart
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 run
```

也可双击根目录的 `启动游戏.cmd`。若直接从编辑器或打包程序启动，可添加 `-cwlegacyart`；公开仓库未包含正式美术，**画面与作者的完整版不同**。工程已包含可公开的基础音效和配乐；需要重建基础音效时先运行 `python Tools/gen_sfx.py`，再执行 `content`。

### 常用操作

| 操作 | 按键 |
|---|---|
| 移动 / 缩放镜头 | A、D / ←、→ / 屏幕边缘；鼠标滚轮 |
| 训练兵种 | 1 / 2 / 3 |
| 升级时代 / 金矿 | U / E |
| 施放技能 | Q 后左键选择落点；右键或 Esc 取消 |
| 部队推进 / 驻守 | F |
| 统帅随军 / 坚守；战吼 | G；R |
| 指定统帅位置 / 对准统帅 | 右键战场或小地图 / C |
| 回到己方基地 / 背水一战 | 空格或 H / L |
| 战局菜单与声音设置 | Esc |

炮塔、训练队列、国策等也可以通过界面操作。

## 联机与开发

```powershell
# 两个终端分别执行，或者在游戏内创建 / 加入房间
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 host
powershell -NoProfile -ExecutionPolicy Bypass -File Tools\civwar.ps1 join -Address 127.0.0.1
```

局域网连接填写主机局域网 IP，默认端口为 UDP 7777。公网直连需要对应的网络配置；房间列表、NAT 穿透尚未接入。源码公开不代表已完成公网、发布包或全平台验收。网页试玩未开放。

```text
Source/CivWar/Sim/       纯 C++ 规则核心与 AI
Source/CivWar/Game/      对局流程、玩家与服务器权威逻辑
Source/CivWar/Net/       网络同步
Source/CivWar/View/      镜头、程序化模型、表现与音频
Source/CivWar/UI/        中文 Slate 界面
Content/Data/           游戏数值 JSON
Content/Fonts/          Noto Sans SC 与许可
Content/Audio/          可再分发的合成音效与 CC BY 配乐
Content/Licenses/       第三方署名和许可证
Tests/SimHarness/       无引擎依赖的规则测试
Tools/                  构建、内容生成与美术处理工具
Docs/                   规则、联机、素材、开发说明
```

- [设计与规则](Docs/DESIGN.md)
- [联机实现](Docs/NETWORK.md)
- [构建、测试与贡献](Docs/DEVELOPMENT.md)
- [素材公开范围](Docs/ASSETS.md)
- [致谢与来源](CREDITS.md)
- [MIT 许可证](LICENSE)

欢迎通过 Issue 反馈问题或提交 Pull Request。涉及新素材时请附上作者、来源和许可证；不要将本项目私有模型或来源不明的素材提交进来。
