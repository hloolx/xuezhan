#include "Game/CWGameMode.h"

#include "CivWar.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/World.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "Game/CWPlayerState.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWBattleReplicator.h"
#include "SocketSubsystem.h"
#include "UI/CWHUD.h"

#define LOCTEXT_NAMESPACE "CivWar"

ACWGameMode::ACWGameMode()
{
	GameStateClass = ACWGameState::StaticClass();
	PlayerStateClass = ACWPlayerState::StaticClass();
	PlayerControllerClass = ACWPlayerController::StaticClass();
	HUDClass = ACWHUD::StaticClass();
	DefaultPawnClass = nullptr; // 没有可操控角色：镜头由本地相机控制，单位由服务器生成
	bStartPlayersAsSpectators = false;
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;
}

ACWGameState* ACWGameMode::GetCWGameState() const
{
	return GetGameState<ACWGameState>();
}

bool ACWGameMode::PlayerCanRestart_Implementation(APlayerController* Player)
{
	return false; // 不生成 Pawn
}

void ACWGameMode::InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage)
{
	Super::InitGame(MapName, Options, ErrorMessage);
	const FString Mode = UGameplayStatics::ParseOption(Options, TEXT("mode"));
	if (Mode == TEXT("single"))
	{
		SessionMode = ECWSessionMode::Single;
	}
	else if (Mode == TEXT("lobby"))
	{
		SessionMode = ECWSessionMode::Lobby;
	}
	else if (Mode.IsEmpty() && (UGameplayStatics::HasOption(Options, TEXT("listen")) || IsRunningDedicatedServer()))
	{
		// 编辑器 PIE 多人预览 / 专用服务器启动时没有 mode 参数：作为联机房间
		SessionMode = ECWSessionMode::Lobby;
	}
	else
	{
		SessionMode = ECWSessionMode::Menu;
	}
	const int32 DifficultyOption = FMath::Clamp(UGameplayStatics::GetIntOption(Options, TEXT("difficulty"), 1), 0, 2);
	Difficulty = static_cast<cw::AiDifficulty>(DifficultyOption);
	UE_LOG(LogCivWar, Log, TEXT("InitGame mode=%s difficulty=%d"), *Mode, DifficultyOption);
}

void ACWGameMode::BeginPlay()
{
	Super::BeginPlay();
	if (SessionMode == ECWSessionMode::Menu && (GetNetMode() == NM_ListenServer || GetNetMode() == NM_DedicatedServer))
	{
		// 兜底：已经在监听网络连接的实例不应停留在主菜单
		SessionMode = ECWSessionMode::Lobby;
		bSessionInitialized = false;
	}
	EnsureSessionState();
	EnsureReplicator();
}

void ACWGameMode::EnsureReplicator()
{
	if (Replicator)
	{
		return;
	}
	FActorSpawnParameters Params;
	Params.Owner = this;
	Replicator = GetWorld()->SpawnActor<ACWBattleReplicator>(Params);
	if (ACWGameState* State = GetCWGameState())
	{
		State->Replicator = Replicator;
	}
}

void ACWGameMode::EnsureSessionState()
{
	// 本地玩家的 PostLogin 发生在 BeginPlay 之前：会话状态只初始化一次，避免覆盖已开始的倒计时
	ACWGameState* State = GetCWGameState();
	if (bSessionInitialized || !State)
	{
		return;
	}
	bSessionInitialized = true;
	State->bSinglePlayer = SessionMode == ECWSessionMode::Single;
	State->AiDifficulty = static_cast<uint8>(Difficulty);
	if (const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>())
	{
		State->DataChecksum = DataSys->GetChecksum();
	}
	State->SetPhase(SessionMode == ECWSessionMode::Menu ? ECWMatchPhase::Menu : ECWMatchPhase::Lobby);
	if (SessionMode == ECWSessionMode::Lobby)
	{
		State->HostAddress = DescribeHostAddress();
	}
	UpdateLobbySlots();
}

FString ACWGameMode::DescribeHostAddress() const
{
	FString Result;
	if (ISocketSubsystem* Sockets = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM))
	{
		bool bCanBind = false;
		const TSharedRef<FInternetAddr> Addr = Sockets->GetLocalHostAddr(*GLog, bCanBind);
		if (Addr->IsValid())
		{
			Result = Addr->ToString(false);
		}
	}
	const int32 Port = GetWorld()->URL.Port;
	return FString::Printf(TEXT("%s:%d"), Result.IsEmpty() ? TEXT("127.0.0.1") : *Result, Port);
}

void ACWGameMode::PreLogin(const FString& Options, const FString& Address, const FUniqueNetIdRepl& UniqueId, FString& ErrorMessage)
{
	Super::PreLogin(Options, Address, UniqueId, ErrorMessage);
	if (!ErrorMessage.IsEmpty())
	{
		return;
	}
	if (SessionMode != ECWSessionMode::Lobby)
	{
		// 单人与菜单实例只允许本地玩家
		if (GetNumPlayers() >= 1)
		{
			ErrorMessage = TEXT("该房间不接受联机玩家");
		}
		return;
	}
	const ACWGameState* State = GetCWGameState();
	if (State && State->GetPhase() != ECWMatchPhase::Lobby)
	{
		ErrorMessage = TEXT("对局正在进行，无法加入");
		return;
	}
	if (FindFreeTeam() < 0)
	{
		ErrorMessage = TEXT("房间已满");
	}
}

int32 ACWGameMode::FindFreeTeam(const AController* Ignore) const
{
	bool bUsed[2] = { false, false };
	if (const ACWGameState* State = GetCWGameState())
	{
		for (const APlayerState* PS : State->PlayerArray)
		{
			const ACWPlayerState* CPS = Cast<ACWPlayerState>(PS);
			if (CPS && CPS->GetOwner() != Ignore && CPS->GetTeam() >= 0 && CPS->GetTeam() < 2)
			{
				bUsed[CPS->GetTeam()] = true;
			}
		}
	}
	if (!bUsed[0])
	{
		return 0;
	}
	if (!bUsed[1])
	{
		return 1;
	}
	return -1;
}

void ACWGameMode::PostLogin(APlayerController* NewPlayer)
{
	Super::PostLogin(NewPlayer);
	EnsureSessionState();
	ACWPlayerState* PS = NewPlayer ? NewPlayer->GetPlayerState<ACWPlayerState>() : nullptr;
	ACWGameState* State = GetCWGameState();
	if (!PS || !State)
	{
		return;
	}
	switch (SessionMode)
	{
	case ECWSessionMode::Menu:
		PS->SetTeam(0);
		break;
	case ECWSessionMode::Single:
		PS->SetTeam(0);
		UpdateLobbySlots();
		StartCountdown();
		break;
	case ECWSessionMode::Lobby:
	{
		const int32 Team = FindFreeTeam(NewPlayer);
		PS->SetTeam(Team);
		PS->SetReady(false);
		UpdateLobbySlots();
		if (Team == 1)
		{
			State->SetStatusMessage(FString::Printf(TEXT("%s 已加入房间"), *PS->GetPlayerName()));
		}
		break;
	}
	default:
		break;
	}
}

void ACWGameMode::Logout(AController* Exiting)
{
	const ACWPlayerState* PS = Exiting ? Exiting->GetPlayerState<ACWPlayerState>() : nullptr;
	const int32 Team = PS ? PS->GetTeam() : -1;
	const FString Name = PS ? PS->GetPlayerName() : FString();
	Super::Logout(Exiting);

	ACWGameState* State = GetCWGameState();
	if (SessionMode != ECWSessionMode::Lobby || !State || Team < 0)
	{
		return;
	}
	switch (State->GetPhase())
	{
	case ECWMatchPhase::InMatch:
		// 对局中离开：判负，剩余玩家获胜（只结算一次）
		if (Sim)
		{
			Sim->Forfeit(Team);
			ProcessSimEvents();
			State->SyncFromSim(*Sim);
		}
		EndMatch(1 - Team, ECWEndReason::Forfeit);
		State->SetStatusMessage(FString::Printf(TEXT("%s 已离开，对局判负"), *Name));
		break;
	case ECWMatchPhase::Countdown:
		ReturnToLobby();
		State->SetStatusMessage(FString::Printf(TEXT("%s 已离开，倒计时取消"), *Name));
		break;
	default:
		State->SetStatusMessage(FString::Printf(TEXT("%s 已离开房间"), *Name));
		break;
	}
	UpdateLobbySlots(Exiting);
}

void ACWGameMode::UpdateLobbySlots(const AController* Leaving)
{
	ACWGameState* State = GetCWGameState();
	if (!State)
	{
		return;
	}
	TArray<FCWLobbySlot> Slots;
	Slots.SetNum(2);
	for (const APlayerState* PS : State->PlayerArray)
	{
		const ACWPlayerState* CPS = Cast<ACWPlayerState>(PS);
		if (!CPS || CPS->GetOwner() == Leaving || CPS->GetTeam() < 0 || CPS->GetTeam() > 1)
		{
			continue;
		}
		FCWLobbySlot& Slot = Slots[CPS->GetTeam()];
		Slot.bOccupied = true;
		Slot.bReady = CPS->IsReady();
		Slot.Name = CPS->GetPlayerName();
	}
	if (SessionMode == ECWSessionMode::Single)
	{
		Slots[1].bOccupied = true;
		Slots[1].bReady = true;
		Slots[1].bIsAI = true;
		static const TCHAR* DifficultyNames[] = { TEXT("简单"), TEXT("普通"), TEXT("困难") };
		Slots[1].Name = FString::Printf(TEXT("电脑（%s）"), DifficultyNames[static_cast<int32>(Difficulty)]);
	}
	State->LobbySlots = Slots;
}

void ACWGameMode::HandleReady(ACWPlayerController* PC, bool bReady)
{
	ACWGameState* State = GetCWGameState();
	ACWPlayerState* PS = PC ? PC->GetPlayerState<ACWPlayerState>() : nullptr;
	if (!State || !PS || SessionMode != ECWSessionMode::Lobby || PS->GetTeam() < 0)
	{
		return;
	}
	if (State->GetPhase() != ECWMatchPhase::Lobby && State->GetPhase() != ECWMatchPhase::Countdown)
	{
		return;
	}
	PS->SetReady(bReady);
	UpdateLobbySlots();
	const TArray<FCWLobbySlot>& Slots = State->GetLobbySlots();
	const bool bAllReady = Slots[0].bOccupied && Slots[1].bOccupied && Slots[0].bReady && Slots[1].bReady;
	if (bAllReady && State->GetPhase() == ECWMatchPhase::Lobby)
	{
		StartCountdown();
	}
	else if (!bAllReady && State->GetPhase() == ECWMatchPhase::Countdown)
	{
		ReturnToLobby(); // 有人取消准备
	}
}

void ACWGameMode::StartCountdown()
{
	ACWGameState* State = GetCWGameState();
	if (!State)
	{
		return;
	}
	State->SetStatusMessage(FString());
	State->SetPhase(ECWMatchPhase::Countdown, CountdownSeconds);
}

void ACWGameMode::StartMatch()
{
	ACWGameState* State = GetCWGameState();
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!State || !DataSys || !DataSys->IsLoaded())
	{
		UE_LOG(LogCivWar, Error, TEXT("无法开始对局：数据未加载"));
		if (State)
		{
			State->SetStatusMessage(TEXT("数据加载失败，无法开始对局"));
			State->SetPhase(ECWMatchPhase::Lobby);
		}
		return;
	}
	Sim = MakeUnique<cw::Simulation>(DataSys->GetData(), static_cast<uint32>(FMath::Rand()) * 2654435761u + 1u);
	Sim->Start();
#if WITH_EDITOR
	int32 EraArtFixtureAge = -1;
	const bool bEraArtFixture = GetNetMode() == NM_Standalone && SessionMode == ECWSessionMode::Single &&
		FParse::Value(FCommandLine::Get(), TEXT("cwerafixture="), EraArtFixtureAge) &&
		EraArtFixtureAge >= 1 && EraArtFixtureAge <= 4 && PrepareEraArtFixture(EraArtFixtureAge);
	const bool bStoneEraFixture = GetNetMode() == NM_Standalone && SessionMode == ECWSessionMode::Single &&
		FParse::Param(FCommandLine::Get(), TEXT("cwstoneerafixture"));
	const bool bRockTowerFixture = GetNetMode() == NM_Standalone && SessionMode == ECWSessionMode::Single &&
		FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerfixture")) &&
		(FParse::Param(FCommandLine::Get(), TEXT("cwdefaultartfixture")) ||
			(FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerpilot")) &&
			FParse::Param(FCommandLine::Get(), TEXT("cwbasestonepilot"))));
	if (bStoneEraFixture || bRockTowerFixture)
	{
		const cw::GameData& FixtureData = DataSys->GetData();
		int32 TowerDefinition = -1;
		for (int32 Index = 0; Index < static_cast<int32>(FixtureData.Turrets.size()); ++Index)
		{
			if (FixtureData.Turrets[Index].Age == 0 && DataSys->GetTurretVisualKey(Index) == FName(TEXT("Turret_RockTower"))) TowerDefinition = Index;
		}
		if (TowerDefinition >= 0 && FixtureData.Rules.MaxTurretSlots == 3)
		{
			for (int32 FixtureTeam = 0; FixtureTeam < 2; ++FixtureTeam)
			{
				const double GoldBefore = Sim->Team(FixtureTeam).Gold;
				for (int32 FixtureSlot = 0; FixtureSlot < 3; ++FixtureSlot)
				{
					if (!Sim->Team(FixtureTeam).Turrets[FixtureSlot].Unlocked)
					{
						const int32 SlotCost = Sim->NextTurretSlotCost(FixtureTeam);
						if (SlotCost < 0) break;
						Sim->DebugGrantGold(FixtureTeam, SlotCost);
						cw::Command Unlock;
						Unlock.Type = cw::CommandType::BuyTurretSlot;
						if (Sim->Apply(FixtureTeam, Unlock) != cw::CommandResult::Ok) break;
					}
					Sim->DebugGrantGold(FixtureTeam, FixtureData.Turrets[TowerDefinition].Cost);
					cw::Command Build;
					Build.Type = cw::CommandType::BuildTurret;
					Build.A = FixtureSlot;
					Build.B = TowerDefinition;
					const cw::CommandResult Result = Sim->Apply(FixtureTeam, Build);
					UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ROCK_TOWER_FIXTURE team=%d slot=%d result=%d source=normal_sim_commands standalone_editor_only=true"), FixtureTeam, FixtureSlot, static_cast<int32>(Result));
					if (Result != cw::CommandResult::Ok) break;
				}
				UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ROCK_TOWER_FIXTURE_GOLD team=%d before=%.3f after=%.3f"), FixtureTeam, GoldBefore, Sim->Team(FixtureTeam).Gold);
			}
		}
	}
	if (bStoneEraFixture)
	{
		// The review starts with real training queues. Units still pay their normal
		// costs, take their normal training time and use authoritative combat.
		const cw::GameData& FixtureData = DataSys->GetData();
		for (int32 FixtureTeam = 0; FixtureTeam < 2; ++FixtureTeam)
		{
			const double GoldBefore = Sim->Team(FixtureTeam).Gold;
			for (const TCHAR* Key : { TEXT("Unit_StoneAxe"), TEXT("Unit_StoneSlinger"), TEXT("Unit_BeastRider"),
				TEXT("Unit_StoneSlinger"), TEXT("Unit_BeastRider") })
			{
				for (int32 Index = 0; Index < static_cast<int32>(FixtureData.Units.size()); ++Index)
				{
					if (FixtureData.Units[Index].Age != 0 || FixtureData.Units[Index].IsChampion ||
						DataSys->GetUnitVisualKey(Index) != FName(Key)) continue;
					Sim->DebugGrantGold(FixtureTeam, FixtureData.Units[Index].Cost);
					cw::Command Train;
					Train.Type = cw::CommandType::Train;
					Train.A = Index;
					const cw::CommandResult Result = Sim->Apply(FixtureTeam, Train);
					UE_LOG(LogCivWar, Display, TEXT("CIVWAR_STONE_ERA_FIXTURE team=%d asset=%s result=%d source=normal_sim_training standalone_editor_only=true"),
						FixtureTeam, Key, static_cast<int32>(Result));
					break;
				}
			}
			UE_LOG(LogCivWar, Display, TEXT("CIVWAR_STONE_ERA_FIXTURE_GOLD team=%d before=%.3f after=%.3f champion=%d"),
				FixtureTeam, GoldBefore, Sim->Team(FixtureTeam).Gold, Sim->Team(FixtureTeam).ChampionId);
		}
	}
#endif
	if (FParse::Param(FCommandLine::Get(), TEXT("cwstress")))
	{
		// 性能压力测试：双方资金充足，配合 -cwautoplay 让场上单位数量接近上限
		Sim->DebugGrantGold(0, 50000.0);
		Sim->DebugGrantGold(1, 50000.0);
		UE_LOG(LogCivWar, Warning, TEXT("压力测试模式：双方各获得 50000 金币"));
	}
	if (SessionMode == ECWSessionMode::Single)
	{
		cw::AiConfig Config;
		Config.Difficulty = Difficulty;
		Config.Seed = static_cast<uint32>(FMath::Rand()) | 1u;
		Ai = MakeUnique<cw::AiPlayer>(1, Config);
	}
	else
	{
		Ai.Reset();
	}
	ShowcaseAi.Reset();
	#if WITH_EDITOR
	if (bStoneEraFixture || bEraArtFixture)
	{
		// Keep this explicit review in its requested era. The user can still issue
		// commands; the fixture supplies only the initial opposing armies.
		Ai.Reset();
	}
	int32 RockTowerDefender = -1;
	if (GetNetMode() == NM_Standalone && SessionMode == ECWSessionMode::Single &&
		FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerfixture")) &&
		(FParse::Param(FCommandLine::Get(), TEXT("cwdefaultartfixture")) ||
			(FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerpilot")) &&
			FParse::Param(FCommandLine::Get(), TEXT("cwbasestonepilot")))) &&
		FParse::Value(FCommandLine::Get(), TEXT("cwrocktowerdefender="), RockTowerDefender) &&
		(RockTowerDefender == 0 || RockTowerDefender == 1))
	{
		if (RockTowerDefender == 1) Ai.Reset();
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ROCK_TOWER_DEFENDER team=%d normal_enemy_movement=true"), RockTowerDefender);
	}
	#endif
	ShowcaseNextGrant = 40.f;
	if (SessionMode == ECWSessionMode::Single && FParse::Param(FCommandLine::Get(), TEXT("cwshowcase")))
	{
		cw::AiConfig Config;
		Config.Difficulty = Difficulty;
		Config.Seed = static_cast<uint32>(FMath::Rand()) | 1u;
		ShowcaseAi = MakeUnique<cw::AiPlayer>(0, Config);
		UE_LOG(LogCivWar, Warning, TEXT("展示模式：双方均由 AI 操控，每 60 秒补足下一时代所需经验与金币"));
	}
	CastInfo.Reset();
	Accumulator = 0.f;
	EnsureReplicator();
	Replicator->ClearAll();
	const cw::GameData& Data = DataSys->GetData();
	State->ResetMatchState(Data.Rules.StartGold, Data.Ages[0].BaseMaxHp);
	State->SyncFromSim(*Sim);
	State->SetPhase(ECWMatchPhase::InMatch);
	UE_LOG(LogCivWar, Log, TEXT("对局开始（%s）"), SessionMode == ECWSessionMode::Single ? TEXT("单人") : TEXT("联机"));
}

#if WITH_EDITOR
bool ACWGameMode::PrepareEraArtFixture(int32 Age)
{
	if (!Sim || Age < 1 || Age >= static_cast<int32>(Sim->Data().Ages.size())) return false;
	const cw::GameData& Data = Sim->Data();
	auto Apply = [this](int32 Team, cw::CommandType Type, int32 A = 0, int32 B = 0, float X = 0.f)
	{
		cw::Command Command;
		Command.Type = Type; Command.A = A; Command.B = B; Command.X = X;
		const cw::CommandResult Result = Sim->Apply(Team, Command);
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ERA_FIXTURE_COMMAND team=%d command=%d a=%d b=%d result=%d normal_sim=true"),
			Team, static_cast<int32>(Type), A, B, static_cast<int32>(Result));
		return Result == cw::CommandResult::Ok;
	};
	// Hold existing champions at home while the real upgrade clocks advance.
	// All combat, training and costs thereafter still use the normal simulation.
	for (int32 Team = 0; Team < 2; ++Team)
		Apply(Team, cw::CommandType::ChampionMove, 0, 0, Sim->BaseFrontX(Team));
	for (int32 Next = 1; Next <= Age; ++Next)
	{
		if (!Data.Ages[Next].Implemented) return false;
		for (int32 Team = 0; Team < 2; ++Team)
		{
			Sim->DebugGrantXp(Team, FMath::Max(0., static_cast<double>(Data.Ages[Next].XpToEnter) - Sim->Team(Team).Xp));
			Sim->DebugGrantGold(Team, Data.Ages[Next].GoldToEnter);
			if (!Apply(Team, cw::CommandType::UpgradeAge)) return false;
		}
		const int32 MaximumSteps = FMath::CeilToInt(Data.Ages[Next].UpgradeDuration / FixedStep) + 3;
		for (int32 Step = 0; Step < MaximumSteps && (Sim->Team(0).Upgrading || Sim->Team(1).Upgrading); ++Step)
			Sim->Step(FixedStep);
		if (Sim->Team(0).Age != Next || Sim->Team(1).Age != Next) return false;
	}
	std::vector<int32_t> TurretDefinitions;
	for (int32 Index = 0; Index < static_cast<int32>(Data.Turrets.size()); ++Index)
		if (Data.Turrets[Index].Age == Age) TurretDefinitions.push_back(Index);
	for (int32 Team = 0; Team < 2; ++Team)
	{
		// Resolve the normal offers so their selection cards do not cover the
		// unattended art captures. This remains inside the explicit fixture.
		for (int32 Pick = 0; Pick < Age + 2 && !Sim->Team(Team).Offer.empty(); ++Pick)
			if (!Apply(Team, cw::CommandType::ChooseDoctrine, 0)) return false;
		for (int32 Slot = 0; Slot < static_cast<int32>(Sim->Team(Team).Turrets.size()) && !TurretDefinitions.empty(); ++Slot)
		{
			if (!Sim->Team(Team).Turrets[Slot].Unlocked)
			{
				const int32 Cost = Sim->NextTurretSlotCost(Team);
				if (Cost < 0) return false;
				Sim->DebugGrantGold(Team, Cost);
				if (!Apply(Team, cw::CommandType::BuyTurretSlot)) return false;
			}
			const int32 Definition = TurretDefinitions[Slot % TurretDefinitions.size()];
			Sim->DebugGrantGold(Team, Data.Turrets[Definition].Cost);
			if (!Apply(Team, cw::CommandType::BuildTurret, Slot, Definition)) return false;
		}
		const auto Units = Data.UnitsForAge(Age);
		for (int32 Queue = 0; Queue < Data.Rules.QueueCapacity && !Units.empty(); ++Queue)
		{
			const int32 Slot = Queue % static_cast<int32>(Units.size());
			Sim->DebugGrantGold(Team, Sim->UnitCost(Team, Units[Slot]));
			if (!Apply(Team, cw::CommandType::Train, Slot)) return false;
		}
		Apply(Team, cw::CommandType::ChampionMove, 1);
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ERA_FIXTURE_READY team=%d age=%d queue=%d champion=%d sim_time=%.3f standalone_editor_only=true"),
			Team, Sim->Team(Team).Age, static_cast<int32>(Sim->Team(Team).Queue.size()), Sim->Team(Team).ChampionId, Sim->Time());
	}
	Sim->ClearEvents();
	return true;
}
#endif

void ACWGameMode::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ACWGameState* State = GetCWGameState();
	if (!State)
	{
		return;
	}
	if (State->GetPhase() == ECWMatchPhase::Countdown && State->GetPhaseTimeLeft() <= 0.f)
	{
		StartMatch();
	}
	else if (State->GetPhase() == ECWMatchPhase::InMatch)
	{
		StepMatch(DeltaSeconds);
	}
}

void ACWGameMode::StepMatch(float DeltaSeconds)
{
	if (!Sim)
	{
		return;
	}
	ACWGameState* State = GetCWGameState();
	// 卡顿时最多追赶 0.25 秒，避免“死亡螺旋”
	Accumulator += FMath::Min(DeltaSeconds, 0.25f);
	int32 Steps = 0;
	while (Accumulator >= FixedStep && Steps < 5 && Sim->Phase() == cw::MatchPhase::Running)
	{
		if (Ai)
		{
			Ai->Tick(*Sim, FixedStep);
		}
		if (ShowcaseAi)
		{
			ShowcaseAi->Tick(*Sim, FixedStep);
			if (Sim->Time() >= ShowcaseNextGrant)
			{
				ShowcaseNextGrant += 60.f;
				const cw::GameData& D = Sim->Data();
				for (int32 T = 0; T < 2; ++T)
				{
					const cw::TeamState& S = Sim->Team(T);
					const int32 Next = S.Age + 1;
					if (Next < static_cast<int32>(D.Ages.size()) && D.Ages[Next].Implemented)
					{
						Sim->DebugGrantXp(T, FMath::Max(0.0, static_cast<double>(D.Ages[Next].XpToEnter) - S.Xp));
						Sim->DebugGrantGold(T, FMath::Max(0.0, static_cast<double>(D.Ages[Next].GoldToEnter) + 400.0 - S.Gold));
					}
				}
			}
		}
		Sim->Step(FixedStep);
		ProcessSimEvents();
		Accumulator -= FixedStep;
		++Steps;
	}
	const float ServerTime = static_cast<float>(State->GetServerWorldTimeSeconds());
	Replicator->SyncFromSim(*Sim, ServerTime, ServerTime - Accumulator);
	State->SyncFromSim(*Sim);
	if (Sim->Phase() == cw::MatchPhase::Ended && State->GetPhase() == ECWMatchPhase::InMatch)
	{
		ECWEndReason Reason = ECWEndReason::BaseDestroyed;
		if (Sim->GetEndReason() == cw::EndReason::Forfeit)
		{
			Reason = ECWEndReason::Forfeit;
		}
		else if (Sim->GetEndReason() == cw::EndReason::TimeLimit)
		{
			Reason = ECWEndReason::TimeLimit;
		}
		EndMatch(Sim->Winner(), Reason);
	}
}

void ACWGameMode::ProcessSimEvents()
{
	if (!Sim)
	{
		return;
	}
	for (const cw::SimEvent& Ev : Sim->Events())
	{
		switch (Ev.Type)
		{
		case cw::EventType::TurretFired:
			#if WITH_EDITOR
			if (GetNetMode() == NM_Standalone && FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerfixture")) &&
				Ev.Team >= 0 && Ev.Team < 2 && Ev.A >= 0 && Ev.A < static_cast<int32>(Sim->Team(Ev.Team).Turrets.size()))
			{
				UE_LOG(LogCivWar, Display, TEXT("CIVWAR_ROCK_TOWER_AUTHORITY team=%d slot=%d seq=%d sim_time=%.6f target=%d target_x=%.6f"),
					Ev.Team, Ev.A, Sim->Team(Ev.Team).Turrets[Ev.A].FireSeq, Sim->Time(), Ev.B, Ev.X);
			}
			#endif
			break;
		case cw::EventType::SkillCast:
			CastInfo.Add(Ev.A, TPair<int32, float>(Ev.B, Ev.Value));
			break;
		case cw::EventType::SkillImpact:
		{
			const TPair<int32, float>* Info = CastInfo.Find(Ev.A);
			if (Info && Replicator)
			{
				Replicator->MulticastSkillImpact(static_cast<uint8>(Ev.Team), static_cast<uint8>(Info->Key), Ev.X, Info->Value, Ev.B);
			}
			CastInfo.Remove(Ev.A);
			break;
		}
		default:
			break;
		}
	}
	Sim->ClearEvents();
}

void ACWGameMode::EndMatch(int32 Winner, ECWEndReason Reason)
{
	ACWGameState* State = GetCWGameState();
	if (!State || State->GetPhase() == ECWMatchPhase::PostMatch)
	{
		return; // 结算只发生一次
	}
	State->SetResult(Winner, Reason);
	State->SetPhase(ECWMatchPhase::PostMatch);
	UE_LOG(LogCivWar, Log, TEXT("对局结束：胜者 %d，原因 %d，时长 %.1fs"), Winner, static_cast<int32>(Reason), Sim ? Sim->Time() : 0.f);
}

void ACWGameMode::ReturnToLobby()
{
	ACWGameState* State = GetCWGameState();
	if (!State)
	{
		return;
	}
	Sim.Reset();
	Ai.Reset();
	CastInfo.Reset();
	if (Replicator)
	{
		Replicator->ClearAll();
	}
	for (APlayerState* PS : State->PlayerArray)
	{
		if (ACWPlayerState* CPS = Cast<ACWPlayerState>(PS))
		{
			CPS->SetReady(false);
		}
	}
	UpdateLobbySlots();
	State->SetPhase(ECWMatchPhase::Lobby);
}

void ACWGameMode::HandleReturnToLobby(ACWPlayerController* PC)
{
	ACWGameState* State = GetCWGameState();
	if (!State || SessionMode != ECWSessionMode::Lobby || State->GetPhase() != ECWMatchPhase::PostMatch)
	{
		return;
	}
	ReturnToLobby();
}

void ACWGameMode::HandleRestartSingle(ACWPlayerController* PC)
{
	ACWGameState* State = GetCWGameState();
	if (!State || SessionMode != ECWSessionMode::Single || State->GetPhase() != ECWMatchPhase::PostMatch)
	{
		return;
	}
	Sim.Reset();
	Ai.Reset();
	Replicator->ClearAll();
	StartCountdown();
}

void ACWGameMode::HandleCommand(ACWPlayerController* PC, uint8 Type, int32 A, int32 B, float X)
{
	if (!PC)
	{
		return;
	}
	ACWGameState* State = GetCWGameState();
	if (!Sim || !State || State->GetPhase() != ECWMatchPhase::InMatch)
	{
		PC->ClientCommandResult(Type, static_cast<uint8>(cw::CommandResult::MatchNotRunning));
		return;
	}
	if (Type >= static_cast<uint8>(cw::CommandType::Count))
	{
		PC->ClientCommandResult(Type, static_cast<uint8>(cw::CommandResult::InvalidParam));
		return;
	}
	const ACWPlayerState* PS = PC->GetPlayerState<ACWPlayerState>();
	const int32 Team = PS ? PS->GetTeam() : -1; // 阵营只认服务器分配值
	cw::Command Cmd;
	Cmd.Type = static_cast<cw::CommandType>(Type);
	Cmd.A = A;
	Cmd.B = B;
	Cmd.X = X;
	const cw::CommandResult Result = Sim->Apply(Team, Cmd);
	if (Result == cw::CommandResult::Ok)
	{
		ProcessSimEvents();
		State->SyncFromSim(*Sim); // 立即同步，界面反馈更及时
	}
	else
	{
		PC->ClientCommandResult(Type, static_cast<uint8>(Result));
	}
}

#undef LOCTEXT_NAMESPACE
