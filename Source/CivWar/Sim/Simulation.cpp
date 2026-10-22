#include "Simulation.h"

#include <algorithm>
#include <cmath>

#if defined(WITH_ENGINE) && WITH_ENGINE
#include "CoreMinimal.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#endif

namespace cw
{
	static void RecordAttackEnd(Unit& Attacker, AttackOutcome Outcome, float Time)
	{
		Attacker.AttackResult = Outcome;
		Attacker.AttackEndSimTime = Time;
	}

	static void TraceArtTiming([[maybe_unused]] const char* Event, [[maybe_unused]] const Unit& Attacker, [[maybe_unused]] const UnitDef& Definition, [[maybe_unused]] float Time, [[maybe_unused]] const char* Reason)
	{
#if defined(WITH_ENGINE) && WITH_ENGINE
		static const bool bEnabled = FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"));
		if (!bEnabled || Definition.VisualKey != "Unit_StoneAxe" || Attacker.AttackStartSimTime < 0.f) return;
		static const FString Run = [] { FString Value = TEXT("unspecified"); FParse::Value(FCommandLine::Get(), TEXT("cwarttimingrun="), Value); return Value; }();
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_TIMING run=%s role=server event=%hs pid=%u id=%d seq=%u start_sim=%.6f sim=%.6f team=%d target=%d reason=%hs windup=%.6f"),
			*Run, Event, FPlatformProcess::GetCurrentProcessId(), Attacker.Id, static_cast<uint32>(Attacker.AttackSeq), Attacker.AttackStartSimTime, Time, Attacker.Team, Attacker.TargetId, Reason, Attacker.Windup);
#endif
	}
	// 射程判定容差（厘米），吸收浮点误差
	constexpr float SimRangeTolerance = 0.5f;

	Simulation::Simulation(const GameData& InData, uint32_t InSeed)
		: GameDataRef(InData)
		, Seed(InSeed != 0 ? InSeed : 1u)
	{
		for (const UnitDef& D : GameDataRef.Units)
		{
			MaxUnitRadius = std::max(MaxUnitRadius, D.Radius);
		}
		Reset();
	}

	void Simulation::Reset()
	{
		CurrentPhase = MatchPhase::NotStarted;
		WinnerTeam = -1;
		Reason = EndReason::None;
		SimTime = 0.f;
		TickCount = 0;
		bSuddenDeathAnnounced = false;
		PendingHits.clear();
		NextUnitId = 1;
		NextProjectileId = 1;
		NextCastId = 1;
		RngState = (Seed * 2654435761u) ^ 0x9E3779B9u;
		if (RngState == 0)
		{
			RngState = 1u;
		}
		UnitList.clear();
		ProjectileList.clear();
		CastList.clear();
		EventList.clear();
		IdToIndex.clear();
		const RulesDef& R = GameDataRef.Rules;
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			TeamState& S = Teams[T];
			S = TeamState();
			S.Gold = R.StartGold;
			S.Age = 0;
			S.BaseMaxHp = GameDataRef.Ages.empty() ? 1000.f : GameDataRef.Ages[0].BaseMaxHp;
			S.BaseHp = S.BaseMaxHp;
			S.Turrets.resize(static_cast<size_t>(std::max(R.MaxTurretSlots, 0)));
			for (int32_t I = 0; I < R.InitialTurretSlots && I < static_cast<int32_t>(S.Turrets.size()); ++I)
			{
				S.Turrets[I].Unlocked = true;
			}
			S.ChampionDef = GameDataRef.ChampionForAge(0);
			S.ChampionHoldX = BaseFrontX(T);
			Order[T].clear();
		}
	}

	void Simulation::Start()
	{
		if (CurrentPhase != MatchPhase::NotStarted)
		{
			return;
		}
		CurrentPhase = MatchPhase::Running;
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			SpawnChampion(T);
			GrantDoctrinePick(T); // 开局第一项国策
		}
	}

	uint32_t Simulation::NextRandom()
	{
		// xorshift32：同一种子下结果可复现
		uint32_t X = RngState;
		X ^= X << 13;
		X ^= X >> 17;
		X ^= X << 5;
		RngState = X;
		return X;
	}

	void Simulation::Forfeit(int32_t LoserTeam)
	{
		if (LoserTeam >= 0 && LoserTeam < TeamCount)
		{
			EndMatch(Enemy(LoserTeam), EndReason::Forfeit);
		}
	}

	void Simulation::DebugGrantGold(int32_t InTeam, double Amount)
	{
		if (InTeam >= 0 && InTeam < TeamCount && Amount > 0.0)
		{
			Teams[InTeam].Gold += Amount;
		}
	}

	void Simulation::DebugGrantXp(int32_t InTeam, double Amount)
	{
		if (InTeam >= 0 && InTeam < TeamCount && Amount > 0.0)
		{
			Teams[InTeam].Xp += Amount;
		}
	}

	float Simulation::BaseX(int32_t InTeam) const
	{
		return InTeam == 0 ? 0.f : GameDataRef.Rules.LaneLength;
	}

	float Simulation::BaseFrontX(int32_t InTeam) const
	{
		return BaseX(InTeam) + static_cast<float>(Dir(InTeam)) * GameDataRef.Rules.BaseHalfWidth;
	}

	float Simulation::TurretX(int32_t InTeam) const
	{
		return BaseFrontX(InTeam) - static_cast<float>(Dir(InTeam)) * GameDataRef.Rules.TurretOffset;
	}

	const Unit* Simulation::FindUnit(int32_t Id) const
	{
		const auto It = IdToIndex.find(Id);
		return It == IdToIndex.end() ? nullptr : &UnitList[static_cast<size_t>(It->second)];
	}

	Unit* Simulation::FindUnitMutable(int32_t Id)
	{
		const auto It = IdToIndex.find(Id);
		return It == IdToIndex.end() ? nullptr : &UnitList[static_cast<size_t>(It->second)];
	}

	void Simulation::RebuildIndex()
	{
		IdToIndex.clear();
		for (size_t I = 0; I < UnitList.size(); ++I)
		{
			IdToIndex[UnitList[I].Id] = static_cast<int32_t>(I);
		}
	}

	void Simulation::BuildOrders()
	{
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			std::vector<int32_t>& O = Order[T];
			O.clear();
			for (size_t I = 0; I < UnitList.size(); ++I)
			{
				if (UnitList[I].Team == T && IsAlive(UnitList[I]))
				{
					O.push_back(static_cast<int32_t>(I));
				}
			}
			const float D = static_cast<float>(Dir(T));
			std::sort(O.begin(), O.end(), [this, D](int32_t L, int32_t R)
			{
				const float PL = D * UnitList[static_cast<size_t>(L)].X;
				const float PR = D * UnitList[static_cast<size_t>(R)].X;
				if (PL != PR)
				{
					return PL > PR; // 前进方向上更靠前的排前面
				}
				return UnitList[static_cast<size_t>(L)].Id < UnitList[static_cast<size_t>(R)].Id;
			});
		}
	}

	float Simulation::EdgeDistance(const Unit& A, const Unit& B) const
	{
		return std::fabs(A.X - B.X) - GameDataRef.Units[A.Def].Radius - GameDataRef.Units[B.Def].Radius;
	}

	float Simulation::EdgeDistanceToBase(const Unit& A, int32_t BaseTeam) const
	{
		return std::fabs(BaseFrontX(BaseTeam) - A.X) - GameDataRef.Units[A.Def].Radius;
	}

	float Simulation::UnitRange(const Unit& U) const
	{
		return GameDataRef.Units[static_cast<size_t>(U.Def)].Range * U.RangeMul;
	}

	bool Simulation::IsTargetValid(const Unit& U, int32_t TargetId) const
	{
		const float Range = UnitRange(U) + SimRangeTolerance;
		if (TargetId == TargetBase)
		{
			return EdgeDistanceToBase(U, Enemy(U.Team)) <= Range;
		}
		if (TargetId < 0)
		{
			return false;
		}
		const Unit* T = FindUnit(TargetId);
		return T != nullptr && IsAlive(*T) && T->Team != U.Team && EdgeDistance(U, *T) <= Range;
	}

	int32_t Simulation::SelectTarget(const Unit& U) const
	{
		const UnitDef& D = GameDataRef.Units[U.Def];
		const int32_t E = Enemy(U.Team);
		const float Range = UnitRange(U) + SimRangeTolerance;
		const float BaseDist = EdgeDistanceToBase(U, E);
		const bool bBaseInRange = BaseDist <= Range;

		int32_t Best = TargetNone;
		float BestScore = 0.f;
		auto Consider = [&Best, &BestScore](int32_t Id, float Score)
		{
			if (Best == TargetNone || Score < BestScore)
			{
				Best = Id;
				BestScore = Score;
			}
		};

		// 敌方单位按距离从近到远排列；超出“射程 + 最大半径”即可提前结束
		for (const int32_t Idx : Order[E])
		{
			const Unit& Other = UnitList[static_cast<size_t>(Idx)];
			if (!IsAlive(Other))
			{
				continue;
			}
			const float CenterDist = std::fabs(Other.X - U.X) - D.Radius;
			if (CenterDist - MaxUnitRadius > Range)
			{
				break;
			}
			const float Dist = EdgeDistance(U, Other);
			if (Dist > Range)
			{
				continue;
			}
			const UnitDef& OD = GameDataRef.Units[Other.Def];
			float Score = Dist;
			switch (D.Targeting)
			{
			case TargetRule::LowestHp:
				Score = Other.Hp;
				break;
			case TargetRule::PreferRanged:
				Score = OD.Role == UnitRole::Ranged ? Dist - 1.0e6f : Dist;
				break;
			case TargetRule::PreferHeavy:
				Score = OD.Role == UnitRole::Heavy ? Dist - 1.0e6f : Dist;
				break;
			default:
				break;
			}
			Consider(Other.Id, Score);
		}

		if (bBaseInRange)
		{
			if (D.Targeting == TargetRule::PreferStructure)
			{
				return TargetBase;
			}
			if (Best == TargetNone)
			{
				return TargetBase;
			}
			// 默认规则下，同等距离优先打单位（守住城门的敌人）
			if (D.Targeting == TargetRule::Nearest && BaseDist + 1.f < BestScore)
			{
				return TargetBase;
			}
		}
		return Best;
	}

	void Simulation::Step(float Dt)
	{
		if (CurrentPhase != MatchPhase::Running || Dt <= 0.f)
		{
			return;
		}
		SimTime += Dt;
		++TickCount;
		StepEconomy(Dt);
		StepAgeUpgrades(Dt);
		StepTraining(Dt);
		StepChampions(Dt);
		BuildOrders();
		StepUnits(Dt);
		StepProjectiles(Dt);
		StepTurrets(Dt);
		StepSkills(Dt);
		StepDeaths(Dt);
		if (CurrentPhase == MatchPhase::Running && GameDataRef.Rules.MatchTimeLimit > 0.f && SimTime >= GameDataRef.Rules.MatchTimeLimit)
		{
			EndByTimeLimit();
		}
	}

	bool Simulation::IsSuddenDeath() const
	{
		return SimTime >= GameDataRef.Rules.SuddenDeathTime;
	}

	float Simulation::BaseDamageMultiplier() const
	{
		const RulesDef& R = GameDataRef.Rules;
		if (!IsSuddenDeath())
		{
			return 1.f;
		}
		const float Minutes = (SimTime - R.SuddenDeathTime) / 60.f;
		return std::min(R.SuddenDeathBaseDamage + R.SuddenDeathRampPerMinute * Minutes, R.SuddenDeathMaxMultiplier);
	}

	float Simulation::IncomeMultiplier() const
	{
		return IsSuddenDeath() ? GameDataRef.Rules.SuddenDeathIncomeMultiplier : 1.f;
	}

	float Simulation::TurretDamageMultiplier() const
	{
		const RulesDef& R = GameDataRef.Rules;
		if (!IsSuddenDeath())
		{
			return 1.f;
		}
		const float Minutes = (SimTime - R.SuddenDeathTime) / 60.f;
		return std::max(R.SuddenDeathTurretMin, 1.f - R.SuddenDeathTurretDecayPerMinute * Minutes);
	}

	void Simulation::EndByTimeLimit()
	{
		// 比较基地剩余生命比例；相同则比较击杀数；仍相同为平局（Winner = -1）
		const float R0 = Teams[0].BaseMaxHp > 0.f ? Teams[0].BaseHp / Teams[0].BaseMaxHp : 0.f;
		const float R1 = Teams[1].BaseMaxHp > 0.f ? Teams[1].BaseHp / Teams[1].BaseMaxHp : 0.f;
		int32_t InWinner = -1;
		if (std::fabs(R0 - R1) > 1.0e-4f)
		{
			InWinner = R0 > R1 ? 0 : 1;
		}
		else if (Teams[0].Stats.Kills != Teams[1].Stats.Kills)
		{
			InWinner = Teams[0].Stats.Kills > Teams[1].Stats.Kills ? 0 : 1;
		}
		EndMatch(InWinner, EndReason::TimeLimit);
	}

	void Simulation::StepEconomy(float Dt)
	{
		const RulesDef& R = GameDataRef.Rules;
		if (!bSuddenDeathAnnounced && IsSuddenDeath())
		{
			bSuddenDeathAnnounced = true;
			Emit(EventType::SuddenDeath, 0);
		}
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			TeamState& S = Teams[T];
			S.Gold += static_cast<double>(IncomePerSecond(T) * Dt);
			S.Xp += static_cast<double>(R.PassiveXpPerSec * (1.f + S.Effects.Xp) * Dt);
			S.SkillCooldown = std::max(0.f, S.SkillCooldown - Dt);
			S.TurretBoostTime = std::max(0.f, S.TurretBoostTime - Dt);
		}
	}

	void Simulation::StepAgeUpgrades(float Dt)
	{
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			TeamState& S = Teams[T];
			if (!S.Upgrading)
			{
				continue;
			}
			S.UpgradeTimeLeft -= Dt;
			if (S.UpgradeTimeLeft > 0.f)
			{
				continue;
			}
			S.Upgrading = false;
			S.UpgradeTimeLeft = 0.f;
			const float OldMax = S.BaseMaxHp;
			S.Age += 1;
			S.BaseMaxHp = GameDataRef.Ages[static_cast<size_t>(S.Age)].BaseMaxHp * std::max(1.f + S.Effects.BaseHp, 0.2f);
			// 保持生命百分比不变
			S.BaseHp = OldMax > 0.f ? S.BaseHp / OldMax * S.BaseMaxHp : S.BaseMaxHp;
			Emit(EventType::AgeUpgradeDone, T, S.Age);
			EvolveChampion(T);
			GrantDoctrinePick(T);
		}
	}

	void Simulation::StepTraining(float Dt)
	{
		for (int32_t T = 0; T < TeamCount; ++T)
		{
			TeamState& S = Teams[T];
			if (S.Queue.empty())
			{
				continue;
			}
			QueueItem& Front = S.Queue.front();
			const float TrainTime = UnitTrainTime(T, Front.Def);
			Front.Progress = std::min(Front.Progress + Dt, TrainTime);
			if (Front.Progress >= TrainTime && TrySpawn(T, Front.Def))
			{
				S.Queue.erase(S.Queue.begin());
			}
		}
	}

	bool Simulation::TrySpawn(int32_t InTeam, int32_t Def)
	{
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(Def)];
		const RulesDef& R = GameDataRef.Rules;
		// 出生点在己方城门内侧，紧贴城门：敌军停在城门外侧，不会与新单位重叠
		const float SpawnX = BaseFrontX(InTeam) - static_cast<float>(Dir(InTeam)) * D.Radius;
		// 选择出生点最空的一行（中间行优先）；所有行都被占用时，训练完成的单位在队列中等待
		const int32_t Rows = std::max(R.LaneRows, 1);
		int32_t BestRow = -1;
		float BestClearance = -1.f;
		for (int32_t K = 0; K < Rows; ++K)
		{
			const int32_t Row = (Rows / 2 + ((K % 2 == 1) ? -(K + 1) / 2 : K / 2) + Rows) % Rows;
			float Clearance = 1.0e9f;
			bool bFree = true;
			for (const Unit& Ally : UnitList)
			{
				if (Ally.Team != InTeam || Ally.Row != Row || !IsAlive(Ally) || Ally.Champion)
				{
					continue;
				}
				const float Dist = std::fabs(Ally.X - SpawnX);
				const float Need = (D.Radius + GameDataRef.Units[static_cast<size_t>(Ally.Def)].Radius) * R.AllySpacingFactor;
				if (Dist < Need)
				{
					bFree = false;
					break;
				}
				Clearance = std::min(Clearance, Dist - Need);
			}
			if (bFree && Clearance > BestClearance)
			{
				BestClearance = Clearance;
				BestRow = Row;
			}
		}
		if (BestRow < 0)
		{
			return false;
		}
		const int32_t NewId = AddUnit(InTeam, Def, SpawnX, BestRow, false).Id;
		Teams[InTeam].Stats.UnitsTrained += 1;
		Emit(EventType::UnitSpawned, InTeam, NewId, Def, SpawnX);
		return true;
	}

	Unit& Simulation::AddUnit(int32_t InTeam, int32_t Def, float X, int32_t Row, bool bChampion)
	{
		const RulesDef& R = GameDataRef.Rules;
		Unit U;
		U.Id = NextUnitId++;
		U.Team = InTeam;
		U.Def = Def;
		U.Row = Row;
		U.X = X;
		U.State = UnitState::Walking;
		U.RetargetTimer = static_cast<float>(U.Id % 5) * R.RetargetInterval / 5.f;
		U.ChargeReady = true;
		U.Champion = bChampion;
		if (!bChampion)
		{
			const int32_t Role = static_cast<int32_t>(GameDataRef.Units[static_cast<size_t>(Def)].Role);
			U.Rank = std::min(std::max(Teams[InTeam].Effects.StartRank[Role], 0), 3);
		}
		RefreshUnitStats(U);
		U.Hp = U.MaxHp;
		UnitList.push_back(U);
		IdToIndex[U.Id] = static_cast<int32_t>(UnitList.size() - 1);
		return UnitList.back();
	}

	void Simulation::RefreshUnitStats(Unit& U)
	{
		const RulesDef& R = GameDataRef.Rules;
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
		const DoctrineEffects& E = Teams[U.Team].Effects;
		float HpMul = 1.f;
		float DmgMul = 1.f;
		float SpeedMul = 1.f;
		float RangeMul = 1.f;
		float AsMul = 1.f;
		if (U.Champion)
		{
			HpMul = std::max(1.f + E.ChampionHp, 0.2f);
			DmgMul = std::max(1.f + E.ChampionDamage, 0.2f);
		}
		else
		{
			const int32_t Role = static_cast<int32_t>(D.Role);
			HpMul = std::max(1.f + E.Hp[Role], 0.2f) * (1.f + R.VeteranHpBonus * static_cast<float>(U.Rank));
			DmgMul = std::max(1.f + E.Damage[Role], 0.2f) * (1.f + R.VeteranDamageBonus * static_cast<float>(U.Rank));
			SpeedMul = std::max(1.f + E.Speed[Role], 0.3f);
			RangeMul = std::max(1.f + E.Range[Role], 0.5f);
			AsMul = std::max(1.f + E.AttackSpeed[Role], 0.3f);
		}
		const float OldMax = U.MaxHp;
		U.MaxHp = D.MaxHp * HpMul;
		U.DamageMul = DmgMul;
		U.SpeedMul = SpeedMul;
		U.RangeMul = RangeMul;
		U.AttackSpeedMul = AsMul;
		if (OldMax > 0.f && IsAlive(U))
		{
			U.Hp = std::min(U.Hp / OldMax * U.MaxHp, U.MaxHp);
		}
	}

	void Simulation::RefreshTeamUnits(int32_t InTeam)
	{
		for (Unit& U : UnitList)
		{
			if (U.Team == InTeam && IsAlive(U))
			{
				RefreshUnitStats(U);
			}
		}
	}

	float Simulation::UnitDamageMultiplier(const Unit& U) const
	{
		float M = U.DamageMul;
		if (U.BuffTime > 0.f)
		{
			M *= 1.f + U.BuffDamage;
		}
		if (!U.Champion)
		{
			const Unit* Champ = ChampionUnit(U.Team);
			const ChampionDef* CD = CurrentChampion(U.Team);
			if (Champ != nullptr && CD != nullptr && std::fabs(Champ->X - U.X) <= CD->AuraRadius)
			{
				M *= 1.f + CD->AuraDamageBonus; // 统帅光环
			}
		}
		return M;
	}

	float Simulation::UnitAttackInterval(const Unit& U) const
	{
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
		const float Speed = U.AttackSpeedMul * (U.BuffTime > 0.f ? 1.f + U.BuffAttackSpeed : 1.f);
		return D.AttackInterval / std::max(Speed, 0.1f);
	}

	int32_t Simulation::VeteranRankFor(const Unit& U, float Value) const
	{
		const RulesDef& R = GameDataRef.Rules;
		const float Cost = static_cast<float>(std::max(GameDataRef.Units[static_cast<size_t>(U.Def)].Cost, 1));
		int32_t Rank = 0;
		Rank += Value >= R.VeteranRank1Ratio * Cost ? 1 : 0;
		Rank += Value >= R.VeteranRank2Ratio * Cost ? 1 : 0;
		Rank += Value >= R.VeteranRank3Ratio * Cost ? 1 : 0;
		return Rank;
	}

	void Simulation::CreditKill(int32_t AttackerUnitId, float Value)
	{
		if (AttackerUnitId < 0)
		{
			return;
		}
		Unit* A = FindUnitMutable(AttackerUnitId);
		if (A == nullptr || !IsAlive(*A) || A->Champion)
		{
			return; // 统帅有自己的成长方式，不参与老兵晋升
		}
		A->KillValue += Value * std::max(1.f + Teams[A->Team].Effects.VeteranGain, 0.f);
		const int32_t NewRank = std::max(A->Rank, VeteranRankFor(*A, A->KillValue));
		if (NewRank > A->Rank)
		{
			A->Rank = NewRank;
			RefreshUnitStats(*A);
			A->Hp = std::min(A->MaxHp, A->Hp + A->MaxHp * GameDataRef.Rules.VeteranPromotionHeal);
			Teams[A->Team].Stats.Promotions += 1;
			Emit(EventType::UnitPromoted, A->Team, A->Id, NewRank, A->X);
		}
	}

	void Simulation::StepUnits(float Dt)
	{
		// 每步交替两队的行动顺序，避免固定先手；近战伤害在双方都行动后统一结算
		const int32_t First = static_cast<int32_t>(TickCount % 2u);
		StepTeamUnits(First, Dt);
		StepTeamUnits(1 - First, Dt);
		ApplyPendingHits();
	}

	void Simulation::ApplyPendingHits()
	{
		for (const PendingHit& Hit : PendingHits)
		{
			if (Hit.TargetId == TargetBase)
			{
				DamageBase(Enemy(Hit.AttackerTeam), Hit.Damage, Hit.Type, Hit.StructureMult, Hit.AttackerTeam);
			}
			else if (Unit* Target = FindUnitMutable(Hit.TargetId))
			{
				DamageUnit(*Target, Hit.Damage, Hit.Type, Hit.AttackerTeam, false, Hit.AttackerId);
			}
			if (Hit.SplashRadius > 0.f)
			{
				SplashDamage(Hit.AttackerTeam, Hit.SplashX, Hit.SplashRadius, Hit.Damage, Hit.Type, Hit.TargetId, false, Hit.AttackerId);
			}
		}
		PendingHits.clear();
	}

	void Simulation::StepTeamUnits(int32_t T, float Dt)
	{
		const RulesDef& R = GameDataRef.Rules;
		if (CurrentPhase == MatchPhase::Running)
		{
			const int32_t E = Enemy(T);
			const float DirF = static_cast<float>(Dir(T));
			const std::vector<int32_t>& O = Order[T];
			// 每行中“前方最近的友军”：按从前到后的顺序处理，记录各行最近处理过的单位
			int32_t LastInRow[MaxLaneRows];
			for (int32_t& Idx : LastInRow)
			{
				Idx = -1;
			}
			// 每行中“身后最近的友军”（驻守后撤时保持间距）：从后往前扫描
			BehindScratch.assign(O.size(), -1);
			int32_t LastBehind[MaxLaneRows];
			for (int32_t& Idx : LastBehind)
			{
				Idx = -1;
			}
			for (size_t K = O.size(); K-- > 0;)
			{
				const Unit& BU = UnitList[static_cast<size_t>(O[K])];
				if (IsAlive(BU) && !BU.Champion)
				{
					BehindScratch[K] = LastBehind[BU.Row];
					LastBehind[BU.Row] = O[K];
				}
			}
			const bool bHold = Teams[T].Stance == ArmyStance::Hold;
			const float HoldP = DirF * BaseFrontX(T) + R.HoldLineDistance; // 驻守线（以前进方向的进度表示）
			for (size_t K = 0; K < O.size(); ++K)
			{
				Unit& U = UnitList[static_cast<size_t>(O[K])];
				if (!IsAlive(U))
				{
					continue; // 本步内已被击杀：不再行动
				}
				// 统帅不受友军阻挡，也不阻挡友军：不参与“同一行前方友军”的记录
				const int32_t AllyAheadIdx = U.Champion ? -1 : LastInRow[U.Row];
				if (!U.Champion)
				{
					LastInRow[U.Row] = O[K];
				}
				const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
				U.Cooldown = std::max(0.f, U.Cooldown - Dt);
				U.RetargetTimer -= Dt;

				// 统帅收到“坚守”指令且目标位置在身后：脱离战斗直接后撤（玩家指令优先）
				if (U.Champion && Teams[T].Order == ChampionOrder::Hold && ChampionTargetProgress(T, U) < DirF * U.X - 0.5f)
				{
					if (U.Windup > 0.f)
					{
						RecordAttackEnd(U, AttackOutcome::Cancelled, SimTime);
						TraceArtTiming("cancel", U, D, SimTime, "champion_retreat");
					}
					U.TargetId = TargetNone;
					U.Windup = 0.f;
					StepChampionMovement(U, T, Dt);
					continue;
				}

				// 1) 索敌：前摇期间锁定目标；目标失效则取消前摇
				const bool bLocked = U.Windup > 0.f && IsTargetValid(U, U.TargetId);
				if (!bLocked)
				{
					if (U.Windup > 0.f)
					{
						RecordAttackEnd(U, AttackOutcome::Cancelled, SimTime);
						TraceArtTiming("cancel", U, D, SimTime, "invalid_target");
					}
					U.Windup = 0.f;
					if (!IsTargetValid(U, U.TargetId) || U.RetargetTimer <= 0.f)
					{
						U.TargetId = SelectTarget(U);
						U.RetargetTimer = R.RetargetInterval;
					}
				}

				// 2) 有目标：停下攻击
				if (U.TargetId != TargetNone)
				{
					U.State = UnitState::Attacking;
					U.WalkTime = 0.f;
					if (U.Windup > 0.f)
					{
						U.Windup -= Dt;
						if (U.Windup <= 0.f)
						{
							U.Windup = 0.f;
							ResolveUnitAttack(U);
						}
					}
					else if (U.Cooldown <= 0.f)
					{
						U.Cooldown = UnitAttackInterval(U);
						U.AttackSeq = static_cast<uint8_t>(U.AttackSeq + 1);
						U.AttackStartSimTime = SimTime;
						U.AttackResult = AttackOutcome::Windup;
						U.AttackEndSimTime = -1.f;
						Emit(EventType::UnitAttackStart, T, U.Id, U.TargetId, U.X);
						TraceArtTiming("start", U, D, SimTime, "windup_started");
						if (D.AttackWindup <= 0.f)
						{
							ResolveUnitAttack(U);
						}
						else
						{
							U.Windup = D.AttackWindup;
						}
					}
					continue;
				}

				// 3) 无目标：统帅按指令移动；普通单位驻守且越线则后撤，否则前进，受敌方基地、敌方最前单位、前方友军（及驻守线）约束
				if (U.Champion)
				{
					StepChampionMovement(U, T, Dt);
					continue;
				}
				const float Speed = D.MoveSpeed * U.SpeedMul;
				const float P = DirF * U.X;
				if (bHold && P > HoldP + 0.5f)
				{
					float NewP = std::max(P - Speed * R.RetreatSpeedFactor * Dt, HoldP);
					const int32_t BehindIdx = BehindScratch[K];
					if (BehindIdx >= 0)
					{
						const Unit& Back = UnitList[static_cast<size_t>(BehindIdx)];
						NewP = std::max(NewP, DirF * Back.X + (D.Radius + GameDataRef.Units[static_cast<size_t>(Back.Def)].Radius) * R.AllySpacingFactor);
					}
					NewP = std::min(NewP, P); // 后撤约束只会阻止后退，不会把单位往前推
					U.State = NewP < P - 0.001f ? UnitState::Walking : UnitState::Blocked;
					U.WalkTime = 0.f;
					U.X = DirF * NewP;
					continue;
				}
				float Limit = DirF * BaseFrontX(E) - D.Radius;
				if (bHold)
				{
					Limit = std::min(Limit, HoldP);
				}
				for (const int32_t EIdx : Order[E])
				{
					const Unit& Foe = UnitList[static_cast<size_t>(EIdx)];
					if (IsAlive(Foe))
					{
						Limit = std::min(Limit, DirF * Foe.X - (D.Radius + GameDataRef.Units[Foe.Def].Radius));
						break;
					}
				}
				if (AllyAheadIdx >= 0)
				{
					const Unit& Ally = UnitList[static_cast<size_t>(AllyAheadIdx)];
					Limit = std::min(Limit, DirF * Ally.X - (D.Radius + GameDataRef.Units[static_cast<size_t>(Ally.Def)].Radius) * R.AllySpacingFactor);
				}
				float NewP = std::min(P + Speed * Dt, Limit);
				NewP = std::max(NewP, P); // 约束只阻止前进，不会把单位往回推
				const bool bMoved = NewP > P + 0.001f;
				U.X = DirF * NewP;
				if (bMoved)
				{
					U.State = UnitState::Walking;
					U.WalkTime += Dt;
					if (U.WalkTime >= R.ChargeRechargeTime)
					{
						U.ChargeReady = true;
					}
				}
				else
				{
					U.State = UnitState::Blocked;
					U.WalkTime = 0.f;
				}
			}
		}
	}

	void Simulation::ResolveUnitAttack(Unit& U)
	{
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
		if (!IsTargetValid(U, U.TargetId))
		{
			RecordAttackEnd(U, AttackOutcome::Cancelled, SimTime);
			TraceArtTiming("cancel", U, D, SimTime, "invalid_at_resolve");
			return; // 命中瞬间目标已失效：本次攻击落空
		}
		RecordAttackEnd(U, AttackOutcome::Released, SimTime);
		TraceArtTiming("release", U, D, SimTime, D.ProjectileSpeed > 0.f ? "projectile" : "queued_melee");
		float Damage = D.Damage * UnitDamageMultiplier(U);
		if (U.ChargeReady && D.ChargeMultiplier > 1.f)
		{
			Damage *= D.ChargeMultiplier;
		}
		U.ChargeReady = false;

		const int32_t E = Enemy(U.Team);
		const float TargetX = U.TargetId == TargetBase ? BaseFrontX(E) : FindUnit(U.TargetId)->X;
		if (D.ProjectileSpeed > 0.f)
		{
			const float MuzzleX = U.X + static_cast<float>(Dir(U.Team)) * D.Radius;
			LaunchProjectile(U.Team, U.Id, -1, U.TargetId, MuzzleX, TargetX, D.ProjectileSpeed, Damage,
				D.SplashRadius, D.StructureMultiplier, D.DmgType);
			return;
		}
		PendingHit Hit;
		Hit.AttackerTeam = U.Team;
		Hit.TargetId = U.TargetId;
		Hit.Damage = Damage;
		Hit.Type = D.DmgType;
		Hit.StructureMult = D.StructureMultiplier;
		Hit.SplashX = TargetX;
		Hit.SplashRadius = D.SplashRadius;
		Hit.AttackerId = U.Id;
		PendingHits.push_back(Hit);
	}

	void Simulation::LaunchProjectile(int32_t InTeam, int32_t SourceUnit, int32_t SourceSlot, int32_t TargetId,
		float FromX, float TargetX, float Speed, float Damage, float Splash, float StructureMult, DamageType Type)
	{
		Projectile P;
		P.Id = NextProjectileId++;
		P.Team = InTeam;
		P.SourceUnit = SourceUnit;
		P.SourceTurretSlot = SourceSlot;
		P.TargetId = TargetId;
		P.X = FromX;
		P.TargetX = TargetX;
		P.Speed = Speed;
		P.Damage = Damage;
		P.SplashRadius = Splash;
		P.StructureMultiplier = StructureMult;
		P.DmgType = Type;
		ProjectileList.push_back(P);
		Emit(EventType::ProjectileFired, InTeam, P.Id, SourceUnit, FromX, TargetX);
	}

	void Simulation::StepProjectiles(float Dt)
	{
		if (CurrentPhase != MatchPhase::Running)
		{
			return;
		}
		std::vector<int32_t> Finished;
		for (size_t I = 0; I < ProjectileList.size(); ++I)
		{
			Projectile& P = ProjectileList[I];
			const int32_t E = Enemy(P.Team);
			bool bTargetAlive = false;
			if (P.TargetId == TargetBase)
			{
				P.TargetX = BaseFrontX(E);
				bTargetAlive = true;
			}
			else if (const Unit* T = FindUnit(P.TargetId))
			{
				if (IsAlive(*T))
				{
					P.TargetX = T->X; // 追踪目标
					bTargetAlive = true;
				}
			}
			const float Delta = P.TargetX - P.X;
			const float Move = P.Speed * Dt;
			if (std::fabs(Delta) > Move)
			{
				P.X += Delta > 0.f ? Move : -Move;
				continue;
			}
			// 命中
			P.X = P.TargetX;
			const Projectile Hit = P; // 拷贝：后续伤害结算可能触发结束
			const bool bFromTurret = Hit.SourceTurretSlot >= 0;
			if (bTargetAlive)
			{
				if (Hit.TargetId == TargetBase)
				{
					DamageBase(E, Hit.Damage, Hit.DmgType, Hit.StructureMultiplier, Hit.Team);
				}
				else if (Unit* Target = FindUnitMutable(Hit.TargetId))
				{
					DamageUnit(*Target, Hit.Damage, Hit.DmgType, Hit.Team, bFromTurret, Hit.SourceUnit);
				}
			}
			if (Hit.SplashRadius > 0.f)
			{
				SplashDamage(Hit.Team, Hit.X, Hit.SplashRadius, Hit.Damage, Hit.DmgType, bTargetAlive ? Hit.TargetId : TargetNone, bFromTurret,
					Hit.SourceUnit);
			}
			Emit(EventType::ProjectileImpact, Hit.Team, Hit.Id, bTargetAlive ? 1 : 0, Hit.X);
			Finished.push_back(Hit.Id);
		}
		if (!Finished.empty())
		{
			ProjectileList.erase(std::remove_if(ProjectileList.begin(), ProjectileList.end(), [&Finished](const Projectile& P)
			{
				return std::find(Finished.begin(), Finished.end(), P.Id) != Finished.end();
			}), ProjectileList.end());
		}
	}

	void Simulation::StepTurrets(float Dt)
	{
		const RulesDef& R = GameDataRef.Rules;
		for (int32_t T = 0; T < TeamCount && CurrentPhase == MatchPhase::Running; ++T)
		{
			const int32_t E = Enemy(T);
			const float TX = TurretX(T);
			TeamState& S = Teams[T];
			for (size_t SlotIdx = 0; SlotIdx < S.Turrets.size(); ++SlotIdx)
			{
				TurretSlot& Slot = S.Turrets[SlotIdx];
				if (Slot.Def == InvalidIndex)
				{
					continue;
				}
				const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(Slot.Def)];
				const float Range = TurretRangeFor(T, Slot.Def, Slot.Level) + SimRangeTolerance;
				Slot.Cooldown = std::max(0.f, Slot.Cooldown - Dt);
				Slot.RetargetTimer -= Dt;

				const Unit* Current = Slot.TargetId >= 0 ? FindUnit(Slot.TargetId) : nullptr;
				const bool bValid = Current != nullptr && IsAlive(*Current) && Current->Team == E
					&& std::fabs(Current->X - TX) - GameDataRef.Units[Current->Def].Radius <= Range;
				if (!bValid || Slot.RetargetTimer <= 0.f)
				{
					Slot.TargetId = TargetNone;
					Slot.RetargetTimer = R.TurretRetargetInterval;
					// 敌方最前单位就是离己方基地最近的单位；它不在射程内则其他单位也不在
					for (const int32_t Idx : Order[E])
					{
						const Unit& Foe = UnitList[static_cast<size_t>(Idx)];
						if (!IsAlive(Foe))
						{
							continue;
						}
						if (std::fabs(Foe.X - TX) - GameDataRef.Units[Foe.Def].Radius <= Range)
						{
							Slot.TargetId = Foe.Id;
						}
						break;
					}
				}
				if (Slot.TargetId < 0 || Slot.Cooldown > 0.f)
				{
					continue;
				}
				Unit* Target = FindUnitMutable(Slot.TargetId);
				if (Target == nullptr)
				{
					continue;
				}
				Slot.Cooldown = D.AttackInterval;
				Slot.FireSeq = static_cast<uint8_t>(Slot.FireSeq + 1);
				const float Boost = S.TurretBoostTime > 0.f ? 1.f + R.LastStandTurretBonus : 1.f;
				const float Damage = TurretDamageFor(T, Slot.Def, Slot.Level) * TurretDamageMultiplier() * Boost;
				Emit(EventType::TurretFired, T, static_cast<int32_t>(SlotIdx), Slot.TargetId, TX);
				if (D.ProjectileSpeed > 0.f)
				{
					LaunchProjectile(T, -1, static_cast<int32_t>(SlotIdx), Slot.TargetId, TX, Target->X, D.ProjectileSpeed,
						Damage, D.SplashRadius, 1.f, D.DmgType);
				}
				else
				{
					const float HitX = Target->X;
					const int32_t HitId = Target->Id;
					DamageUnit(*Target, Damage, D.DmgType, T, true);
					if (D.SplashRadius > 0.f)
					{
						SplashDamage(T, HitX, D.SplashRadius, Damage, D.DmgType, HitId, true);
					}
				}
			}
		}
	}

	void Simulation::StepSkills(float Dt)
	{
		if (CurrentPhase != MatchPhase::Running)
		{
			return;
		}
		for (SkillCast& Cast : CastList)
		{
			Cast.TimeLeft -= Dt;
			if (Cast.TimeLeft > 0.f)
			{
				continue;
			}
			const SkillDef& S = GameDataRef.Skills[static_cast<size_t>(Cast.Skill)];
			const float SkillDamage = S.Damage * std::max(1.f + Teams[Cast.Team].Effects.SkillDamage, 0.f);
			int32_t Hits = 0;
			for (Unit& U : UnitList)
			{
				if (U.Team != Cast.Team && IsAlive(U)
					&& std::fabs(U.X - Cast.X) <= S.Radius + GameDataRef.Units[U.Def].Radius)
				{
					DamageUnit(U, SkillDamage, S.DmgType, Cast.Team);
					++Hits;
				}
			}
			Emit(EventType::SkillImpact, Cast.Team, Cast.Id, Hits, Cast.X);
		}
		CastList.erase(std::remove_if(CastList.begin(), CastList.end(), [](const SkillCast& C)
		{
			return C.TimeLeft <= 0.f;
		}), CastList.end());
	}

	void Simulation::StepDeaths(float Dt)
	{
		bool bRemoved = false;
		for (Unit& U : UnitList)
		{
			if (U.State == UnitState::Dying)
			{
				U.DeathTimer -= Dt;
				bRemoved = bRemoved || U.DeathTimer <= 0.f;
			}
		}
		if (bRemoved)
		{
			UnitList.erase(std::remove_if(UnitList.begin(), UnitList.end(), [](const Unit& U)
			{
				return U.State == UnitState::Dying && U.DeathTimer <= 0.f;
			}), UnitList.end());
			RebuildIndex();
		}
	}

	void Simulation::DamageUnit(Unit& Target, float RawDamage, DamageType Type, int32_t AttackerTeam, bool bFromTurret, int32_t AttackerUnitId)
	{
		if (!IsAlive(Target) || Target.Team == AttackerTeam)
		{
			return; // 死亡单位不再受击，也不会被重复结算
		}
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(Target.Def)];
		const float Damage = RawDamage * GameDataRef.DamageMultiplier(Type, D.Armor);
		Target.Hp -= Damage;
		Target.HitSeq = static_cast<uint8_t>(Target.HitSeq + 1);
		Target.LastAttackerTeam = AttackerTeam;
		Emit(EventType::UnitHit, Target.Team, Target.Id, AttackerTeam, Target.X, Damage);
		if (Target.Hp <= 0.f)
		{
			KillUnit(Target, AttackerTeam, bFromTurret, AttackerUnitId);
		}
	}

	void Simulation::DamageBase(int32_t BaseTeam, float RawDamage, DamageType Type, float StructureMult, int32_t AttackerTeam)
	{
		if (CurrentPhase != MatchPhase::Running)
		{
			return;
		}
		TeamState& B = Teams[BaseTeam];
		const float Doctrine = std::max(1.f + Teams[AttackerTeam].Effects.StructureDamage, 0.f);
		const float Damage = RawDamage * GameDataRef.DamageMultiplier(Type, ArmorType::Building) * StructureMult * Doctrine * BaseDamageMultiplier();
		B.BaseHp -= Damage;
		B.BaseHitSeq = static_cast<uint8_t>(B.BaseHitSeq + 1);
		Teams[AttackerTeam].Stats.DamageToBase += Damage;
		Emit(EventType::BaseHit, BaseTeam, 0, AttackerTeam, BaseFrontX(BaseTeam), Damage);
		if (B.BaseHp <= 0.f)
		{
			B.BaseHp = 0.f;
			EndMatch(AttackerTeam, EndReason::BaseDestroyed);
		}
	}

	void Simulation::SplashDamage(int32_t AttackerTeam, float CenterX, float Radius, float RawDamage, DamageType Type, int32_t ExcludeId,
		bool bFromTurret, int32_t AttackerUnitId)
	{
		const float Secondary = RawDamage * GameDataRef.Rules.SplashSecondaryRatio;
		for (Unit& U : UnitList)
		{
			if (U.Team != AttackerTeam && U.Id != ExcludeId && IsAlive(U)
				&& std::fabs(U.X - CenterX) <= Radius + GameDataRef.Units[static_cast<size_t>(U.Def)].Radius)
			{
				DamageUnit(U, Secondary, Type, AttackerTeam, bFromTurret, AttackerUnitId);
			}
		}
	}

	void Simulation::KillUnit(Unit& U, int32_t KillerTeam, bool bByTurret, int32_t AttackerUnitId)
	{
		const RulesDef& R = GameDataRef.Rules;
		const UnitDef& D = GameDataRef.Units[static_cast<size_t>(U.Def)];
		if (U.Windup > 0.f)
		{
			RecordAttackEnd(U, AttackOutcome::Cancelled, SimTime);
			TraceArtTiming("cancel", U, D, SimTime, "attacker_died");
		}
		U.Hp = 0.f;
		U.State = UnitState::Dying;
		U.DeathTimer = R.DeathDuration;
		U.TargetId = TargetNone;
		U.Windup = 0.f;
		U.BuffTime = 0.f;

		TeamState& Killer = Teams[KillerTeam];
		TeamState& Loser = Teams[U.Team];
		const float KillerXp = static_cast<float>(D.XpReward) * std::max(1.f + Killer.Effects.Xp, 0.f);
		const float LoserXp = static_cast<float>(D.XpReward) * R.LoserXpRatio * std::max(1.f + Loser.Effects.Xp, 0.f);
		int32_t Gold = 0;
		if (U.Champion)
		{
			// 统帅阵亡：击杀方获得赏金，阵亡方开始复活倒计时
			const ChampionDef* CD = CurrentChampion(U.Team);
			const float Bounty = CD != nullptr ? static_cast<float>(CD->Bounty) : static_cast<float>(D.Cost) * 0.3f;
			Gold = static_cast<int32_t>(Bounty * std::max(1.f + Killer.Effects.KillGold, 0.f) + 0.5f);
			Killer.Stats.ChampionKills += 1;
			Loser.ChampionId = -1;
			Loser.ChampionRespawn = ChampionRespawnTime(U.Team);
		}
		else
		{
			const float GoldRatio = R.KillGoldRatio * (bByTurret ? R.TurretKillGoldFactor : 1.f);
			Gold = static_cast<int32_t>(static_cast<float>(D.Cost) * GoldRatio * std::max(1.f + Killer.Effects.KillGold, 0.f) + 0.5f);
			Loser.Stats.UnitsLost += 1;
		}
		Killer.Gold += Gold;
		Killer.Xp += KillerXp;
		Killer.Stats.Kills += 1;
		Killer.Stats.GoldEarned += Gold;
		Loser.Xp += static_cast<double>(LoserXp);
		Emit(EventType::UnitDied, U.Team, U.Id, KillerTeam, U.X);
		Emit(EventType::KillReward, KillerTeam, Gold, static_cast<int32_t>(KillerXp), U.X);
		if (U.Champion)
		{
			Emit(EventType::ChampionDied, U.Team, U.Id, KillerTeam, U.X, static_cast<float>(Gold));
		}
		CreditKill(AttackerUnitId, U.Champion ? static_cast<float>(Gold) * 2.f : static_cast<float>(D.Cost));
	}

	void Simulation::EndMatch(int32_t InWinner, EndReason InReason)
	{
		if (CurrentPhase != MatchPhase::Running)
		{
			return; // 结算只发生一次
		}
		for (Unit& Pending : UnitList)
		{
			if (Pending.Windup > 0.f)
			{
				RecordAttackEnd(Pending, AttackOutcome::Cancelled, SimTime);
				TraceArtTiming("interrupted", Pending, GameDataRef.Units[static_cast<size_t>(Pending.Def)], SimTime, "match_ended");
			}
		}
		CurrentPhase = MatchPhase::Ended;
		WinnerTeam = InWinner;
		Reason = InReason;
		Emit(EventType::MatchEnded, InWinner, static_cast<int32_t>(InReason));
	}

	void Simulation::Emit(EventType Type, int32_t InTeam, int32_t A, int32_t B, float X, float Value)
	{
		SimEvent Ev;
		Ev.Type = Type;
		Ev.Team = InTeam;
		Ev.A = A;
		Ev.B = B;
		Ev.X = X;
		Ev.Value = Value;
		EventList.push_back(Ev);
	}

	void Simulation::Pay(int32_t InTeam, int32_t Gold)
	{
		Teams[InTeam].Gold -= Gold;
		Teams[InTeam].Stats.GoldSpent += Gold;
	}
}
