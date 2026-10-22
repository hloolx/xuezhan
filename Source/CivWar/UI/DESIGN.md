---
name: 血战文明 · 原生 UI
description: 战役指挥沙盘；Windows Unreal Slate 的已实现视觉系统
colors:
  gold: "color(srgb-linear 0.91 0.69 0.31)"
  text-main: "color(srgb-linear 0.94 0.91 0.8)"
  text-dim: "color(srgb-linear 0.68 0.74 0.66)"
  text-disabled: "color(srgb-linear 0.56 0.61 0.55)"
  good: "color(srgb-linear 0.48 0.84 0.6)"
  bad: "color(srgb-linear 1 0.43 0.34)"
  warning: "color(srgb-linear 1 0.73 0.31)"
  team-blue: "color(srgb-linear 0.3 0.58 1)"
  team-red: "color(srgb-linear 1 0.36 0.3)"
  panel: "color(srgb-linear 0.018 0.033 0.029 / 0.98)"
  panel-light: "color(srgb-linear 0.042 0.068 0.057)"
  button-normal: "color(srgb-linear 0.055 0.09 0.073)"
  button-primary: "color(srgb-linear 0.25 0.17 0.055)"
  button-danger: "color(srgb-linear 0.26 0.052 0.039)"
typography:
  title:
    fontFamily: "Noto Sans SC"
    fontSize: "19pt"
    fontWeight: 700
  body:
    fontFamily: "Noto Sans SC"
    fontSize: "15pt"
    fontWeight: 400
  command:
    fontFamily: "Noto Sans SC"
    fontSize: "15pt"
    fontWeight: 700
  label:
    fontFamily: "Noto Sans SC"
    fontSize: "12pt"
    fontWeight: 400
  section:
    fontFamily: "Noto Sans SC"
    fontSize: "13pt"
    fontWeight: 700
rounded:
  control: "3px"
  panel: "4px"
spacing:
  tight: "6px"
  group: "8px"
  inset: "12px"
components:
  button-normal:
    backgroundColor: "{colors.button-normal}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
  button-primary:
    backgroundColor: "{colors.button-primary}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
  button-danger:
    backgroundColor: "{colors.button-danger}"
    textColor: "{colors.text-main}"
    rounded: "{rounded.control}"
    padding: "6px 10px"
  command-panel:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.panel}"
    padding: "10px 12px"
---

# Design System: 血战文明 · 原生 UI

## Overview

**Creative North Star: "战役指挥沙盘"**

实色墨绿指挥台覆盖在真实 3D 战场上。中文信息紧凑排列，黄铜强调资源与关键操作，阵营色负责定位敌我；界面围绕训练、发展、战术和城防组织判断。

本文件仅约束 Source/CivWar/UI。依据 CWUIStyle.cpp、SCWEpicFrame.h、SCWMenus.cpp、SCWAudioSettings.cpp、CWHUD.cpp、SCWBattleHud.cpp、SCWMinimap.* 的实现及原生完成度审阅；Docs/DESIGN.md 仍是玩法规则。主要面板增加 Kenney Fantasy UI Borders 的 CC0 栅格边框，原始 panel-border-000.png（48×48）未经修改复制为 T_CommandFrame.png；来源、许可与 SHA256 记录于 RawAssets/UI/EpicBorders/selection_manifest.json。线形兵种符号和小地图仍由 Slate 绘制。

**Key Characteristics:**
- 深色实面与细边界，战场保持可见。
- 同一中文字体家族，以字重和层级区分任务。
- 真实状态、费用、进度与拒绝原因直接可读。

## Colors

墨绿与灰绿构成底层，暖浅色文字保持连续阅读，黄铜和蓝红色分别承担操作与阵营语义。

### Primary
- **黄铜**（gold）：资源、进化、关键状态、滑块把手与按钮悬停边界。
- 主操作使用 button-primary 的暗铜底，文字仍用 text-main。

### Secondary
- **阵营蓝 / 阵营红**：TeamColor(0/1)，用于基地、兵力、小地图；并非固定的“蓝色永远是我方”。
- **成功绿 / 错误红 / 警告金**：就绪、拒绝、警告等真实反馈；不能替代文字原因。

### Neutral
- **指挥台墨绿 / 子面板灰绿**：panel 与 panel-light，区分容器层次。
- **暖白 / 次级灰绿 / 禁用灰绿**：text-main、text-dim、text-disabled；禁用指令仍需保留可读的信息。

前置颜色使用 CSS Color 4 的 srgb-linear 表达 FLinearColor 原始线性通道，不能把通道直接乘 255 当作显示十六进制。侧车预览使用标准线性至 sRGB 转换，透明合成及引擎输出仍以实际截图为准。

**The Semantic Accent Rule.** 黄铜说明操作与资源，蓝红说明阵营，颜色必须伴随名称、数值或状态文本。

## Typography

**Display Font:** Noto Sans SC Bold。  
**Body Font:** Noto Sans SC Regular。字体来自 Content/Fonts，缺失时引擎默认字体仅作运行兜底。

单一家族适配连续中文和混排数字。前置 pt 对应 FSlateFontInfo 的字号输入；布局 px 仅代表 Slate 逻辑单位的可移植记法，不是截图的物理像素。未声明固定行高或等比字体阶梯。

### Hierarchy
- **Title**：国策名称与资源等主要信息采用较大的粗体。
- **Command / Body**：兵种名称、操作及设置说明使用主要阅读层。
- **Section / Label**：功能分区、类别、辅助状态按空间密度使用 11–13 号；这些紧凑文字不能成为普通正文的默认下限。
- 主菜单题名采用 58 号粗体，子页标题采用 32 号粗体；结算标题与倒计时也有专用大字号。这些场景值不提取成通用令牌。

**The Name First Rule.** 国策卡先呈现名称，再呈现分类与作用目标，最后呈现效果正文。

## Layout

PC 鼠标键盘界面，布局由 SOverlay 锚定与水平/垂直盒组合。上方两端显示基地信息，中央显示时间与小地图；底部依次为文明发展、征召部队、战术指挥、城防工事，训练区保留队列。国策选择覆盖在指令区上方，不暂停战斗。

菜单为左侧固定逻辑宽度操作面板，右侧露出 3D 场景与时代说明。首页内容宽度 410，普通子页 460，操作指南 520（均为内部逻辑宽度，不含外板内边距）；外板内边距为横向 32、纵向 26。右侧时代说明与选择区域宽度 660，仅首页显示。设置与子菜单沿用该容器并按内容滚动。战斗面板常用内边距为前置 command-panel；组内与组间以 tight、group 为主要节奏，具体边距仍随控件语义调整。

已检查 1280×720 和 1600×900 原生截图。当前组件主要为固定逻辑尺寸与锚定布局，没有移动端重排或 CSS 断点；显示缩放由 Unreal/Slate 视口链路处理，不能把截图尺寸反推为控件输入尺寸。更小窗口、高 DPI 与触屏尚未形成可继承的适配承诺。

## Elevation & Depth

靠墨绿底、稍亮子面、细描边与主要容器的黄铜折角边框区分深度，不依赖卡片投影或毛玻璃。主面板带少量透明度，但不以透明代替文字对比。部分战场叠字使用 Font 的一单位黑色描边以分离背景；这是可读性处理。

## Shapes

主面板采用 panel 小圆角，控件及子面板采用 control 小圆角。主要容器在原有底板上叠加透明折角边框；NineSlice 使用 48×48 图像与四边 0.25 margin，保留 12 逻辑单位角部。小按钮继续沿用原生圆角和描边。按钮静态描边一单位，悬停黄铜边界增至 1.5 单位；按下底色变暗。兵种使用刀、弓、盾的程序线段几何，保留共同笔画语言；这些不是 Unicode 字符或图标字体。

## Components

### Buttons
普通、主操作、危险操作共享 CWUI::ButtonStyle，分别使用墨绿、暗铜、暗红。悬停按线性 RGB 的 Base × 1.35 加偏移提亮，按下 Base × 0.7；不能在 gamma 编码值上照抄该运算。按下内边距由上下 6/6 变为 7/5，形成一单位反馈。紧凑样式用于队列和炮塔操作，默认内边距上下 2、左右 3。点击音由现有 UIClick 资源提供。

SCWCommandButton 保留禁用输入路由，同时让子内容正常绘制；费用、状态与恢复条件不能因禁用一起变暗到不可读。未定义新的通用焦点动画，继承 Slate 行为。

### Inputs / Fields
地址输入沿用 TextBoxStyle：深绿底、灰绿一单位边框，聚焦为较亮底加黄铜边框。字体由调用控件设置，输入文字为白色。

### Settings
画质与显示模式是状态选择按钮：选中项使用黄铜文字及方括号双重标记。非统一质量级别显示“自定义”；窗口状态优先读取原生窗口实际模式。

首页设置与战局弹层共用 SCWAudioSettings。五路音量均使用“标签 + 右侧百分比 + 滑块”：主音量、史诗配乐、战场音效、界面反馈、战局提示。百分比绑定真实通道；修改立即生效，捕获结束、控件销毁或停止修改 0.4 秒后保存待保存值。步进 0.05，轨道厚度 4，黄铜把手 16×20（逻辑单位）；Tab 切换、方向键微调。

全部静音独立保存状态，保留五路音量；静音与主音量为零分别显示原因。两种手动试听为战场碰撞和升级提示，同一控件内间隔至少 1.5 秒，静音时不播放，也不自动解除静音。拖动滑块不触发试听。

### Navigation & Era Preview
首页以“开始征战”为主行动，联机、指南、设置及署名入口按使用频率分层。子页用独立标题、说明和返回首页按钮建立位置；Esc 返回首页。按钮标签不自动换行，说明正文按容器换行。

五时代选择以现有游戏数据驱动名称、基地、部队与统帅的真实 3D 展示；选中项使用黄铜及括号标记。界面明确说明这只是展示，对局仍从石器时代开始。相机和模型摆位属于原生场景实现，见侧车 native.menuPresentation，不作为通用布局令牌。

### Connection & Battle Overlays
连接期间显示目标地址、等待时间和取消操作，阻止重复提交及背后菜单交互；Esc 优先取消连接，恢复联机页并保留地址。错误以真实原因文本反馈。

战局 Esc 优先取消技能瞄准，其次关闭建造菜单，再关闭已有弹层，否则打开声音与返回菜单。弹层遮罩并接管焦点，隔离战斗命令与相机输入，明确提示对局继续运行。返回主菜单需经过离开确认；取消或 Esc 关闭弹层并回到战局／房间。危险确认沿用暗红按钮，不把普通返回动作标成危险操作。

### Lobby Names
昵称输入限制为 16 个 FString 字符单位，提交时去除首尾空白，空名回退为“玩家”；项目 LocalPlayer 将该名字用于登录。房间姓名允许换行，避免长名遮挡准备状态和操作。不以操作系统用户名替代玩家选择。

### Epic Frames
SCWEpicFrame 复用 SBorder 的布局与输入契约，在内容绘制之后叠加 CWUI::EpicFrameBrush。它用于主菜单外板、时代说明条、战斗四个主要指令分区与国策选择外围；内部按钮和国策选项保持原样。底层 PanelBrush 始终保留；可选纹理缺失时仅省略装饰边框，内容与交互不受影响。运行时黄铜染色及九宫格缩放不修改源 PNG；完整绘制参数见侧车 native.epicFrame。

### Credits
主菜单通过普通按钮“音乐与素材”进入同一左侧容器中的署名页。黄铜标题下按音乐、边框、战斗采样分组显示作者、许可、来源地址及处理说明，以“返回”回到主菜单；沿用现有 Label 和按钮样式。页面列出 Scott Buckley 三首配乐、Kenney Fantasy UI Borders 与 Sonniss GDC 2026 采样，不另设网页或外部导航样式。
### Command Cards & Progress
兵种卡结合线形角色符号、热键、名称、费用与状态。队列进度和生命条由真实比例控制宽度并钳制在 0–1。国策卡使用同一按钮材质，名称优先规则适用于每张选择卡。背水一战提示最小高度 112，实际高度随内容伸展，避免固定高度裁切说明。小地图是可点击、可拖动的横向战线：己方始终在左，阵营色跟随实际队伍，统帅用白边大方块区分。

## Do's and Don'ts

### Do:
- **Do** 复用 CWUI 样式与打包的 Noto Sans SC，并核对两档原生窗口截图。
- **Do** 同时显示语义文字与颜色，禁用指令保留费用及拒绝原因。
- **Do** 使用实际游戏和原生窗口状态驱动选择、数值与进度。

### Don't:
- **Don't** 把线性 RGB 通道直接当作 sRGB 显示颜色。
- **Don't** 将类别标签放在国策名称之前，也不要新增装饰性眉题。
- **Don't** 将网页预览、引擎缺字兜底字体或当前紧凑辅助字号扩展为新的平台规范。

