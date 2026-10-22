#include "Game/CWGameState.h"

#include "Net/CWBattleReplicator.h"
#include "Net/UnrealNetwork.h"
#include "Sim/Simulation.h"

ACWGameState::ACWGameState()
{
	SetNetUpdateFrequency(20.f);
	Teams.SetNum(2);
	LobbySlots.SetNum(2);
}

void ACWGameState::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(ACWGameState, Replicator);
	DOREPLIFETIME(ACWGameState, bSinglePlayer);
	DOREPLIFETIME(ACWGameState, AiDifficulty);
	DOREPLIFETIME(ACWGameState, DataChecksum);
	DOREPLIFETIME(ACWGameState, LobbySlots);
	DOREPLIFETIME(ACWGameState, HostAddress);
	DOREPLIFETIME(ACWGameState, MatchTime);
	DOREPLIFETIME(ACWGameState, Phase);
	DOREPLIFETIME(ACWGameState, PhaseEndServerTime);
	DOREPLIFETIME(ACWGameState, Teams);
	DOREPLIFETIME(ACWGameState, WinnerTeam);
	DOREPLIFETIME(ACWGameState, EndReason);
	DOREPLIFETIME(ACWGameState, SkillCasts);
	DOREPLIFETIME(ACWGameState, StatusMessage);
}

void ACWGameState::SetPhase(ECWMatchPhase NewPhase, float PhaseDuration)
{
	Phase = NewPhase;
	PhaseEndServerTime = PhaseDuration > 0.f ? static_cast<float>(GetServerWorldTimeSeconds()) + PhaseDuration : 0.f;
}

float ACWGameState::GetPhaseTimeLeft() const
{
	if (PhaseEndServerTime <= 0.f)
	{
		return 0.f;
	}
	return FMath::Max(0.f, PhaseEndServerTime - static_cast<float>(GetServerWorldTimeSeconds()));
}

const FCWTeamNetState& ACWGameState::GetTeam(int32 Team) const
{
	static const FCWTeamNetState Empty;
	return Teams.IsValidIndex(Team) ? Teams[Team] : Empty;
}

void ACWGameState::ResetMatchState(int32 StartGoldHint, float BaseHp)
{
	Teams.SetNum(2);
	for (FCWTeamNetState& T : Teams)
	{
		T = FCWTeamNetState();
		T.Gold = StartGoldHint;
		T.BaseHp = BaseHp;
		T.BaseMaxHp = BaseHp;
	}
	SkillCasts.Reset();
	WinnerTeam = -1;
	EndReason = ECWEndReason::None;
	MatchTime = 0.f;
}

void ACWGameState::SetResult(int32 InWinner, ECWEndReason InReason)
{
	WinnerTeam = InWinner;
	EndReason = InReason;
}

void ACWGameState::SetStatusMessage(const FString& Message)
{
	StatusMessage = Message;
}

void ACWGameState::SyncFromSim(const cw::Simulation& Sim)
{
	MatchTime = Sim.Time();
	for (int32 T = 0; T < 2; ++T)
	{
		const cw::TeamState& S = Sim.Team(T);
		FCWTeamNetState& N = Teams[T];
		N.Gold = static_cast<int32>(S.Gold);
		N.Xp = static_cast<int32>(S.Xp);
		N.Age = static_cast<uint8>(S.Age);
		N.bUpgrading = S.Upgrading;
		N.UpgradeTimeLeft = S.UpgradeTimeLeft;
		N.BaseHp = S.BaseHp;
		N.BaseMaxHp = S.BaseMaxHp;
		N.SkillCooldown = S.SkillCooldown;
		N.BaseHitSeq = S.BaseHitSeq;
		N.EconomyLevel = static_cast<uint8>(S.EconomyLevel);
		N.Stance = static_cast<uint8>(S.Stance);
		N.Doctrines.SetNum(static_cast<int32>(S.Doctrines.size()));
		for (int32 I = 0; I < N.Doctrines.Num(); ++I)
		{
			N.Doctrines[I] = static_cast<uint8>(S.Doctrines[I]);
		}
		N.Offer.SetNum(static_cast<int32>(S.Offer.size()));
		for (int32 I = 0; I < N.Offer.Num(); ++I)
		{
			N.Offer[I] = static_cast<uint8>(S.Offer[I]);
		}
		N.PendingPicks = static_cast<uint8>(FMath::Clamp(S.PendingPicks, 0, 255));
		N.ChampionId = S.ChampionId;
		N.ChampionDef = static_cast<int16>(S.ChampionDef);
		N.ChampionRespawn = S.ChampionRespawn;
		N.ChampionOrder = static_cast<uint8>(S.Order);
		N.ChampionHoldX = S.ChampionHoldX;
		N.ChampionCooldown = S.ChampionCooldown;
		N.ChampionAbilitySeq = S.ChampionAbilitySeq;
		N.bLastStandUsed = S.LastStandUsed;
		N.TurretBoostTime = S.TurretBoostTime;
		N.Queue.SetNum(static_cast<int32>(S.Queue.size()));
		for (int32 I = 0; I < N.Queue.Num(); ++I)
		{
			N.Queue[I].Def = static_cast<uint16>(S.Queue[I].Def);
			N.Queue[I].Progress = S.Queue[I].Progress;
		}
		N.Turrets.SetNum(static_cast<int32>(S.Turrets.size()));
		for (int32 I = 0; I < N.Turrets.Num(); ++I)
		{
			const cw::TurretSlot& Slot = S.Turrets[I];
			FCWTurretNetSlot& Out = N.Turrets[I];
			Out.bUnlocked = Slot.Unlocked;
			Out.Def = static_cast<int16>(Slot.Def);
			Out.Level = static_cast<uint8>(Slot.Level);
			Out.TargetId = Slot.TargetId;
			Out.FireSeq = Slot.FireSeq;
			Out.Invested = Slot.Invested;
		}
		N.UnitsTrained = S.Stats.UnitsTrained;
		N.UnitsLost = S.Stats.UnitsLost;
		N.Kills = S.Stats.Kills;
		N.GoldSpent = S.Stats.GoldSpent;
		N.DamageToBase = S.Stats.DamageToBase;
		N.Promotions = S.Stats.Promotions;
		N.ChampionKills = S.Stats.ChampionKills;
	}

	// 技能预警：同步正在倒计时的施放
	const float Now = static_cast<float>(GetServerWorldTimeSeconds());
	SkillCasts.SetNum(static_cast<int32>(Sim.SkillCasts().size()));
	for (int32 I = 0; I < SkillCasts.Num(); ++I)
	{
		const cw::SkillCast& C = Sim.SkillCasts()[I];
		FCWSkillCastNet& Out = SkillCasts[I];
		if (Out.Id != C.Id)
		{
			Out.Id = C.Id;
			Out.Team = static_cast<uint8>(C.Team);
			Out.Skill = static_cast<uint8>(C.Skill);
			Out.X = C.X;
			Out.Radius = Sim.Data().Skills[C.Skill].Radius;
			Out.ImpactServerTime = Now + C.TimeLeft;
		}
	}
}
