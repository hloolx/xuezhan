// 血战文明 - HUD：本地生成战场表现，按阶段切换界面，绘制单位血条
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "CWHUD.generated.h"

class ACWBattlefield;
class ACWBattleView;
class SCWBattleHud;
class SWidget;

UCLASS()
class CIVWAR_API ACWHUD : public AHUD
{
	GENERATED_BODY()

public:
	ACWHUD();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void DrawHUD() override;

	ACWBattleView* GetBattleView() const { return BattleView; }
	void ToggleFrontendMenu();
	bool IsFrontendMenuOpen() const { return bFrontendMenuOpen || bConfirmLeave; }
	void HandleFrontendBack();
	void RequestLeaveMatch();

private:
	void CreateWidgets();
	TSharedRef<SWidget> MakeFrontendOverlay();
	void SetFrontendMenuOpen(bool bOpen);
	void CloseFrontendMenu();
	void HandleCommandRejected(uint8 Type, uint8 Result);
	void UpdateTargetingPreview();
	void DrawUnitBars();

	UPROPERTY(Transient)
	TObjectPtr<ACWBattleView> BattleView;

	UPROPERTY(Transient)
	TObjectPtr<ACWBattlefield> Battlefield;

	TSharedPtr<SWidget> RootWidget;
	TSharedPtr<SWidget> ViewportWidget;
	TSharedPtr<SCWBattleHud> BattleHud;
	TSharedPtr<SWidget> FrontendOverlay;
	bool bFrontendMenuOpen = false;
	bool bConfirmLeave = false;
#if WITH_EDITOR
	bool bFrontendFixtureOpened = false;
	bool bFrontendFlowChecking = false;
#endif
	bool bBoundController = false;
	uint8 LastPhase = 255;

	// -cwshots：按阶段/对局时间自动截图（含界面）；-cwquitafter=秒：到时退出（冒烟测试）
	void UpdateAutomationShots();
	bool bAutoShots = false;
	FString ShotPrefix = TEXT("CivWar"); // -cwshotprefix=名称：区分不同测试批次的截图文件
	float QuitAfterSeconds = 0.f;
#if WITH_EDITOR
	float ReviewWorldDuration = 0.f;
#endif
	TSet<FString> ShotsTaken;
	TSet<FString> ShotsQueued; // 已排入 PendingShots 的定时截图
	// 对局中：镜头自动跟随交战前线；时代变化时先把镜头移到对应基地再截图
	struct FPendingShot
	{
		FString Name;
		float FocusX = 0.f;
		double ShootAt = -1.0;
	};
	TArray<FPendingShot> PendingShots;
	int32 ShotSeenAge[2] = { -1, -1 };
	float FrontLineX() const;

	// -cwperf：每 5 秒把帧率、帧时间与单位数量写入日志
	bool bPerfLog = false;
	bool bLightLogged = false;
	double PerfWindowStart = 0.0;
	int32 PerfFrames = 0;
	float PerfWorstFrame = 0.f;
};
