// 血战文明 - 战斗 HUD 与结算界面（Slate）
// 所有“能否操作”的判断只用于界面提示；真正的校验在服务器的规则核心中进行。
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "UI/CWUIStyle.h"

class ACWGameState;
class ACWPlayerController;
struct FCWTeamNetState;
struct FCWUnitNetItem;

namespace cw
{
	struct GameData;
}

class SCWBattleHud : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCWBattleHud) {}
		SLATE_ARGUMENT(TWeakObjectPtr<ACWPlayerController>, Controller)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual void Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime) override;

	void ShowToast(const FText& Message, bool bError = true);
	bool IsBuildMenuOpen() const { return BuildMenuSlot >= 0; }
	void CloseBuildMenu() { BuildMenuSlot = -1; }

private:
	// 数据访问
	const ACWGameState* GS() const;
	const cw::GameData* Data() const;
	int32 MyTeam() const;
	int32 SideTeam(int32 Side) const; // Side 0 = 屏幕左侧（己方），1 = 右侧（敌方）
	const FCWTeamNetState* TeamState(int32 Team) const;
	int32 UnitDefForSlot(int32 Slot) const;
	// 国策加成后的实际造价/训练时间（与服务器使用同一套计算）
	int32 EffectiveCost(int32 Team, int32 Def) const;
	float EffectiveTrainTime(int32 Team, int32 Def) const;
	const FCWUnitNetItem* FindUnitItem(int32 Id) const;
	FText ChampionStatusText(int32 Team) const;

	// 构件
	TSharedRef<SWidget> MakeTopBar();
	TSharedRef<SWidget> MakeSideInfo(int32 Side);
	TSharedRef<SWidget> MakeBar(TAttribute<float> Ratio, TAttribute<FSlateColor> Color, float Width, float Height, TAttribute<FText> Text);
	TSharedRef<SWidget> MakeResourceRow();
	TSharedRef<SWidget> MakeCommandPanel();
	TSharedRef<SWidget> MakeUnitButton(int32 Slot);
	TSharedRef<SWidget> MakeQueueSlot(int32 Index);
	TSharedRef<SWidget> MakeAgeButton();
	TSharedRef<SWidget> MakeSkillButton();
	TSharedRef<SWidget> MakeEconomyButton();
	TSharedRef<SWidget> MakeStanceButton();
	TSharedRef<SWidget> MakeChampionAbilityButton();
	TSharedRef<SWidget> MakeChampionOrderButton();
	TSharedRef<SWidget> MakeDoctrinePanel();
	TSharedRef<SWidget> MakeDoctrineOption(int32 Index);
	TSharedRef<SWidget> MakeTurretSlot(int32 Slot);
	TSharedRef<SWidget> MakeBuildMenu();
	TSharedRef<SWidget> MakeResultPanel();
	TSharedRef<SWidget> MakeStatRow(const FText& Label, TFunction<FText(int32 Team)> Value);

	// 状态与原因
	bool CanTrain(int32 Slot, FText& OutReason) const;
	bool CanUpgradeAge(FText& OutReason) const;
	bool CanCastSkill(FText& OutReason) const;
	bool CanUpgradeEconomy(FText& OutReason) const;
	bool IsTurretPhaseAllowed() const;
	FText TurretPhaseReason() const;
	FReply OnUpgradeEconomy();
	FReply OnToggleStance();
	FReply OnChooseDoctrine(int32 Index);
	FReply OnChampionAbility();
	FReply OnToggleChampionOrder();
	FReply OnLastStand();
	void UpdateNotifications();
	FText GetToastText() const { return ToastText; }
	EVisibility GetToastVisibility() const;

	// 操作
	FReply OnTrain(int32 Slot);
	FReply OnCancelQueue(int32 Index);
	FReply OnUpgradeAge();
	FReply OnSkill();
	FReply OnTurretSlotClicked(int32 Slot);
	FReply OnTurretUpgrade(int32 Slot);
	FReply OnTurretSell(int32 Slot);
	FReply OnBuildTurret(int32 TurretDef);
	FReply OnLeaveMatch();
	FReply OnFrontendMenu();
	FReply OnRematch();
	FReply OnBackToLobby();
	FReply OnMainMenu();

	TWeakObjectPtr<ACWPlayerController> Controller;
	FText ToastText;
	FLinearColor ToastColor = FLinearColor::White;
	double ToastTime = -100.0;
	int32 BuildMenuSlot = -1;
	// 事件提示：比较复制状态的变化（国策、统帅阵亡）
	bool bTrackerReady = false;
	int32 SeenDoctrines[2] = { 0, 0 };
	int32 SeenChampionId[2] = { -1, -1 };
	bool SeenLastStand[2] = { false, false };
};
