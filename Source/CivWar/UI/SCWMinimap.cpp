#include "UI/SCWMinimap.h"

#include "Data/CWGameDataSubsystem.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "Net/CWBattleReplicator.h"
#include "Rendering/DrawElements.h"
#include "Sim/SimState.h"
#include "UI/CWUIStyle.h"
#include "View/CWCameraRig.h"

namespace
{
	constexpr float MinimapMargin = 34.f;   // 两端留给基地图标
	constexpr float MinimapLaneTop = 30.f;  // 车道条位置
	constexpr float MinimapLaneHeight = 26.f;
}

void SCWMinimap::Construct(const FArguments& InArgs)
{
	Controller = InArgs._Controller;
}

FVector2D SCWMinimap::ComputeDesiredSize(float LayoutScaleMultiplier) const
{
	return FVector2D(Width, Height);
}

int32 SCWMinimap::ViewTeam() const
{
	const ACWPlayerController* PC = Controller.Get();
	return PC ? FMath::Max(PC->GetTeam(), 0) : 0;
}

float SCWMinimap::LaneLength() const
{
	const ACWPlayerController* PC = Controller.Get();
	const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	return Sys && Sys->IsLoaded() ? Sys->GetData().Rules.LaneLength : 6000.f;
}

float SCWMinimap::LocalXFromWorld(float WorldX) const
{
	const float T = FMath::Clamp(WorldX / FMath::Max(LaneLength(), 1.f), 0.f, 1.f);
	const float Display = ViewTeam() == 0 ? T : 1.f - T;
	return MinimapMargin + Display * (Width - 2.f * MinimapMargin);
}

float SCWMinimap::WorldXFromLocal(float LocalX) const
{
	const float Display = FMath::Clamp((LocalX - MinimapMargin) / (Width - 2.f * MinimapMargin), 0.f, 1.f);
	const float T = ViewTeam() == 0 ? Display : 1.f - Display;
	return T * LaneLength();
}

int32 SCWMinimap::OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
	FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const
{
	auto Box = [&](float X, float Y, float W, float H, const FSlateBrush* Brush, const FLinearColor& Color, int32 Layer)
	{
		FSlateDrawElement::MakeBox(OutDrawElements, Layer, AllottedGeometry.ToPaintGeometry(FVector2f(W, H), FSlateLayoutTransform(FVector2f(X, Y))),
			Brush, ESlateDrawEffect::None, Color);
	};

	// 背景与车道
	// 自定义 Slate 绘制必须显式提供底色，MakeBox 不会替我们应用 Brush 的 tint。
	Box(0.f, 0.f, Width, Height, CWUI::WhiteBrush(), FLinearColor(0.012f, 0.025f, 0.021f), LayerId);
	Box(MinimapMargin, MinimapLaneTop, Width - 2.f * MinimapMargin, MinimapLaneHeight, CWUI::RoundedFill(), FLinearColor(0.10f, 0.15f, 0.11f), LayerId + 1);
	for (int32 Tick = 1; Tick < 8; ++Tick)
	{
		const float X = MinimapMargin + (Width - 2.f * MinimapMargin) * static_cast<float>(Tick) / 8.f;
		Box(X, MinimapLaneTop + MinimapLaneHeight + 7.f, 1.f, Tick == 4 ? 6.f : 3.f, CWUI::WhiteBrush(), FLinearColor(0.35f, 0.40f, 0.29f), LayerId + 1);
	}

	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!State || !Sys || !Sys->IsLoaded())
	{
		return LayerId + 2;
	}
	const cw::RulesDef& Rules = Sys->GetData().Rules;
	const int32 MyTeam = ViewTeam();
	const FLinearColor MinimapOwnColor = CWUI::TeamColor(MyTeam);
	const FLinearColor MinimapEnemyColor = CWUI::TeamColor(1 - MyTeam);
	const int32 Layer = LayerId + 2;

	// 双方基地（己方在左）：图标 + 生命条
	for (int32 Team = 0; Team < 2; ++Team)
	{
		const bool bMine = Team == MyTeam;
		const float BaseCenter = LocalXFromWorld(Team == 0 ? 0.f : Rules.LaneLength);
		const FLinearColor Color = bMine ? MinimapOwnColor : MinimapEnemyColor;
		Box(BaseCenter - 14.f, MinimapLaneTop - 4.f, 28.f, MinimapLaneHeight + 8.f, CWUI::RoundedFill(), Color * 0.8f, Layer);
		const FCWTeamNetState& T = State->GetTeam(Team);
		const float Ratio = T.BaseMaxHp > 0.f ? FMath::Clamp(T.BaseHp / T.BaseMaxHp, 0.f, 1.f) : 0.f;
		Box(BaseCenter - 14.f, MinimapLaneTop + MinimapLaneHeight + 6.f, 28.f, 4.f, CWUI::WhiteBrush(), FLinearColor(0.f, 0.f, 0.f, 0.7f), Layer);
		Box(BaseCenter - 14.f, MinimapLaneTop + MinimapLaneHeight + 6.f, 28.f * Ratio, 4.f, CWUI::WhiteBrush(), Color, Layer + 1);
	}

	// 己方驻守线
	const FCWTeamNetState& Mine = State->GetTeam(MyTeam);
	if (Mine.Stance == 1)
	{
		const float GateX = MyTeam == 0 ? Rules.BaseHalfWidth : Rules.LaneLength - Rules.BaseHalfWidth;
		const float HoldX = GateX + (MyTeam == 0 ? 1.f : -1.f) * Rules.HoldLineDistance;
		Box(LocalXFromWorld(HoldX) - 1.f, MinimapLaneTop - 3.f, 2.f, MinimapLaneHeight + 6.f, CWUI::WhiteBrush(), FLinearColor(1.f, 0.85f, 0.2f, 0.9f), Layer);
	}

	// 己方统帅的坚守位置
	if (Mine.ChampionOrder == 1)
	{
		const float FlagX = LocalXFromWorld(Mine.ChampionHoldX);
		Box(FlagX - 1.f, MinimapLaneTop - 8.f, 2.f, MinimapLaneHeight + 8.f, CWUI::WhiteBrush(), FLinearColor(1.f, 1.f, 1.f, 0.9f), Layer);
		Box(FlagX + (MyTeam == 0 ? 1.f : -9.f), MinimapLaneTop - 8.f, 8.f, 6.f, CWUI::WhiteBrush(), MinimapOwnColor, Layer);
	}

	// 技能预警范围
	for (const FCWSkillCastNet& Cast : State->GetSkillCasts())
	{
		const float L = LocalXFromWorld(Cast.X - Cast.Radius);
		const float R = LocalXFromWorld(Cast.X + Cast.Radius);
		Box(FMath::Min(L, R), MinimapLaneTop, FMath::Abs(R - L), MinimapLaneHeight, CWUI::RoundedFill(),
			(Cast.Team == MyTeam ? MinimapOwnColor : MinimapEnemyColor) * FLinearColor(1.f, 1.f, 1.f, 0.35f), Layer);
	}

	// 单位：按行错开，重型单位画大一号
	int32 Count[2] = { 0, 0 };
	if (const ACWBattleReplicator* Rep = State->GetReplicator())
	{
		const cw::GameData& Data = Sys->GetData();
		for (const FCWUnitNetItem& U : Rep->GetUnits().Items)
		{
			if (U.State == static_cast<uint8>(cw::UnitState::Dying) || U.Def >= Data.Units.size())
			{
				continue;
			}
			const bool bMine = U.Team == MyTeam;
			if ((U.Flags & CWUnitFlags::Champion) != 0)
			{
				// 统帅：白边大方块，叠在普通单位之上
				const float CX = LocalXFromWorld(U.X);
				const float CY = MinimapLaneTop + MinimapLaneHeight * 0.5f;
				Box(CX - 7.f, CY - 7.f, 14.f, 14.f, CWUI::WhiteBrush(), FLinearColor::White, Layer + 3);
				Box(CX - 5.f, CY - 5.f, 10.f, 10.f, CWUI::WhiteBrush(), bMine ? MinimapOwnColor : MinimapEnemyColor, Layer + 3);
				continue;
			}
			Count[bMine ? 0 : 1] += 1;
			const bool bHeavy = Data.Units[U.Def].Role == cw::UnitRole::Heavy;
			const float Size = bHeavy ? 8.f : 5.f;
			const float Y = MinimapLaneTop + MinimapLaneHeight * 0.5f + (static_cast<float>(U.Row) - (Rules.LaneRows - 1) * 0.5f) * 7.f;
			Box(LocalXFromWorld(U.X) - Size * 0.5f, Y - Size * 0.5f, Size, Size, CWUI::RoundedFill(), bMine ? MinimapOwnColor : MinimapEnemyColor, Layer + 2);
		}
	}

	// 当前视野
	if (const ACWCameraRig* Rig = PC->GetCameraRig())
	{
		const float L = LocalXFromWorld(Rig->GetFocusX() - Rig->GetViewHalfWidth());
		const float R = LocalXFromWorld(Rig->GetFocusX() + Rig->GetViewHalfWidth());
		const float X0 = FMath::Min(L, R);
		const float X1 = FMath::Max(L, R);
		const float Y0 = MinimapLaneTop - 6.f;
		const float Y1 = MinimapLaneTop + MinimapLaneHeight + 4.f;
		TArray<FVector2f> Points = { FVector2f(X0, Y0), FVector2f(X1, Y0), FVector2f(X1, Y1), FVector2f(X0, Y1), FVector2f(X0, Y0) };
		FSlateDrawElement::MakeLines(OutDrawElements, Layer + 3, AllottedGeometry.ToPaintGeometry(), Points, ESlateDrawEffect::None,
			FLinearColor(1.f, 1.f, 1.f, 0.85f), true, 1.5f);
	}

	// 兵力对比
	const FSlateFontInfo Font = CWUI::Font(12, true, true);
	FSlateDrawElement::MakeText(OutDrawElements, Layer + 3, AllottedGeometry.ToPaintGeometry(FVector2f(200.f, 20.f), FSlateLayoutTransform(FVector2f(10.f, 4.f))),
		FString::Printf(TEXT("我方 %d"), Count[0]), Font, ESlateDrawEffect::None, MinimapOwnColor);
	FSlateDrawElement::MakeText(OutDrawElements, Layer + 3, AllottedGeometry.ToPaintGeometry(FVector2f(200.f, 20.f), FSlateLayoutTransform(FVector2f(Width - 74.f, 4.f))),
		FString::Printf(TEXT("敌方 %d"), Count[1]), Font, ESlateDrawEffect::None, MinimapEnemyColor);
	return Layer + 4;
}

void SCWMinimap::FocusAt(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) const
{
	ACWPlayerController* PC = Controller.Get();
	ACWCameraRig* Rig = PC ? PC->GetCameraRig() : nullptr;
	if (Rig)
	{
		const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
		Rig->FocusX(WorldXFromLocal(static_cast<float>(Local.X)));
	}
}

FReply SCWMinimap::OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (MouseEvent.GetEffectingButton() == EKeys::RightMouseButton)
	{
		if (ACWPlayerController* PC = Controller.Get())
		{
			const FVector2D Local = MyGeometry.AbsoluteToLocal(MouseEvent.GetScreenSpacePosition());
			PC->RequestChampionHold(WorldXFromLocal(static_cast<float>(Local.X)));
		}
		return FReply::Handled();
	}
	if (MouseEvent.GetEffectingButton() != EKeys::LeftMouseButton)
	{
		return FReply::Unhandled();
	}
	bDragging = true;
	FocusAt(MyGeometry, MouseEvent);
	return FReply::Handled().CaptureMouse(SharedThis(this));
}

FReply SCWMinimap::OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (!bDragging)
	{
		return FReply::Unhandled();
	}
	bDragging = false;
	return FReply::Handled().ReleaseMouseCapture();
}

FReply SCWMinimap::OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent)
{
	if (bDragging && HasMouseCapture())
	{
		FocusAt(MyGeometry, MouseEvent);
		return FReply::Handled();
	}
	return FReply::Unhandled();
}

FCursorReply SCWMinimap::OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const
{
	return FCursorReply::Cursor(EMouseCursor::Hand);
}
