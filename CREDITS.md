# 致谢、灵感与素材署名

维护者：[hloolx](https://github.com/hloolx) / [hlool @ linux.do](https://linux.do/u/hlool/)。

## 玩法灵感

主要参考 Louissi 的 [Age of War（战争进化史）](https://www.kongregate.com/games/louissi/age-of-war)：单线基地战、自动出兵交战、炮塔防御和时代演进。感谢这款 Flash 小游戏带来的玩法启发。

设计讨论也参考了 Kingkong Games 的 [Vampire Slasher（吸血鬼狂刀）](https://www.moddb.com/games/vampire-slasher)、[Age of Empires（帝国时代）](https://www.ageofempires.com/) 系列，以及 [Thronefall](https://store.steampowered.com/app/2239150/Thronefall/)。参考方向分别为角色与部队协作、资源与进化取舍、精简建设负担。

本项目独立开发，与这些游戏没有官方关联。此处为设计来源说明，不授予原作的商标、源码或素材使用权。

## AI 辅助制作说明

游戏设计、代码、工具和调试使用 AI 辅助；维护者负责项目整合、取舍与发布。制作记录中包括 Codex 辅助开发，以及 ImageGen 辅助参考图制作。记录没有可靠确定每张图像的底层模型版本，因此不对其作具体版本声明。

完整版主要 3D 网格和 PBR 纹理由 [Tripo AI](https://www.tripo3d.ai/) 生成，随后通过 Blender 和项目工具整理：网格清理、尺度归一、UV 与材质处理、骨架/权重修复、红蓝队色、五段角色动作和机械机构动画；部分人物使用 Tripo 返回的 FBX 骨架，部分重新本地绑定。

**这些模型、贴图、骨架、动画、参考图以及美术生产源文件是作者保留的私有资产，不包含在开源仓库中，未授予复制、提取或再分发许可。** AI 生成来源说明不等于开源授权。公开版本中的程序化占位外观由项目代码和引擎基础形体构建。

## 音乐：Scott Buckley

| 曲目 | 作者官方页面 |
|---|---|
| Titan | [Titan](https://www.scottbuckley.com.au/library/titan/) |
| Legionnaire (Original) | [Legionnaire](https://www.scottbuckley.com.au/library/legionnaire/) |
| Juggernaut | [Juggernaut](https://www.scottbuckley.com.au/library/juggernaut/) |

Music by **Scott Buckley** — [www.scottbuckley.com.au](https://www.scottbuckley.com.au/) — released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

使用位置：`Content/Audio/Music/MUS_*.uasset`。修改：原 MP3 解码为 48 kHz 双声道 PCM16，响度归一至 -23 LUFS、真峰值上限 -3 dBTP，保留完整曲目；Unreal 导入后由游戏控制音量和曲目切换。再分发时需保留作者、曲名、来源、许可和修改说明。

许可原文：[CC-BY-4.0.txt](Content/Licenses/CC-BY-4.0.txt)。这些音乐由 Scott Buckley 创作，不属于本项目声称的 AI 生成素材。

## UI：Kenney

[Fantasy UI Borders](https://kenney.nl/assets/fantasy-ui-borders)，作者 **Kenney**，采用 [CC0](https://creativecommons.org/publicdomain/zero/1.0/)。

选用 `PNG/Default/Border/panel-border-000.png`，导入为 `Content/UI/EpicBorders/T_CommandFrame.uasset`。原图未改动，游戏中进行着色和九宫格缩放；未采用示例字体或示例图。随附 [原始许可](Content/Licenses/Kenney-Fantasy-UI-Borders-CC0.txt)。

## 字体：Noto Sans SC

Noto Sans SC Regular / Bold，来源为 [notofonts/noto-cjk](https://github.com/notofonts/noto-cjk/tree/main/Sans/SubsetOTF/SC)，采用 **SIL Open Font License 1.1**。位于 `Content/Fonts/`，保留 [字体原始许可与版权声明](Content/Fonts/NotoSansSC-LICENSE.txt)。字体不改为 MIT 授权。

## 合成音效与未分发的采样

`Content/Audio/SFX_*.uasset` 来自项目脚本 [gen_sfx.py](Tools/gen_sfx.py) 的程序化合成，脚本只使用 Python 标准库，未使用第三方采样；项目自有脚本及其生成的这组音效按 MIT 提供。

完整版还用到 **344 Audio** 的 Historical Weapons Vol. 2 / Bass Drops & Downers Vol. 1，经 [Sonniss GDC 2026](https://gdc.sonniss.com/) 提供。对选段进行了重采样、滤波、淡入淡出和混音。根据 [Sonniss GDC Bundle License](https://sonniss.com/gdc-bundle-license/) 的素材再分发限制，**这些原始录音和派生 `TPSFX_*` 文件均未包含在本仓库**；现有音频代码找不到采样时回退到项目合成音效。历史署名保留在 [EPIC_ASSETS_ATTRIBUTION.txt](Content/Licenses/EPIC_ASSETS_ATTRIBUTION.txt)，不表示本仓库分发了这些采样。

## 引擎与工具

- **Unreal Engine**：Epic Games 提供，适用其 [官方许可](https://www.unrealengine.com/en-US/eula/unreal)。本仓库不分发 Unreal Engine 源码、二进制或引擎基础形体文件。
- **Blender**：用于本地美术处理，工具脚本在 `Tools/Blender/`；软件和私有处理输入不随项目打包。

MIT 仅覆盖仓库内项目自有代码、文字文档、数值配置和已明确标注的自有生成内容；第三方资源依各自许可，作者私有资产不在本次授权范围内。`Docs/images/*.png` 是完整版游戏的实机展示截图，不适用 MIT，也不授予截图中私有美术源资产的复制、提取或再分发许可，详见[截图说明](Docs/images/README.md)。
