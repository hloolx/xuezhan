// 血战文明 - 规则核心：统帅（随时代进化的英雄单位）与国策
#include "Simulation.h"

#include <algorithm>
#include <cmath>

namespace cw
{
	// ---------------- 统帅 ----------------

	const ChampionDef* Simulation::CurrentChampion(int32_t InTeam) const
	{
		const int32_t Index = Teams[InTeam].ChampionDef;
		return Index >= 0 && Index < static_cast<int32_t>(GameDataRef.Champions.size()) ? &GameDataRef.Champions[static_cast<size_t>(Index)] : nullptr;
	}

	const Unit* Simulation::ChampionUnit(int32_t InTeam) const
	{
		const int32_t Id = Teams[InTeam].ChampionId;
		if (Id < 0)
		{
			return nullptr;
		}
		const Unit* U = FindUnit(Id);
		return U != nullptr && IsAlive(*U) ? U : nullptr;
	}

	float Simulation::ChampionAbilityCooldown(int32_t InTeam) const
	{
		const ChampionDef* CD = CurrentChampion(InTeam);
		return CD != nullptr ? CD->AbilityCooldown * std::max(1.f + Teams[InTeam].Effects.ChampionCooldown, 0.3f) : 0.f;
	}

	float Simulation::ChampionRespawnTime(int32_t InTeam) const
	{
		const ChampionDef* CD = CurrentChampion(InTeam);
		return CD != nullptr ? CD->RespawnTime * std::max(1.f + Teams[InTeam].Effects.ChampionRespawn, 0.3f) : 0.f;
	}

	void Simulation::SpawnChampion(int32_t InTeam)
	{
		TeamState& S = Teams[InTeam];
		const ChampionDef* CD = CurrentChampion(InTeam);
		if (CD == nullptr || S.ChampionId >= 0)
		{
			return;
		}
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(CD->UnitDefIndex)];
		// 与普通单位相同：在己方城门内侧出生，敌军停在城门外侧，不会重叠
		const float X = BaseFrontX(InTeam) - static_cast<float>(Dir(InTeam)) * D.Radius;
		const int32_t Id = AddUnit(InTeam, CD->UnitDefIndex, X, std::max(GameDataRef.Rules.LaneRows, 1) / 2, true).Id;
		S.ChampionId = Id;
		S.ChampionRespawn = 0.f;
		Emit(EventType::UnitSpawned, InTeam, Id, CD->UnitDefIndex, X);
		Emit(EventType::ChampionSpawned, InTeam, Id, CD->UnitDefIndex, X);
	}

	void Simulation::EvolveChampion(int32_t InTeam)
	{
		TeamState& S = Teams[InTeam];
		const int32_t NewIndex = GameDataRef.ChampionForAge(S.Age);
		if (NewIndex == InvalidIndex || NewIndex == S.ChampionDef)
		{
			return;
		}
		S.ChampionDef = NewIndex;
		Unit* U = S.ChampionId >= 0 ? FindUnitMutable(S.ChampionId) : nullptr;
		if (U == nullptr || !IsAlive(*U))
		{
			return; // 阵亡中：复活时直接以新时代形态出现
		}
		// 同一个单位原地进化：保持生命比例；体型变大时向己方后退，避免与贴身的敌人重叠
		const float OldRadius = GameDataRef.Units[static_cast<size_t>(U->Def)].Radius;
		U->Def = GameDataRef.Champions[static_cast<size_t>(NewIndex)].UnitDefIndex;
		const float NewRadius = GameDataRef.Units[static_cast<size_t>(U->Def)].Radius;
		const float DirF = static_cast<float>(Dir(InTeam));
		if (NewRadius > OldRadius)
		{
			const float MinP = DirF * BaseFrontX(InTeam) - NewRadius;
			U->X = DirF * std::max(DirF * U->X - (NewRadius - OldRadius), MinP);
		}
		RefreshUnitStats(*U);
	}

	float Simulation::ChampionTargetProgress(int32_t InTeam, const Unit& Champ) const
	{
		const RulesDef& R = GameDataRef.Rules;
		const TeamState& S = Teams[InTeam];
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(Champ.Def)];
		const float DirF = static_cast<float>(Dir(InTeam));
		const float GateP = DirF * BaseFrontX(InTeam);
		const float MinP = GateP - D.Radius;
		const float MaxP = DirF * BaseFrontX(Enemy(InTeam)) - D.Radius;
		float P = GateP + R.ChampionGuardDistance;
		if (S.Order == ChampionOrder::Hold)
		{
			P = DirF * S.ChampionHoldX;
		}
		else
		{
			// 随军：跟到己方最前方的部队；场上没有部队时守在城门前
			for (const int32_t Idx : Order[InTeam])
			{
				const Unit& Ally = UnitList[static_cast<size_t>(Idx)];
				if (Ally.Champion || !IsAlive(Ally))
				{
					continue;
				}
				P = std::max(P, DirF * Ally.X);
				break;
			}
			if (S.Stance == ArmyStance::Hold)
			{
				P = std::min(P, GateP + R.HoldLineDistance);
			}
		}
		return std::min(std::max(P, MinP), MaxP);
	}

	void Simulation::StepChampionMovement(Unit& U, int32_t InTeam, float Dt)
	{
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
		const float DirF = static_cast<float>(Dir(InTeam));
		const float P = DirF * U.X;
		const float Target = ChampionTargetProgress(InTeam, U);
		const float Speed = D.MoveSpeed * U.SpeedMul;
		// 随军时允许领先部队一段距离（不来回抖动）；坚守时停在指定位置
		const float Slack = Teams[InTeam].Order == ChampionOrder::Follow ? 300.f : 0.5f;
		float NewP = P;
		if (Target > P + 0.5f)
		{
			// 前进：不能穿越敌军与敌方基地，但不受友军阻挡
			float Limit = DirF * BaseFrontX(Enemy(InTeam)) - D.Radius;
			for (const int32_t EIdx : Order[Enemy(InTeam)])
			{
				const Unit& Foe = UnitList[static_cast<size_t>(EIdx)];
				if (IsAlive(Foe))
				{
					Limit = std::min(Limit, DirF * Foe.X - (D.Radius + GameDataRef.Units[static_cast<size_t>(Foe.Def)].Radius));
					break;
				}
			}
			NewP = std::max(std::min(std::min(P + Speed * Dt, Target), Limit), P);
		}
		else if (Target < P - Slack)
		{
			NewP = std::max(P - Speed * Dt, Target);
		}
		const bool bMoved = std::fabs(NewP - P) > 0.001f;
		U.X = DirF * NewP;
		U.State = bMoved ? UnitState::Walking : UnitState::Blocked;
		if (bMoved && NewP > P)
		{
			U.WalkTime += Dt;
		}
		else
		{
			U.WalkTime = 0.f;
		}
	}

	void Simulation::StepChampions(float Dt)
	{
		const RulesDef& R = GameDataRef.Rules;
		for (Unit& U : UnitList)
		{
			U.BuffTime = std::max(0.f, U.BuffTime - Dt);
		}
		if (GameDataRef.Champions.empty())
		{
			return;
		}
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			TeamState& S = Teams[T];
			S.ChampionCooldown = std::max(0.f, S.ChampionCooldown - Dt);
			if (S.ChampionId < 0)
			{
				S.ChampionRespawn -= Dt;
				if (S.ChampionRespawn <= 0.f)
				{
					SpawnChampion(T);
				}
				continue;
			}
			Unit* U = FindUnitMutable(S.ChampionId);
			const ChampionDef* CD = CurrentChampion(T);
			if (U == nullptr || !IsAlive(*U) || CD == nullptr || std::fabs(U->X - BaseFrontX(T)) > R.ChampionBaseHealRadius)
			{
				continue;
			}
			// 回到城门附近休整：附近有敌人时不回血（避免统帅在城门口成为打不死的守门员）
			bool bThreatened = false;
			for (const Unit& Foe : UnitList)
			{
				if (Foe.Team != T && IsAlive(Foe) && std::fabs(Foe.X - U->X) <= R.ChampionBaseHealRadius)
				{
					bThreatened = true;
					break;
				}
			}
			if (!bThreatened)
			{
				U->Hp = std::min(U->MaxHp, U->Hp + U->MaxHp * CD->BaseRegen * Dt);
			}
		}
	}

	// ---------------- 国策 ----------------

	void Simulation::GrantDoctrinePick(int32_t InTeam)
	{
		if (GameDataRef.Doctrines.empty())
		{
			return;
		}
		TeamState& S = Teams[InTeam];
		S.PendingPicks += 1;
		if (S.Offer.empty())
		{
			GenerateOffer(InTeam);
		}
	}

	void Simulation::GenerateOffer(int32_t InTeam)
	{
		TeamState& S = Teams[InTeam];
		S.Offer.clear();
		std::vector<int32_t> Pool;
		for (size_t I = 0; I < GameDataRef.Doctrines.size(); ++I)
		{
			const DoctrineDef& D = GameDataRef.Doctrines[I];
			const bool bTaken = std::find(S.Doctrines.begin(), S.Doctrines.end(), static_cast<int32_t>(I)) != S.Doctrines.end();
			if (!bTaken && S.Age >= D.MinAge && (D.MaxAge < 0 || S.Age <= D.MaxAge))
			{
				Pool.push_back(static_cast<int32_t>(I));
			}
		}
		const int32_t Choices = std::max(GameDataRef.Rules.DoctrineChoices, 1);
		for (int32_t K = 0; K < Choices && !Pool.empty(); ++K)
		{
			const size_t Pick = static_cast<size_t>(NextRandom() % static_cast<uint32_t>(Pool.size()));
			S.Offer.push_back(Pool[Pick]);
			Pool.erase(Pool.begin() + static_cast<std::ptrdiff_t>(Pick));
		}
		if (S.Offer.empty())
		{
			S.PendingPicks = 0; // 已经没有可选的国策
			return;
		}
		Emit(EventType::DoctrineOffered, InTeam, static_cast<int32_t>(S.Offer.size()));
	}

	void Simulation::ApplyDoctrineEffects(int32_t InTeam)
	{
		TeamState& S = Teams[InTeam];
		S.Effects = GameDataRef.ComputeEffects(S.Doctrines);
		// 基地生命上限立即按比例变化
		const float OldMax = S.BaseMaxHp;
		S.BaseMaxHp = GameDataRef.Ages[static_cast<size_t>(S.Age)].BaseMaxHp * std::max(1.f + S.Effects.BaseHp, 0.2f);
		S.BaseHp = OldMax > 0.f ? S.BaseHp / OldMax * S.BaseMaxHp : S.BaseMaxHp;
		// 已在场的单位立即获得加成（生命按比例保持）
		RefreshTeamUnits(InTeam);
	}
}
