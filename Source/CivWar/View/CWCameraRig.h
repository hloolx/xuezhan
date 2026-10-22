// 血战文明 - 横向战术镜头：略带俯视，沿战线平移、有限缩放、快速回到己方基地
// 阵营 1 的镜头位于战场另一侧（绕 Z 轴转 180°），使双方都看到己方基地在左侧；
// 这只是显示层处理，世界坐标与服务器坐标保持一致。
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CWCameraRig.generated.h"

class UCameraComponent;
class ACWMenuShowcase;

UCLASS()
class CIVWAR_API ACWCameraRig : public AActor
{
	GENERATED_BODY()

public:
	ACWCameraRig();

	virtual void Tick(float DeltaSeconds) override;

	void SetViewTeam(int32 Team);
	int32 GetViewTeam() const { return ViewTeam; }
	bool IsArtReviewEnabled() const { return bArtReview; }
#if WITH_EDITOR
	void CaptureRockTowerReview(int32 Team, int32 Slot, uint8 Sequence, float Elapsed, float Pitch, bool bStoneVisible);
#endif
	void AddPanInput(float ScreenAxis);
	void AddZoomInput(float Axis);
	void FocusX(float X, bool bInstant = false);
	void StopManualMovement();
	void SetLaneLength(float InLaneLength) { LaneLength = InLaneLength; }
	// 屏幕向右对应的世界 X 方向（阵营 1 为 -1）
	float ScreenRightSign() const { return ViewTeam == 1 ? -1.f : 1.f; }

	// 菜单背景：缓慢巡游
	void SetAttractMode(bool bEnabled) { bAttract = bEnabled; }

	// 小地图：镜头焦点与地面可视半宽（水平视场 45° 时约为 距离 × tan(22.5°)）
	float GetFocusX() const { return CurrentX; }
	float GetViewHalfWidth() const { return CurrentDistance * 0.414f; }

private:
	void ApplyTransform();
	bool UpdateArtReview(float DeltaSeconds);
#if WITH_EDITOR
	bool UpdateMotionCapture();
	int32 MotionCaptureId = -1;
	float MotionCaptureStart[3] = { -1.f, -1.f, -1.f };
	int32 MotionCaptureFrames[3] = { 0, 0, 0 };
	float MotionCapturePreviousX = 0.f;
	bool bMotionCaptureHasPrevious = false;
#endif

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UCameraComponent> Camera;

	UPROPERTY(Transient)
	TObjectPtr<ACWMenuShowcase> MenuShowcase;
	bool bMenuPresentation = false;

	int32 ViewTeam = 0;
	float LaneLength = 6000.f;
	float TargetX = 900.f;
	float CurrentX = 900.f;
	float TargetDistance = 2300.f;
	float CurrentDistance = 2300.f;
	float PendingPan = 0.f;
	float SideBlend = 0.f; // 0 = 阵营 0 视角，1 = 阵营 1 视角（切换时平滑旋转）
	bool bAttract = false;
	bool bTeamInitialized = false;
	float AttractTime = 0.f;
	bool bArtReview = false;
	float ArtReviewElapsed = 0.f;
	int32 ArtReviewShot = -1;
	FString ArtReviewPrefix = TEXT("TripoEnvironment");
#if WITH_EDITOR
	int32 RockTowerReviewTeam = -1;
	int32 RockTowerReviewSequence = -1;
	uint8 RockTowerReviewMask = 0;
#endif

	static constexpr float MinDistance = 1300.f;
	static constexpr float MaxDistance = 3400.f;
	static constexpr float PitchDegrees = 20.f;
	static constexpr float PanSpeed = 2600.f;
};
