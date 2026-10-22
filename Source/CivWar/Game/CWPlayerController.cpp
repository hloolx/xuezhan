#include "Game/CWPlayerController.h"

#include "CivWar.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/LocalPlayer.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "Game/CWGameInstance.h"
#include "Game/CWGameMode.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerState.h"
#include "InputAction.h"
#include "InputActionValue.h"
#include "InputMappingContext.h"
#include "InputModifiers.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWBattleReplicator.h"
#include "Sim/SimState.h"
#include "UI/CWHUD.h"
#include "UI/CWFrontendFlow.h"
#include "TimerManager.h"
#include "View/CWCameraRig.h"

#include <limits>

ACWPlayerController::ACWPlayerController()
{
	bShowMouseCursor = true;
	bEnableClickEvents = false;
	bAutoManageActiveCameraTarget = false;
	DefaultMouseCursor = EMouseCursor::Default;
}

void ACWPlayerController::BeginPlay()
{
	Super::BeginPlay();
	LastTokenRefill = GetWorld()->GetTimeSeconds();
}

int32 ACWPlayerController::GetTeam() const
{
	const ACWPlayerState* PS = GetPlayerState<ACWPlayerState>();
	return PS ? PS->GetTeam() : -1;
}

ACWGameState* ACWPlayerController::GetCWGameState() const
{
	return GetWorld() ? GetWorld()->GetGameState<ACWGameState>() : nullptr;
}

bool ACWPlayerController::CanUseBattleInput() const
{
	const ACWGameState* State = GetCWGameState();
	const ACWHUD* Hud = Cast<ACWHUD>(GetHUD());
	return State && CWFrontend::CanCommand(State->GetPhase(), Hud && Hud->IsFrontendMenuOpen());
}

bool ACWPlayerController::CanUseCameraInput() const
{
	const ACWGameState* State = GetCWGameState();
	const ACWHUD* Hud = Cast<ACWHUD>(GetHUD());
	return State && CWFrontend::CanMoveCamera(State->GetPhase(), Hud && Hud->IsFrontendMenuOpen());
}

void ACWPlayerController::DispatchBattleCommand(uint8 Type, int32 A, int32 B, float X)
{
	if (!CanUseBattleInput()) return;
#if WITH_EDITOR
	++LocalCommandDispatchCount;
#endif
	ServerCommand(Type, A, B, X);
}

// ---------------------------------------------------------------------------
// 输入：动作与映射在运行时创建
// ---------------------------------------------------------------------------
static UInputAction* CWMakeAction(UObject* Outer, const TCHAR* Name, EInputActionValueType Type)
{
	UInputAction* Action = NewObject<UInputAction>(Outer, FName(Name));
	Action->ValueType = Type;
	return Action;
}

void ACWPlayerController::BuildInputActions()
{
	if (MappingContext)
	{
		return;
	}
	MappingContext = NewObject<UInputMappingContext>(this, TEXT("IMC_CivWar"));
	PanAction = CWMakeAction(this, TEXT("IA_Pan"), EInputActionValueType::Axis1D);
	ZoomAction = CWMakeAction(this, TEXT("IA_Zoom"), EInputActionValueType::Axis1D);
	HomeAction = CWMakeAction(this, TEXT("IA_Home"), EInputActionValueType::Boolean);
	Train1Action = CWMakeAction(this, TEXT("IA_Train1"), EInputActionValueType::Boolean);
	Train2Action = CWMakeAction(this, TEXT("IA_Train2"), EInputActionValueType::Boolean);
	Train3Action = CWMakeAction(this, TEXT("IA_Train3"), EInputActionValueType::Boolean);
	UpgradeAction = CWMakeAction(this, TEXT("IA_Upgrade"), EInputActionValueType::Boolean);
	EconomyAction = CWMakeAction(this, TEXT("IA_Economy"), EInputActionValueType::Boolean);
	StanceAction = CWMakeAction(this, TEXT("IA_Stance"), EInputActionValueType::Boolean);
	SkillAction = CWMakeAction(this, TEXT("IA_Skill"), EInputActionValueType::Boolean);
	ClickAction = CWMakeAction(this, TEXT("IA_Click"), EInputActionValueType::Boolean);
	CancelAction = CWMakeAction(this, TEXT("IA_Cancel"), EInputActionValueType::Boolean);
	RightClickAction = CWMakeAction(this, TEXT("IA_RightClick"), EInputActionValueType::Boolean);
	RallyAction = CWMakeAction(this, TEXT("IA_Rally"), EInputActionValueType::Boolean);
	FollowAction = CWMakeAction(this, TEXT("IA_Follow"), EInputActionValueType::Boolean);
	FocusChampionAction = CWMakeAction(this, TEXT("IA_FocusChampion"), EInputActionValueType::Boolean);
	LastStandAction = CWMakeAction(this, TEXT("IA_LastStand"), EInputActionValueType::Boolean);

	// 平移：A/← 为负，D/→ 为正
	MappingContext->MapKey(PanAction, EKeys::D);
	MappingContext->MapKey(PanAction, EKeys::Right);
	FEnhancedActionKeyMapping& Left = MappingContext->MapKey(PanAction, EKeys::A);
	Left.Modifiers.Add(NewObject<UInputModifierNegate>(MappingContext));
	FEnhancedActionKeyMapping& LeftArrow = MappingContext->MapKey(PanAction, EKeys::Left);
	LeftArrow.Modifiers.Add(NewObject<UInputModifierNegate>(MappingContext));

	MappingContext->MapKey(ZoomAction, EKeys::MouseWheelAxis);
	MappingContext->MapKey(HomeAction, EKeys::SpaceBar);
	MappingContext->MapKey(HomeAction, EKeys::H);
	MappingContext->MapKey(Train1Action, EKeys::One);
	MappingContext->MapKey(Train2Action, EKeys::Two);
	MappingContext->MapKey(Train3Action, EKeys::Three);
	MappingContext->MapKey(UpgradeAction, EKeys::U);
	MappingContext->MapKey(EconomyAction, EKeys::E);
	MappingContext->MapKey(StanceAction, EKeys::F);
	MappingContext->MapKey(SkillAction, EKeys::Q);
	MappingContext->MapKey(ClickAction, EKeys::LeftMouseButton);
	MappingContext->MapKey(RightClickAction, EKeys::RightMouseButton); // 瞄准技能时取消，否则指挥统帅
	MappingContext->MapKey(CancelAction, EKeys::Escape);
	MappingContext->MapKey(RallyAction, EKeys::R);
	MappingContext->MapKey(FollowAction, EKeys::G);
	MappingContext->MapKey(FocusChampionAction, EKeys::C);
	MappingContext->MapKey(LastStandAction, EKeys::L);
}

void ACWPlayerController::SetupInputComponent()
{
	Super::SetupInputComponent();
	BuildInputActions();
	UEnhancedInputComponent* Input = Cast<UEnhancedInputComponent>(InputComponent);
	if (!Input)
	{
		UE_LOG(LogCivWar, Error, TEXT("InputComponent 不是 EnhancedInputComponent，请检查 DefaultInput.ini"));
		return;
	}
	Input->BindAction(PanAction, ETriggerEvent::Triggered, this, &ACWPlayerController::OnPan);
	Input->BindAction(ZoomAction, ETriggerEvent::Triggered, this, &ACWPlayerController::OnZoom);
	Input->BindAction(HomeAction, ETriggerEvent::Started, this, &ACWPlayerController::OnHome);
	Input->BindAction(Train1Action, ETriggerEvent::Started, this, &ACWPlayerController::OnTrain1);
	Input->BindAction(Train2Action, ETriggerEvent::Started, this, &ACWPlayerController::OnTrain2);
	Input->BindAction(Train3Action, ETriggerEvent::Started, this, &ACWPlayerController::OnTrain3);
	Input->BindAction(UpgradeAction, ETriggerEvent::Started, this, &ACWPlayerController::OnUpgradeKey);
	Input->BindAction(EconomyAction, ETriggerEvent::Started, this, &ACWPlayerController::OnEconomyKey);
	Input->BindAction(StanceAction, ETriggerEvent::Started, this, &ACWPlayerController::OnStanceKey);
	Input->BindAction(SkillAction, ETriggerEvent::Started, this, &ACWPlayerController::OnSkillKey);
	Input->BindAction(ClickAction, ETriggerEvent::Started, this, &ACWPlayerController::OnClick);
	Input->BindAction(CancelAction, ETriggerEvent::Started, this, &ACWPlayerController::OnCancel);
	Input->BindAction(RightClickAction, ETriggerEvent::Started, this, &ACWPlayerController::OnRightClick);
	Input->BindAction(RallyAction, ETriggerEvent::Started, this, &ACWPlayerController::OnRallyKey);
	Input->BindAction(FollowAction, ETriggerEvent::Started, this, &ACWPlayerController::OnFollowKey);
	Input->BindAction(FocusChampionAction, ETriggerEvent::Started, this, &ACWPlayerController::OnFocusChampionKey);
	Input->BindAction(LastStandAction, ETriggerEvent::Started, this, &ACWPlayerController::OnLastStandKey);
}

void ACWPlayerController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);

	// 本地初始化放在 PlayerTick：客户端的控制器可能在 BeginPlay 之后才关联到本地玩家
	if (!CameraRig)
	{
		FInputModeGameAndUI Mode;
		Mode.SetHideCursorDuringCapture(false);
		Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
		SetInputMode(Mode);
		CameraRig = GetWorld()->SpawnActor<ACWCameraRig>();
		SetViewTarget(CameraRig);
		if (ULocalPlayer* LP = GetLocalPlayer())
		{
			if (UEnhancedInputLocalPlayerSubsystem* Subsystem = LP->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>())
			{
				BuildInputActions();
				Subsystem->AddMappingContext(MappingContext, 0);
			}
		}
	}

	// 阵营确定后：设置镜头朝向（阵营 1 从战场另一侧观察，己方基地同样显示在左侧）并对准己方基地
	const int32 Team = GetTeam();
	if (CameraRig && Team >= 0)
	{
		CameraRig->SetViewTeam(Team);
		if (!bFocusedOnce)
		{
			bFocusedOnce = true;
			FocusHome();
		}
	}

	// 鼠标贴边平移
	if (CameraRig && CanUseCameraInput())
	{
		float MouseX = 0.f;
		float MouseY = 0.f;
		int32 SizeX = 0;
		int32 SizeY = 0;
		GetViewportSize(SizeX, SizeY);
		if (GetMousePosition(MouseX, MouseY) && SizeX > 0)
		{
			const float Edge = 12.f;
			if (MouseX <= Edge)
			{
				CameraRig->AddPanInput(-1.f);
			}
			else if (MouseX >= SizeX - Edge)
			{
				CameraRig->AddPanInput(1.f);
			}
		}
	}

	if (!HasAuthority())
	{
		VerifyDataChecksum();
	}
	UpdateAutomation(DeltaTime);
}

// ---------------------------------------------------------------------------
// 自动化测试
// ---------------------------------------------------------------------------
void ACWPlayerController::UpdateAutomation(float DeltaTime)
{
	UCWGameInstance* GI = GetGameInstance<UCWGameInstance>();
	const ACWGameState* State = GetCWGameState();
	if (!GI || !State)
	{
		return;
	}
	AutomationTimer -= DeltaTime;
	if (AutomationTimer > 0.f)
	{
		return;
	}
	AutomationTimer = 0.6f;
	const ECWMatchPhase Phase = State->GetPhase();
	if (Phase == ECWMatchPhase::Lobby && GI->bAutoReady)
	{
		const ACWPlayerState* PS = GetPlayerState<ACWPlayerState>();
		if (PS && PS->GetTeam() >= 0 && !PS->IsReady())
		{
			ServerSetReady(true);
		}
	}
	if (Phase == ECWMatchPhase::InMatch)
	{
		bResultLogged = false;
		if (FParse::Param(FCommandLine::Get(), TEXT("cwcheattest")) && !bCheatTestDone && State->GetMatchTime() > 3.f)
		{
			RunCheatTest();
		}
		if (GI->bAutoPlay)
		{
			RunAutoPlayStep(*State);
		}
	}
	if (Phase == ECWMatchPhase::PostMatch && !bResultLogged)
	{
		bResultLogged = true;
		LogMatchResult(*State);
		if (GI->bExitOnEnd)
		{
			FTimerHandle Handle;
			GetWorldTimerManager().SetTimer(Handle, FTimerDelegate::CreateWeakLambda(this, [this]() { ConsoleCommand(TEXT("quit")); }), 3.f, false);
		}
	}
}

void ACWPlayerController::RunAutoPlayStep(const ACWGameState& State)
{
	if (!CanUseBattleInput()) return;
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	const int32 Team = GetTeam();
	if (!DataSys || !DataSys->IsLoaded() || Team < 0)
	{
		return;
	}
	const cw::GameData& D = DataSys->GetData();
	const FCWTeamNetState& S = State.GetTeam(Team);

	// 0) 有待选国策时选第一项；统帅冷却好且在场时施放战吼
	if (S.Offer.Num() > 0)
	{
		RequestChooseDoctrine(0);
		return;
	}
	if (S.ChampionId >= 0 && S.ChampionCooldown <= 0.f && State.GetMatchTime() > 20.f)
	{
		RequestChampionAbility();
		return;
	}
	// 背水一战：可用 3 秒后发动
	const bool bLastStandReady = !S.bLastStandUsed && S.BaseMaxHp > 0.f && S.BaseHp <= S.BaseMaxHp * D.Rules.LastStandBaseHpRatio;
	if (bLastStandReady)
	{
		if (LastStandReadySince < 0.f)
		{
			LastStandReadySince = State.GetMatchTime();
		}
		else if (State.GetMatchTime() - LastStandReadySince >= 3.f)
		{
			RequestLastStand();
			return;
		}
	}

	// 1) 条件满足就升级时代
	const int32 Next = S.Age + 1;
	if (Next < static_cast<int32>(D.Ages.size()) && D.Ages[Next].Implemented && !S.bUpgrading && S.Xp >= D.Ages[Next].XpToEnter
		&& S.Gold >= D.Ages[Next].GoldToEnter)
	{
		RequestUpgradeAge();
		return;
	}
	// 2) 90 秒后在首个槽位建造当前时代最便宜的炮塔
	if (State.GetMatchTime() > 90.f && S.Turrets.Num() > 0 && S.Turrets[0].bUnlocked && S.Turrets[0].Def < 0)
	{
		int32 Best = -1;
		for (int32 I = 0; I < static_cast<int32>(D.Turrets.size()); ++I)
		{
			if (D.Turrets[I].Age <= S.Age && (Best < 0 || D.Turrets[I].Cost < D.Turrets[Best].Cost))
			{
				Best = I;
			}
		}
		if (Best >= 0 && S.Gold >= D.Turrets[Best].Cost + 50)
		{
			RequestBuildTurret(0, Best);
			return;
		}
	}
	// 3) 技能：打击离己方基地最近的敌方单位
	const int32 Skill = D.SkillForAge(S.Age);
	if (Skill >= 0 && S.SkillCooldown <= 0.f && S.Gold >= D.Skills[Skill].Cost + 60 && State.GetReplicator())
	{
		const float MyGate = Team == 0 ? D.Rules.BaseHalfWidth : D.Rules.LaneLength - D.Rules.BaseHalfWidth;
		float BestX = 0.f;
		float BestDist = 1.0e9f;
		for (const FCWUnitNetItem& U : State.GetReplicator()->GetUnits().Items)
		{
			if (U.Team != Team && FMath::Abs(U.X - MyGate) < BestDist)
			{
				BestDist = FMath::Abs(U.X - MyGate);
				BestX = U.X;
			}
		}
		if (BestDist < D.Rules.LaneLength * 0.6f)
		{
			ServerCommand(static_cast<uint8>(cw::CommandType::CastSkill), 0, 0, BestX);
			return;
		}
	}
	// 4) 轮流训练三种兵种
	if (S.Queue.Num() < 2)
	{
		const std::vector<int32_t> List = D.UnitsForAge(S.Age);
		if (!List.empty())
		{
			const int32 Slot = AutoTrainCounter % static_cast<int32>(List.size());
			if (S.Gold >= D.Units[List[Slot]].Cost)
			{
				RequestTrain(Slot);
				++AutoTrainCounter;
			}
		}
	}
}

void ACWPlayerController::RunCheatTest()
{
	// 客户端越权/绕过资源测试：这些请求都应被服务器拒绝，结果写入日志
	bCheatTestDone = true;
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	const float EnemyGate = DataSys && GetTeam() == 0 ? DataSys->GetData().Rules.LaneLength - DataSys->GetData().Rules.BaseHalfWidth
	                                                 : (DataSys ? DataSys->GetData().Rules.BaseHalfWidth : 0.f);
	UE_LOG(LogCivWar, Display, TEXT("CIVWAR_CHEATTEST 开始：发送非法指令"));
	ServerCommand(static_cast<uint8>(cw::CommandType::Train), 99, 0, 0.f);              // 不存在的兵种槽位
	ServerCommand(static_cast<uint8>(cw::CommandType::CastSkill), 0, 0, EnemyGate);    // 技能落在敌方基地
	ServerCommand(static_cast<uint8>(cw::CommandType::CastSkill), 0, 0, std::numeric_limits<float>::quiet_NaN()); // 非法坐标
	ServerCommand(static_cast<uint8>(cw::CommandType::BuildTurret), 2, 0, 0.f);        // 未解锁槽位
	ServerCommand(static_cast<uint8>(cw::CommandType::UpgradeTurret), 1, 0, 0.f);      // 空槽升级
	ServerCommand(static_cast<uint8>(cw::CommandType::CancelTrain), 50, 0, 0.f);       // 非法队列下标
	ServerCommand(static_cast<uint8>(cw::CommandType::UpgradeAge), 0, 0, 0.f);         // 经验不足
	ServerCommand(200, 0, 0, 0.f);                                                     // 不存在的指令类型
	ServerCommand(static_cast<uint8>(cw::CommandType::ChooseDoctrine), 9, 0, 0.f);     // 不存在的国策选项
	ServerCommand(static_cast<uint8>(cw::CommandType::ChampionMove), 0, 0, std::numeric_limits<float>::quiet_NaN()); // 非法坚守位置
	ServerCommand(static_cast<uint8>(cw::CommandType::ChampionMove), 5, 0, 0.f);       // 非法统帅指令
	for (int32 I = 0; I < 30; ++I)
	{
		ServerCommand(static_cast<uint8>(cw::CommandType::Train), 2, 0, 0.f);          // 刷指令：金币不足/队列已满/限流
	}
}

void ACWPlayerController::LogMatchResult(const ACWGameState& State)
{
	const FCWTeamNetState& T0 = State.GetTeam(0);
	const FCWTeamNetState& T1 = State.GetTeam(1);
	UE_LOG(LogCivWar, Display,
		TEXT("CIVWAR_RESULT role=%s team=%d winner=%d reason=%d time=%.1f base0=%.0f base1=%.0f age0=%d age1=%d trained0=%d trained1=%d kills0=%d kills1=%d"),
		HasAuthority() ? TEXT("host") : TEXT("client"), GetTeam(), State.GetWinner(), static_cast<int32>(State.GetEndReason()), State.GetMatchTime(),
		T0.BaseHp, T1.BaseHp, T0.Age, T1.Age, T0.UnitsTrained, T1.UnitsTrained, T0.Kills, T1.Kills);
	FString Rejections;
	for (const TPair<uint8, int32>& Pair : RejectionCounts)
	{
		Rejections += FString::Printf(TEXT("%d:%d "), Pair.Key, Pair.Value);
	}
	UE_LOG(LogCivWar, Display, TEXT("CIVWAR_REJECTIONS role=%s %s"), HasAuthority() ? TEXT("host") : TEXT("client"), *Rejections);
}

void ACWPlayerController::VerifyDataChecksum()
{
	if (bChecksumVerified)
	{
		return;
	}
	const ACWGameState* State = GetCWGameState();
	if (!State || State->DataChecksum == 0)
	{
		return;
	}
	bChecksumVerified = true;
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (DataSys && DataSys->GetChecksum() != State->DataChecksum)
	{
		UE_LOG(LogCivWar, Error, TEXT("数据校验不一致：本地 %08x，主机 %08x"), DataSys->GetChecksum(), State->DataChecksum);
		if (UCWGameInstance* GI = GetGameInstance<UCWGameInstance>())
		{
			GI->ReturnToMainMenuWithError(NSLOCTEXT("CivWar", "DataMismatch", "游戏数据与主机不一致，请确认双方版本相同"));
		}
	}
}

void ACWPlayerController::OnPan(const FInputActionValue& Value)
{
	if (CameraRig && CanUseCameraInput())
	{
		CameraRig->AddPanInput(Value.Get<float>());
	}
}

void ACWPlayerController::OnZoom(const FInputActionValue& Value)
{
	if (CameraRig && CanUseCameraInput())
	{
		CameraRig->AddZoomInput(Value.Get<float>());
	}
}

void ACWPlayerController::OnHome()
{
	if (CanUseCameraInput()) FocusHome();
}

void ACWPlayerController::FocusHome()
{
	const ACWGameState* State = GetCWGameState();
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (CameraRig && DataSys && DataSys->IsLoaded())
	{
		const float Lane = DataSys->GetData().Rules.LaneLength;
		const int32 Team = FMath::Max(GetTeam(), 0);
		const float HomeX = Team == 0 ? 900.f : Lane - 900.f;
		CameraRig->FocusX(State && State->GetPhase() == ECWMatchPhase::Menu ? Lane * 0.5f : HomeX);
	}
}

void ACWPlayerController::OnTrain1() { RequestTrain(0); }
void ACWPlayerController::OnTrain2() { RequestTrain(1); }
void ACWPlayerController::OnTrain3() { RequestTrain(2); }
void ACWPlayerController::OnUpgradeKey() { RequestUpgradeAge(); }
void ACWPlayerController::OnEconomyKey() { RequestUpgradeEconomy(); }
void ACWPlayerController::OnStanceKey() { ToggleStance(); }
void ACWPlayerController::OnSkillKey() { BeginSkillTargeting(); }

void ACWPlayerController::OnClick()
{
	if (!CanUseBattleInput() || !bSkillTargeting)
	{
		return;
	}
	float X = 0.f;
	if (GetCursorLaneX(X))
	{
		DispatchBattleCommand(static_cast<uint8>(cw::CommandType::CastSkill), 0, 0, X);
	}
	CancelSkillTargeting();
}

void ACWPlayerController::OnCancel()
{
	if (ACWHUD* Hud = Cast<ACWHUD>(GetHUD())) Hud->HandleFrontendBack();
	else CancelSkillTargeting();
}

void ACWPlayerController::OnRightClick()
{
	if (!CanUseBattleInput()) return;
	if (bSkillTargeting)
	{
		CancelSkillTargeting();
		return;
	}
	float X = 0.f;
	if (GetCursorLaneX(X))
	{
		RequestChampionHold(X);
	}
}

void ACWPlayerController::OnRallyKey() { RequestChampionAbility(); }
void ACWPlayerController::OnFollowKey() { ToggleChampionOrder(); }
void ACWPlayerController::OnFocusChampionKey() { FocusChampion(); }
void ACWPlayerController::OnLastStandKey() { RequestLastStand(); }

void ACWPlayerController::RequestLastStand()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::LastStand), 0, 0, 0.f);
}

void ACWPlayerController::RequestChooseDoctrine(int32 OfferIndex)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::ChooseDoctrine), OfferIndex, 0, 0.f);
}

void ACWPlayerController::RequestChampionHold(float X)
{
	if (!CanUseBattleInput()) return;
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (DataSys && DataSys->IsLoaded())
	{
		// 坚守位置限制在两座城门之间（服务器同样会校验）
		const cw::RulesDef& R = DataSys->GetData().Rules;
		X = FMath::Clamp(X, R.BaseHalfWidth, R.LaneLength - R.BaseHalfWidth);
	}
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::ChampionMove), 0, 0, X);
}

void ACWPlayerController::RequestChampionFollow()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::ChampionMove), 1, 0, 0.f);
}

void ACWPlayerController::ToggleChampionOrder()
{
	if (!CanUseBattleInput()) return;
	const ACWGameState* State = GetCWGameState();
	const int32 Team = GetTeam();
	if (!State || Team < 0)
	{
		return;
	}
	const FCWTeamNetState& S = State->GetTeam(Team);
	if (S.ChampionOrder == 1)
	{
		RequestChampionFollow();
		return;
	}
	// 随军 → 坚守在统帅当前位置
	const ACWBattleReplicator* Rep = State->GetReplicator();
	if (Rep)
	{
		for (const FCWUnitNetItem& U : Rep->GetUnits().Items)
		{
			if (U.Id == S.ChampionId)
			{
				RequestChampionHold(U.X);
				return;
			}
		}
	}
}

void ACWPlayerController::RequestChampionAbility()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::ChampionAbility), 0, 0, 0.f);
}

void ACWPlayerController::FocusChampion()
{
	if (!CanUseCameraInput()) return;
	const ACWGameState* State = GetCWGameState();
	const int32 Team = GetTeam();
	const ACWBattleReplicator* Rep = State ? State->GetReplicator() : nullptr;
	if (!CameraRig || !Rep || Team < 0)
	{
		return;
	}
	const int32 ChampionId = State->GetTeam(Team).ChampionId;
	for (const FCWUnitNetItem& U : Rep->GetUnits().Items)
	{
		if (U.Id == ChampionId)
		{
			CameraRig->FocusX(U.X);
			return;
		}
	}
}

bool ACWPlayerController::GetCursorLaneX(float& OutX) const
{
	FVector WorldLoc;
	FVector WorldDir;
	if (!DeprojectMousePositionToWorld(WorldLoc, WorldDir) || FMath::Abs(WorldDir.Z) < 1.0e-3)
	{
		return false;
	}
	// 与地面（Z = 0）求交；世界坐标即服务器坐标，镜头镜像不改变坐标
	const double T = -WorldLoc.Z / WorldDir.Z;
	if (T <= 0.0)
	{
		return false;
	}
	OutX = static_cast<float>((WorldLoc + WorldDir * T).X);
	return true;
}

void ACWPlayerController::BeginSkillTargeting()
{
	if (!CanUseBattleInput()) return;
	const ACWGameState* State = GetCWGameState();
	if (State && State->GetPhase() == ECWMatchPhase::InMatch && GetTeam() >= 0)
	{
		bSkillTargeting = true;
	}
}

void ACWPlayerController::CancelSkillTargeting()
{
	bSkillTargeting = false;
}

void ACWPlayerController::RequestTrain(int32 Slot)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::Train), Slot, 0, 0.f);
}

void ACWPlayerController::RequestCancelTrain(int32 QueueIndex)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::CancelTrain), QueueIndex, 0, 0.f);
}

void ACWPlayerController::RequestUpgradeAge()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::UpgradeAge), 0, 0, 0.f);
}

void ACWPlayerController::RequestBuyTurretSlot()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::BuyTurretSlot), 0, 0, 0.f);
}

void ACWPlayerController::RequestBuildTurret(int32 Slot, int32 TurretDef)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::BuildTurret), Slot, TurretDef, 0.f);
}

void ACWPlayerController::RequestUpgradeTurret(int32 Slot)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::UpgradeTurret), Slot, 0, 0.f);
}

void ACWPlayerController::RequestSellTurret(int32 Slot)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::SellTurret), Slot, 0, 0.f);
}

void ACWPlayerController::RequestUpgradeEconomy()
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::UpgradeEconomy), 0, 0, 0.f);
}

void ACWPlayerController::RequestSetStance(bool bHold)
{
	if (!CanUseBattleInput()) return;
	DispatchBattleCommand(static_cast<uint8>(cw::CommandType::SetStance), bHold ? 1 : 0, 0, 0.f);
}

void ACWPlayerController::ToggleStance()
{
	if (!CanUseBattleInput()) return;
	const ACWGameState* State = GetCWGameState();
	const int32 Team = GetTeam();
	if (State && Team >= 0)
	{
		RequestSetStance(State->GetTeam(Team).Stance == 0);
	}
}

// ---------------------------------------------------------------------------
// 服务器 RPC
// ---------------------------------------------------------------------------
bool ACWPlayerController::ConsumeCommandToken()
{
	// 每秒补充 15 个，最多 20 个：正常操作不受影响，恶意刷指令会被丢弃
	const double Now = GetWorld()->GetTimeSeconds();
	CommandTokens = FMath::Min(20.f, CommandTokens + static_cast<float>(Now - LastTokenRefill) * 15.f);
	LastTokenRefill = Now;
	if (CommandTokens < 1.f)
	{
		return false;
	}
	CommandTokens -= 1.f;
	return true;
}

void ACWPlayerController::ServerCommand_Implementation(uint8 Type, int32 A, int32 B, float X)
{
	if (!ConsumeCommandToken())
	{
		ClientCommandResult(Type, 255); // 255 = 操作过于频繁
		return;
	}
	if (ACWGameMode* GM = GetWorld()->GetAuthGameMode<ACWGameMode>())
	{
		GM->HandleCommand(this, Type, A, B, X);
	}
}

void ACWPlayerController::ServerSetReady_Implementation(bool bReady)
{
	if (ACWGameMode* GM = GetWorld()->GetAuthGameMode<ACWGameMode>())
	{
		GM->HandleReady(this, bReady);
	}
}

void ACWPlayerController::ServerReturnToLobby_Implementation()
{
	if (ACWGameMode* GM = GetWorld()->GetAuthGameMode<ACWGameMode>())
	{
		GM->HandleReturnToLobby(this);
	}
}

void ACWPlayerController::ServerRestartSingle_Implementation()
{
	if (ACWGameMode* GM = GetWorld()->GetAuthGameMode<ACWGameMode>())
	{
		GM->HandleRestartSingle(this);
	}
}

void ACWPlayerController::ClientCommandResult_Implementation(uint8 Type, uint8 Result)
{
	RejectionCounts.FindOrAdd(Result) += 1;
	if (bCheatTestDone)
	{
		// 越权测试：逐条记录服务器的拒绝结果，便于在日志中核对
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_REJECT type=%d result=%d"), Type, Result);
	}
	OnCommandRejected.Broadcast(Type, Result);
}
