#include "Net/CWBattleReplicator.h"

#include "Net/UnrealNetwork.h"
#include "Sim/Simulation.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

static void TraceAttackReplication(const cw::Simulation& Sim, const cw::Unit& Unit, float StartServer, float SnapshotServer)
{
	static const bool bEnabled = FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"));
	if (!bEnabled || Unit.AttackStartSimTime < 0.f || Sim.Data().Units[static_cast<size_t>(Unit.Def)].VisualKey != "Unit_StoneAxe") return;
	static const FString Run = [] { FString Value = TEXT("unspecified"); FParse::Value(FCommandLine::Get(), TEXT("cwarttimingrun="), Value); return Value; }();
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_TIMING run=%s role=server event=replicate_attack pid=%u id=%d seq=%u start_sim=%.6f sim=%.6f team=%d start_server=%.6f snapshot_server=%.6f"),
		*Run, FPlatformProcess::GetCurrentProcessId(), Unit.Id, static_cast<uint32>(Unit.AttackSeq), Unit.AttackStartSimTime, Sim.Time(), Unit.Team, StartServer, SnapshotServer);
}

static void TraceAttackOutcome(const cw::Simulation& Sim, const cw::Unit& Unit, float StartServer, float EndServer, float SnapshotServer)
{
	static const bool bEnabled = FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"));
	if (!bEnabled || Unit.AttackEndSimTime < 0.f || Sim.Data().Units[static_cast<size_t>(Unit.Def)].VisualKey != "Unit_StoneAxe") return;
	static const FString Run = [] { FString Value = TEXT("unspecified"); FParse::Value(FCommandLine::Get(), TEXT("cwarttimingrun="), Value); return Value; }();
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_TIMING run=%s role=server event=replicate_outcome pid=%u id=%d seq=%u start_sim=%.6f sim=%.6f team=%d start_server=%.6f end_sim=%.6f end_server=%.6f snapshot_server=%.6f outcome=%u"),
		*Run, FPlatformProcess::GetCurrentProcessId(), Unit.Id, static_cast<uint32>(Unit.AttackSeq), Unit.AttackStartSimTime, Sim.Time(), Unit.Team, StartServer, Unit.AttackEndSimTime, EndServer, SnapshotServer, static_cast<uint32>(Unit.AttackResult));
}

ACWBattleReplicator::ACWBattleReplicator()
{
	bReplicates = true;
	bAlwaysRelevant = true;
	SetReplicatingMovement(false);
	// 规则步长 20 Hz，同步频率与之一致
	SetNetUpdateFrequency(20.f);
	NetPriority = 3.f;
	PrimaryActorTick.bCanEverTick = false;
}

void ACWBattleReplicator::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(ACWBattleReplicator, Units);
	DOREPLIFETIME(ACWBattleReplicator, Projectiles);
}

void ACWBattleReplicator::ClearAll()
{
	Units.Items.Reset();
	Units.MarkArrayDirty();
	Projectiles.Items.Reset();
	Projectiles.MarkArrayDirty();
	UnitIdToItem.Reset();
	UnitAttackStartSimTimes.Reset();
	UnitAttackEndSimTimes.Reset();
	ProjectileExpire.Reset();
	KnownProjectiles.Reset();
}

void ACWBattleReplicator::SyncFromSim(const cw::Simulation& Sim, float ServerTime, float SnapshotServerTime)
{
	// ---------- 单位 ----------
	TSet<int32> Alive;
	Alive.Reserve(static_cast<int32>(Sim.Units().size()));
	for (const cw::Unit& U : Sim.Units())
	{
		Alive.Add(U.Id);
		const float QX = FMath::RoundToFloat(U.X);
		const uint16 QHp = static_cast<uint16>(FMath::Clamp(FMath::CeilToInt(U.Hp), 0, 65535));
		const uint16 QMaxHp = static_cast<uint16>(FMath::Clamp(FMath::CeilToInt(U.MaxHp), 1, 65535));
		const uint8 QState = static_cast<uint8>(U.State);
		const uint8 QFlags = static_cast<uint8>((U.Champion ? CWUnitFlags::Champion : 0) | (U.BuffTime > 0.f ? CWUnitFlags::Rallied : 0));
		const uint8 QRank = static_cast<uint8>(FMath::Clamp(U.Rank, 0, 3));
		const float QAttackStartServerTime = U.AttackStartSimTime >= 0.f ? SnapshotServerTime - (Sim.Time() - U.AttackStartSimTime) : -1.f;
		const float QAttackEndServerTime = U.AttackEndSimTime >= 0.f ? SnapshotServerTime - (Sim.Time() - U.AttackEndSimTime) : -1.f;
		const uint8 QAttackOutcome = static_cast<uint8>(U.AttackResult);

		if (const int32* Found = UnitIdToItem.Find(U.Id))
		{
			FCWUnitNetItem& Item = Units.Items[*Found];
			bool bChanged = false;
			auto Assign = [&bChanged](auto& Dst, const auto Src)
			{
				if (Dst != Src)
				{
					Dst = Src;
					bChanged = true;
				}
			};
			Assign(Item.X, QX);
			Assign(Item.Hp, QHp);
			Assign(Item.State, QState);
			const float* PreviousAttackStart = UnitAttackStartSimTimes.Find(U.Id);
			if (Item.AttackSeq != U.AttackSeq || !PreviousAttackStart || *PreviousAttackStart != U.AttackStartSimTime)
			{
				Assign(Item.AttackStartServerTime, QAttackStartServerTime);
				UnitAttackStartSimTimes.Add(U.Id, U.AttackStartSimTime);
				TraceAttackReplication(Sim, U, Item.AttackStartServerTime, SnapshotServerTime);
			}
			Assign(Item.AttackSeq, U.AttackSeq);
			const float* PreviousAttackEnd = UnitAttackEndSimTimes.Find(U.Id);
			if (Item.AttackOutcome != QAttackOutcome || !PreviousAttackEnd || *PreviousAttackEnd != U.AttackEndSimTime)
			{
				Assign(Item.AttackOutcome, QAttackOutcome);
				Assign(Item.AttackEndServerTime, QAttackEndServerTime);
				UnitAttackEndSimTimes.Add(U.Id, U.AttackEndSimTime);
				TraceAttackOutcome(Sim, U, Item.AttackStartServerTime, Item.AttackEndServerTime, SnapshotServerTime);
			}
			Assign(Item.HitSeq, U.HitSeq);
			Assign(Item.TargetId, U.TargetId);
			Assign(Item.MaxHp, QMaxHp);
			Assign(Item.Rank, QRank);
			Assign(Item.Flags, QFlags);
			Assign(Item.Def, static_cast<uint16>(U.Def)); // 统帅随时代原地进化
			if (bChanged)
			{
				Units.MarkItemDirty(Item);
			}
			continue;
		}

		FCWUnitNetItem& Item = Units.Items.AddDefaulted_GetRef();
		Item.Id = U.Id;
		Item.Team = static_cast<uint8>(U.Team);
		Item.Row = static_cast<uint8>(U.Row);
		Item.Def = static_cast<uint16>(U.Def);
		Item.X = QX;
		Item.Hp = QHp;
		Item.State = QState;
		Item.AttackSeq = U.AttackSeq;
		Item.AttackStartServerTime = QAttackStartServerTime;
		Item.AttackOutcome = QAttackOutcome;
		Item.AttackEndServerTime = QAttackEndServerTime;
		UnitAttackEndSimTimes.Add(U.Id, U.AttackEndSimTime);
		UnitAttackStartSimTimes.Add(U.Id, U.AttackStartSimTime);
		TraceAttackReplication(Sim, U, Item.AttackStartServerTime, SnapshotServerTime);
		TraceAttackOutcome(Sim, U, Item.AttackStartServerTime, Item.AttackEndServerTime, SnapshotServerTime);
		Item.HitSeq = U.HitSeq;
		Item.TargetId = U.TargetId;
		Item.MaxHp = QMaxHp;
		Item.Rank = QRank;
		Item.Flags = QFlags;
		Units.MarkItemDirty(Item);
		UnitIdToItem.Add(U.Id, Units.Items.Num() - 1);
	}

	bool bUnitsRemoved = false;
	for (int32 I = Units.Items.Num() - 1; I >= 0; --I)
	{
		if (!Alive.Contains(Units.Items[I].Id))
		{
			UnitAttackStartSimTimes.Remove(Units.Items[I].Id);
			UnitAttackEndSimTimes.Remove(Units.Items[I].Id);
			Units.Items.RemoveAtSwap(I);
			bUnitsRemoved = true;
		}
	}
	if (bUnitsRemoved)
	{
		Units.MarkArrayDirty();
		UnitIdToItem.Reset();
		for (int32 I = 0; I < Units.Items.Num(); ++I)
		{
			UnitIdToItem.Add(Units.Items[I].Id, I);
		}
	}

	// ---------- 投射物：只同步发射 ----------
	TSet<int32> Live;
	for (const cw::Projectile& P : Sim.Projectiles())
	{
		Live.Add(P.Id);
		if (KnownProjectiles.Contains(P.Id))
		{
			continue;
		}
		KnownProjectiles.Add(P.Id);
		FCWProjectileNetItem& Item = Projectiles.Items.AddDefaulted_GetRef();
		Item.Id = P.Id;
		Item.Team = static_cast<uint8>(P.Team);
		Item.SourceUnit = P.SourceUnit;
		Item.SourceSlot = static_cast<int8>(P.SourceTurretSlot);
		Item.TargetId = P.TargetId;
		Item.StartX = P.X;
		Item.TargetX = P.TargetX;
		Item.Speed = P.Speed;
		Item.Splash = P.SplashRadius;
		if (P.SourceTurretSlot >= 0)
		{
			const cw::TeamState& T = Sim.Team(P.Team);
			const int32 Def = T.Turrets.size() > static_cast<size_t>(P.SourceTurretSlot) ? T.Turrets[P.SourceTurretSlot].Def : 0;
			Item.VisualDef = static_cast<uint16>(FMath::Max(Def, 0));
		}
		else if (const cw::Unit* Shooter = Sim.FindUnit(P.SourceUnit))
		{
			Item.VisualDef = static_cast<uint16>(Shooter->Def);
		}
		Projectiles.MarkItemDirty(Item);
	}
	for (const int32 Id : KnownProjectiles)
	{
		if (!Live.Contains(Id) && !ProjectileExpire.Contains(Id))
		{
			ProjectileExpire.Add(Id, ServerTime + 0.5f);
		}
	}
	bool bProjectilesRemoved = false;
	for (int32 I = Projectiles.Items.Num() - 1; I >= 0; --I)
	{
		const int32 Id = Projectiles.Items[I].Id;
		const float* Expire = ProjectileExpire.Find(Id);
		if (Expire && *Expire <= ServerTime)
		{
			Projectiles.Items.RemoveAtSwap(I);
			ProjectileExpire.Remove(Id);
			KnownProjectiles.Remove(Id);
			bProjectilesRemoved = true;
		}
	}
	if (bProjectilesRemoved)
	{
		Projectiles.MarkArrayDirty();
	}
}

void ACWBattleReplicator::MulticastSkillImpact_Implementation(uint8 Team, uint8 Skill, float X, float Radius, int32 Hits)
{
	OnSkillImpact.Broadcast(Team, Skill, X, Radius, Hits);
}
