// 血战文明 - 小地图：显示双方基地、兵力分布（蓝 / 红阵营颜色，白边方块为统帅）、技能预警与当前视野；
// 左键点击或拖动跳转镜头，右键点击让统帅坚守到该位置
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SLeafWidget.h"

class ACWPlayerController;

class SCWMinimap : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SCWMinimap) {}
		SLATE_ARGUMENT(TWeakObjectPtr<ACWPlayerController>, Controller)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& AllottedGeometry, const FSlateRect& MyCullingRect,
		FSlateWindowElementList& OutDrawElements, int32 LayerId, const FWidgetStyle& InWidgetStyle, bool bParentEnabled) const override;
	virtual FVector2D ComputeDesiredSize(float LayoutScaleMultiplier) const override;
	virtual FReply OnMouseButtonDown(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseButtonUp(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FReply OnMouseMove(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) override;
	virtual FCursorReply OnCursorQuery(const FGeometry& MyGeometry, const FPointerEvent& CursorEvent) const override;

	static constexpr float Width = 444.f;
	static constexpr float Height = 76.f;

private:
	// 小地图横坐标 ↔ 世界 X；与镜头一致：己方基地始终在左侧
	float LocalXFromWorld(float WorldX) const;
	float WorldXFromLocal(float LocalX) const;
	void FocusAt(const FGeometry& MyGeometry, const FPointerEvent& MouseEvent) const;
	int32 ViewTeam() const;
	float LaneLength() const;

	TWeakObjectPtr<ACWPlayerController> Controller;
	bool bDragging = false;
};
