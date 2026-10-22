// 血战文明 - 玩家控制器：本地输入与镜头、向服务器发送操作请求、接收校验结果
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "CWPlayerController.generated.h"

class ACWCameraRig;
class ACWGameState;
class UInputAction;
class UInputMappingContext;
struct FInputActionValue;

DECLARE_MULTICAST_DELEGATE_TwoParams(FCWOnCommandRejected, uint8 /*CommandType*/, uint8 /*Result*/);

UCLASS()
class CIVWAR_API ACWPlayerController : public APlayerController
{
	GENERATED_BODY()

public:
	ACWPlayerController();

	virtual void BeginPlay() override;
	virtual void SetupInputComponent() override;
	virtual void PlayerTick(float DeltaTime) override;

	// ---------- 发往服务器的请求（服务器校验阵营、资源、冷却） ----------
	UFUNCTION(Server, Reliable)
	void ServerCommand(uint8 Type, int32 A, int32 B, float X);

	UFUNCTION(Server, Reliable)
	void ServerSetReady(bool bReady);

	UFUNCTION(Server, Reliable)
	void ServerReturnToLobby();

	UFUNCTION(Server, Reliable)
	void ServerRestartSingle();

	// ---------- 服务器回执 ----------
	UFUNCTION(Client, Reliable)
	void ClientCommandResult(uint8 Type, uint8 Result);

	FCWOnCommandRejected OnCommandRejected;

	// ---------- 界面调用 ----------
	void RequestTrain(int32 Slot);
	void RequestCancelTrain(int32 QueueIndex);
	void RequestUpgradeAge();
	void RequestBuyTurretSlot();
	void RequestBuildTurret(int32 Slot, int32 TurretDef);
	void RequestUpgradeTurret(int32 Slot);
	void RequestSellTurret(int32 Slot);
	void RequestUpgradeEconomy();
	void RequestSetStance(bool bHold);
	void ToggleStance();
	void RequestChooseDoctrine(int32 OfferIndex);
	// 统帅：坚守到战场坐标 X / 恢复随军 / 战吼
	void RequestChampionHold(float X);
	void RequestChampionFollow();
	void ToggleChampionOrder();
	void RequestChampionAbility();
	void FocusChampion();
	void RequestLastStand();
	void BeginSkillTargeting();
	void CancelSkillTargeting();
	bool IsSkillTargeting() const { return bSkillTargeting; }
	// 鼠标所指的战场坐标（服务器坐标系 X）；无效时返回 false
	bool GetCursorLaneX(float& OutX) const;
	void FocusHome();

	int32 GetTeam() const;
	ACWGameState* GetCWGameState() const;
	ACWCameraRig* GetCameraRig() const { return CameraRig; }
	bool CanUseBattleInput() const;
	bool CanUseCameraInput() const;
#if WITH_EDITOR
	uint32 GetLocalCommandDispatchCount() const { return LocalCommandDispatchCount; }
#endif

private:
	void BuildInputActions();
	void DispatchBattleCommand(uint8 Type, int32 A, int32 B, float X);
#if WITH_EDITOR
	uint32 LocalCommandDispatchCount = 0;
#endif
	void OnPan(const FInputActionValue& Value);
	void OnZoom(const FInputActionValue& Value);
	void OnHome();
	void OnTrain1();
	void OnTrain2();
	void OnTrain3();
	void OnUpgradeKey();
	void OnEconomyKey();
	void OnStanceKey();
	void OnSkillKey();
	void OnClick();
	void OnCancel();
	void OnRightClick();
	void OnRallyKey();
	void OnFollowKey();
	void OnFocusChampionKey();
	void OnLastStandKey();
	bool ConsumeCommandToken();
	void VerifyDataChecksum();

	// 自动化测试（只走与玩家相同的 RPC 路径）
	void UpdateAutomation(float DeltaTime);
	void RunAutoPlayStep(const ACWGameState& State);
	void RunCheatTest();
	void LogMatchResult(const ACWGameState& State);

	UPROPERTY(Transient)
	TObjectPtr<ACWCameraRig> CameraRig;

	UPROPERTY(Transient)
	TObjectPtr<UInputMappingContext> MappingContext;

	UPROPERTY(Transient) TObjectPtr<UInputAction> PanAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ZoomAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> HomeAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> Train1Action;
	UPROPERTY(Transient) TObjectPtr<UInputAction> Train2Action;
	UPROPERTY(Transient) TObjectPtr<UInputAction> Train3Action;
	UPROPERTY(Transient) TObjectPtr<UInputAction> UpgradeAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> EconomyAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> StanceAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> SkillAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> ClickAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> CancelAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> RightClickAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> RallyAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> FollowAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> FocusChampionAction;
	UPROPERTY(Transient) TObjectPtr<UInputAction> LastStandAction;

	bool bSkillTargeting = false;
	bool bChecksumVerified = false;
	bool bFocusedOnce = false;

	float AutomationTimer = 0.f;
	int32 AutoTrainCounter = 0;
	bool bResultLogged = false;
	bool bCheatTestDone = false;
	float LastStandReadySince = -1.f; // 自动化：背水一战可用后等待几秒再发动（先截一张按钮出现的画面）
	TMap<uint8, int32> RejectionCounts;

	// 服务器端：指令限流（令牌桶）
	float CommandTokens = 20.f;
	double LastTokenRefill = 0.0;
};
