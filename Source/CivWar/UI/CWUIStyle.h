// 血战文明 - 界面风格：字体、配色、圆角面板、按钮样式
#pragma once

#include "CoreMinimal.h"
#include "Fonts/SlateFontInfo.h"
#include "Styling/SlateTypes.h"

struct FSlateBrush;

namespace CWUI
{
	// 中文字体：优先 Content/Fonts/NotoSansSC（随游戏打包，SIL OFL 1.1），缺失时退回引擎默认字体
	FSlateFontInfo Font(int32 Size, bool bBold = false, bool bOutline = false);

	const FSlateBrush* PanelBrush();      // 实色墨绿指挥面板
	const FSlateBrush* PanelLightBrush(); // 稍亮的子面板
	const FSlateBrush* WhiteBrush();      // 纯色填充（配合颜色参数使用）
	const FSlateBrush* RoundedFill();     // 圆角纯色（进度条等）
	// Kenney CC0 transparent corner frame, nine-sliced and tinted brass.
	// Decorative only: retain a dark PanelBrush underneath for readable content.
	const FSlateBrush* EpicFrameBrush();

	// 按钮：Primary 金色强调，Normal 深色，Danger 红色
	enum class EButtonKind : uint8
	{
		Normal,
		Primary,
		Danger,
	};
	const FButtonStyle& ButtonStyle(EButtonKind Kind = EButtonKind::Normal);
	// 紧凑按钮：内边距很小，用于炮塔升级/出售、训练队列等小尺寸按钮
	const FButtonStyle& CompactButtonStyle(EButtonKind Kind = EButtonKind::Normal);
	const FEditableTextBoxStyle& TextBoxStyle();

	// 配色
	extern const FLinearColor Gold;
	extern const FLinearColor TextMain;
	extern const FLinearColor TextDim;
	extern const FLinearColor TextDisabled;
	extern const FLinearColor Good;
	extern const FLinearColor Bad;
	extern const FLinearColor Warning;
	FLinearColor TeamColor(int32 Team);
}
