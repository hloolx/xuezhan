#include "SimAI.h"

#include <algorithm>
#include <cmath>

namespace cw
{
	AiPlayer::AiPlayer(int32_t InTeam, const AiConfig& InConfig)
		: Team(InTeam)
		, Config(InConfig)
	{
		RngState = InConfig.Seed != 0 ? InConfig.Seed : 0x9E3779B9u;
		switch (InConfig.Difficulty)
		{
		case AiDifficulty::Easy:
			ThinkInterval = 2.0f;
			ReactionNoise = 0.45f;
			break;
		case AiDifficulty::Hard:
			ThinkInterval = 0.4f;
			ReactionNoise = 0.f;
			break;
		default:
			ThinkInterval = 0.8f;
			ReactionNoise = 0.1f;
			break;
		}
		ThinkTimer = ThinkInterval * 0.5f;
	}

	float AiPlayer::Random01()
	{
		// xorshift32：固定种子下结果可复现
		uint32_t X = RngState;
		X ^= X << 13;
		X ^= X >> 17;
		X ^= X << 5;
		RngState = X;
		return static_cast<float>(X & 0xFFFFFFu) / static_cast<float>(0x1000000u);
	}

	bool AiPlayer::Issue(Simulation& Sim, const Command& Cmd)
	{
		return Sim.Apply(Team, Cmd) == CommandResult::Ok;
	}

	void AiPlayer::Tick(Simulation& Sim, float Dt)
	{
		if (Sim.Phase() != MatchPhase::Running)
		{
			return;
		}
		ThinkTimer -= Dt;
		if (ThinkTimer > 0.f)
		{
			return;
		}
		ThinkTimer += ThinkInterval;
		Think(Sim);
	}

	AiPlayer::Assessment AiPlayer::Assess(const Simulation& Sim) const
	{
		Assessment A;
		const GameData& Data = Sim.Data();
		const int32_t E = Simulation::Enemy(Team);
		const float MyGate = Sim.BaseFrontX(Team);
		const float EnemyGate = Sim.BaseFrontX(E);
		for (const Unit& U : Sim.Units())
		{
			if (U.State == UnitState::Dying)
			{
				continue;
			}
			const UnitDef& D = Data.Units[static_cast<size_t>(U.Def)];
			const float Value = static_cast<float>(D.Cost) * (U.Hp / std::max(U.MaxHp, 1.f));
			const int32_t Role = static_cast<int32_t>(D.Role);
			if (U.Team == Team)
			{
				A.MyArmyValue += Value;
				if (U.Champion)
				{
					continue; // 统帅计入兵力，但不参与兵种构成判断
				}
				A.MyRoleCount[Role] += 1;
				const float Dist = std::fabs(EnemyGate - U.X);
				if (Dist < A.MyFrontDistToEnemyBase)
				{
					A.MyFrontDistToEnemyBase = Dist;
					A.bMyFrontIsMelee = D.Role != UnitRole::Ranged;
				}
			}
			else
			{
				A.EnemyArmyValue += Value;
				A.EnemyFrontDistToMyBase = std::min(A.EnemyFrontDistToMyBase, std::fabs(U.X - MyGate));
				if (U.Champion)
				{
					continue;
				}
				A.EnemyRoleCount[Role] += 1;
				A.EnemyHeavyArmor += D.Armor == ArmorType::Heavy ? 1 : 0;
				A.EnemyLightArmor += D.Armor == ArmorType::Light ? 1 : 0;
			}
		}
		// 炮塔计入防守力量
		float TurretValue = 0.f;
		for (const TurretSlot& Slot : Sim.Team(Team).Turrets)
		{
			TurretValue += static_cast<float>(Slot.Invested) * 0.8f;
		}
		const float Lane = std::max(Sim.BaseFrontX(1) - Sim.BaseFrontX(0), 1.f);
		const float Proximity = 1.f - std::min(std::max(A.EnemyFrontDistToMyBase / Lane, 0.f), 1.f);
		const float Ratio = A.EnemyArmyValue / std::max(A.MyArmyValue + TurretValue, 30.f);
		const TeamState& S = Sim.Team(Team);
		const float BaseDamage = S.BaseMaxHp > 0.f ? 1.f - S.BaseHp / S.BaseMaxHp : 0.f;
		A.Pressure = Proximity * std::min(Ratio, 3.f) * 0.6f + BaseDamage * 0.3f;
		return A;
	}

	void AiPlayer::Think(Simulation& Sim)
	{
		const Assessment A = Assess(Sim);
		const bool bDefend = A.Pressure > 0.6f || (A.EnemyFrontDistToMyBase < 900.f && A.EnemyArmyValue > A.MyArmyValue);

		TryChooseDoctrine(Sim);
		ControlChampion(Sim, A);
		TryLastStand(Sim, A);
		TryCastSkill(Sim, A);
		TryUpgradeAge(Sim, A);

		int32_t GoalCost = 0;
		const SaveGoal Goal = ChooseGoal(Sim, A, GoalCost);
		TryBuildTurret(Sim, A, Goal, GoalCost);
		UpdateStance(Sim, A, Goal);

		// 防守时不为目标攒钱：先保住基地
		const int32_t Reserve = (Goal == SaveGoal::None || bDefend) ? 0 : GoalCost;
		TryImproveTurrets(Sim, A, Reserve);
		TryTrain(Sim, A, Reserve);

		if (bDefend)
		{
			CurrentIntent = AiIntent::Defend;
		}
		else if (Goal == SaveGoal::Age)
		{
			CurrentIntent = AiIntent::SaveForAge;
		}
		else if (A.MyArmyValue > A.EnemyArmyValue * 1.5f && A.MyArmyValue > 150.f)
		{
			CurrentIntent = AiIntent::Push;
		}
		else
		{
			CurrentIntent = AiIntent::Build;
		}
	}

	bool AiPlayer::TryCastSkill(Simulation& Sim, const Assessment& A)
	{
		const GameData& Data = Sim.Data();
		const TeamState& S = Sim.Team(Team);
		const int32_t SkillIndex = Data.SkillForAge(S.Age);
		if (SkillIndex == InvalidIndex)
		{
			return false;
		}
		const SkillDef& K = Data.Skills[static_cast<size_t>(SkillIndex)];
		if (S.SkillCooldown > 0.f || S.Gold < K.Cost)
		{
			return false;
		}
		if (Config.Difficulty == AiDifficulty::Easy && Random01() < 0.5f)
		{
			return false; // 简单难度经常错过技能时机
		}
		float Min = 0.f;
		float Max = 0.f;
		Sim.SkillTargetRange(Team, Min, Max);
		const int32_t E = Simulation::Enemy(Team);

		float BestValue = 0.f;
		float BestX = 0.f;
		for (const Unit& Center : Sim.Units())
		{
			if (Center.Team != E || Center.State == UnitState::Dying)
			{
				continue;
			}
			// 预判：行军中的单位在预警期间会继续前进
			const UnitDef& CD = Data.Units[static_cast<size_t>(Center.Def)];
			float X = Center.X;
			if (Center.State == UnitState::Walking)
			{
				X += static_cast<float>(Simulation::Dir(E)) * CD.MoveSpeed * K.Delay * 0.6f;
			}
			X = std::min(std::max(X, Min), Max);
			float Value = 0.f;
			for (const Unit& U : Sim.Units())
			{
				if (U.Team != E || U.State == UnitState::Dying)
				{
					continue;
				}
				const UnitDef& D = Data.Units[static_cast<size_t>(U.Def)];
				if (std::fabs(U.X - X) <= K.Radius + D.Radius)
				{
					const float Dealt = std::min(U.Hp, K.Damage * Data.DamageMultiplier(K.DmgType, D.Armor));
					Value += static_cast<float>(D.Cost) * Dealt / std::max(U.MaxHp, 1.f);
				}
			}
			if (Value > BestValue)
			{
				BestValue = Value;
				BestX = X;
			}
		}
		const bool bDanger = A.EnemyFrontDistToMyBase < 1000.f;
		const float Threshold = std::max(static_cast<float>(K.Cost) * (bDanger ? 1.2f : 2.0f), 45.f);
		if (BestValue < Threshold)
		{
			return false;
		}
		Command C;
		C.Type = CommandType::CastSkill;
		C.X = BestX;
		return Issue(Sim, C);
	}

	int32_t AiPlayer::BuiltTurrets(const Simulation& Sim) const
	{
		int32_t Count = 0;
		for (const TurretSlot& Slot : Sim.Team(Team).Turrets)
		{
			Count += Slot.Def != InvalidIndex ? 1 : 0;
		}
		return Count;
	}

	int32_t AiPlayer::DesiredTurrets(const Simulation& Sim, const Assessment& A) const
	{
		const TeamState& S = Sim.Team(Team);
		float StartTime = 120.f;
		int32_t Bonus = 0;
		if (Config.Difficulty == AiDifficulty::Easy)
		{
			StartTime = 200.f;
			Bonus = -1;
		}
		int32_t Desired = Sim.Time() >= StartTime ? 1 : 0;
		Desired += S.Age;
		Desired += A.Pressure > 0.5f ? 1 : 0;
		Desired += Bonus;
		return std::min(std::max(Desired, 0), static_cast<int32_t>(S.Turrets.size()));
	}

	AiPlayer::SaveGoal AiPlayer::ChooseGoal(const Simulation& Sim, const Assessment& A, int32_t& OutCost) const
	{
		const GameData& Data = Sim.Data();
		const TeamState& S = Sim.Team(Team);
		OutCost = 0;

		// 1) 时代：经验接近门槛时开始攒钱
		const int32_t Next = S.Age + 1;
		if (!S.Upgrading && Next < static_cast<int32_t>(Data.Ages.size()) && Data.Ages[static_cast<size_t>(Next)].Implemented)
		{
			const double XpRatio = Config.Difficulty == AiDifficulty::Easy ? 1.0 : 0.9;
			const AgeDef& NextAge = Data.Ages[static_cast<size_t>(Next)];
			if (S.Xp >= static_cast<double>(NextAge.XpToEnter) * XpRatio)
			{
				OutCost = NextAge.GoldToEnter;
				return SaveGoal::Age;
			}
		}

		// 2) 金矿：前期安全时逐级投资（简单难度不投资）
		if (S.EconomyLevel < DesiredEconomyLevel(Sim) && A.Pressure < 0.3f)
		{
			const int32_t Cost = Sim.EconomyUpgradeCost(Team);
			if (Cost > 0)
			{
				OutCost = Cost;
				return SaveGoal::Economy;
			}
		}

		// 3) 炮塔：数量随时间、时代和压力增长
		if (BuiltTurrets(Sim) < DesiredTurrets(Sim, A))
		{
			for (const TurretSlot& Slot : S.Turrets)
			{
				if (Slot.Unlocked && Slot.Def == InvalidIndex)
				{
					const int32_t Def = ChooseTurretDef(Sim, A);
					if (Def != InvalidIndex)
					{
						OutCost = Data.Turrets[static_cast<size_t>(Def)].Cost;
						return SaveGoal::Turret;
					}
				}
			}
			const int32_t SlotCost = Sim.NextTurretSlotCost(Team);
			if (SlotCost > 0)
			{
				OutCost = SlotCost;
				return SaveGoal::TurretSlot;
			}
		}
		return SaveGoal::None;
	}

	int32_t AiPlayer::DesiredEconomyLevel(const Simulation& Sim) const
	{
		if (Config.Difficulty == AiDifficulty::Easy)
		{
			return 0;
		}
		const bool bHard = Config.Difficulty == AiDifficulty::Hard;
		const float T = Sim.Time();
		int32_t Level = 0;
		Level += T >= (bHard ? 25.f : 60.f) ? 1 : 0;
		Level += T >= (bHard ? 150.f : 240.f) ? 1 : 0;
		Level += T >= (bHard ? 300.f : 420.f) ? 1 : 0;
		return std::min(Level, Sim.Data().Rules.EconomyMaxLevel);
	}

	void AiPlayer::UpdateStance(Simulation& Sim, const Assessment& A, SaveGoal Goal)
	{
		if (Config.Difficulty == AiDifficulty::Easy || Sim.Time() - LastStanceChange < 6.f)
		{
			return; // 简单难度始终推进；姿态切换至少间隔 6 秒，避免反复横跳
		}
		const ArmyStance Current = Sim.Team(Team).Stance;
		const float Ratio = A.MyArmyValue / std::max(A.EnemyArmyValue, 1.f);
		// 带滞后的阈值：兵力低于对方 70% 时驻守（在己方炮塔掩护下集结），恢复到 95% 再推进
		ArmyStance Desired = Current;
		if (Current == ArmyStance::Advance)
		{
			Desired = A.EnemyArmyValue > 150.f && Ratio < 0.7f ? ArmyStance::Hold : ArmyStance::Advance;
		}
		else
		{
			Desired = Ratio >= 0.95f || A.EnemyArmyValue <= 150.f ? ArmyStance::Advance : ArmyStance::Hold;
		}
		// 波次进攻（工业时代起）：在驻守线集结，兵力达到对手 1.4 倍或集结满 50 秒后整体压上；攻势打光后退回重新集结
		const TeamState& Self = Sim.Team(Team);
		if (Self.Age >= 2 && !Sim.IsSuddenDeath())
		{
			const float WaveTarget = std::max(A.EnemyArmyValue * 1.4f, 350.f * static_cast<float>(Self.Age + 1));
			if (Current == ArmyStance::Hold)
			{
				Desired = A.MyArmyValue >= WaveTarget || Sim.Time() - LastStanceChange > 50.f ? ArmyStance::Advance : ArmyStance::Hold;
			}
			else
			{
				Desired = A.EnemyArmyValue > 200.f && Ratio < 0.6f ? ArmyStance::Hold : ArmyStance::Advance;
			}
		}
		if (Sim.IsSuddenDeath() && !(Ratio < 0.5f && A.Pressure > 0.4f))
		{
			Desired = ArmyStance::Advance; // 决战阶段基地更脆弱：以进攻为主
		}
		(void)Goal;
		if (Desired != Current)
		{
			Command C;
			C.Type = CommandType::SetStance;
			C.A = Desired == ArmyStance::Hold ? 1 : 0;
			if (Issue(Sim, C))
			{
				LastStanceChange = Sim.Time();
			}
		}
	}

	void AiPlayer::TryChooseDoctrine(Simulation& Sim)
	{
		const GameData& Data = Sim.Data();
		const TeamState& S = Sim.Team(Team);
		if (S.Offer.empty())
		{
			return;
		}
		// 偏好与本时代兵种配比一致的国策；前期更看重经济与经验，最后一个时代不再选择经验类
		const AgeDef& Age = Data.Ages[static_cast<size_t>(S.Age)];
		int32_t PreferredRole = 0;
		if (Age.AiRanged > Age.AiMelee && Age.AiRanged >= Age.AiHeavy)
		{
			PreferredRole = 1;
		}
		else if (Age.AiHeavy > Age.AiMelee && Age.AiHeavy > Age.AiRanged)
		{
			PreferredRole = 2;
		}
		const float Noise = Config.Difficulty == AiDifficulty::Easy ? 2.f : (Config.Difficulty == AiDifficulty::Hard ? 0.15f : 0.4f);
		int32_t Best = 0;
		float BestScore = -1.0e9f;
		for (size_t I = 0; I < S.Offer.size(); ++I)
		{
			const DoctrineDef& D = Data.Doctrines[static_cast<size_t>(S.Offer[I])];
			float Score = D.AiWeight;
			const int32_t TargetRole = static_cast<int32_t>(D.Target) - static_cast<int32_t>(DoctrineTarget::Melee);
			if (TargetRole == PreferredRole)
			{
				Score += 0.25f;
			}
			else if (D.Target == DoctrineTarget::All)
			{
				Score += 0.1f;
			}
			if (S.Age <= 1 && (D.IncomeBonus > 0.f || D.XpBonus > 0.f))
			{
				Score += 0.3f;
			}
			if (S.Age + 1 >= static_cast<int32_t>(Data.Ages.size()) && D.XpBonus > 0.f)
			{
				Score -= 1.f;
			}
			Score += (Random01() - 0.5f) * Noise;
			if (Score > BestScore)
			{
				BestScore = Score;
				Best = static_cast<int32_t>(I);
			}
		}
		Command C;
		C.Type = CommandType::ChooseDoctrine;
		C.A = Best;
		Issue(Sim, C);
	}

	void AiPlayer::ControlChampion(Simulation& Sim, const Assessment& A)
	{
		const GameData& Data = Sim.Data();
		if (Data.Champions.empty())
		{
			return;
		}
		const TeamState& S = Sim.Team(Team);
		const Unit* Champ = Sim.ChampionUnit(Team);
		if (Champ == nullptr)
		{
			// 阵亡期间恢复随军，复活后直接跟上部队
			bChampionRetreating = false;
			if (S.Order != ChampionOrder::Follow)
			{
				Command C;
				C.Type = CommandType::ChampionMove;
				C.A = 1;
				Issue(Sim, C);
			}
			return;
		}
		const float HpRatio = Champ->Hp / std::max(Champ->MaxHp, 1.f);
		if (Config.Difficulty != AiDifficulty::Easy)
		{
			// 残血回城休整（城门附近回血），恢复后重新随军
			if (!bChampionRetreating && HpRatio < 0.3f && A.Pressure < 0.8f)
			{
				Command C;
				C.Type = CommandType::ChampionMove;
				C.A = 0;
				C.X = Sim.BaseFrontX(Team);
				bChampionRetreating = Issue(Sim, C);
			}
			else if (bChampionRetreating && (HpRatio > 0.85f || A.Pressure >= 0.8f))
			{
				Command C;
				C.Type = CommandType::ChampionMove;
				C.A = 1;
				if (Issue(Sim, C))
				{
					bChampionRetreating = false;
				}
			}
		}
		const ChampionDef* CD = Sim.CurrentChampion(Team);
		if (CD == nullptr || S.ChampionCooldown > 0.f || bChampionRetreating)
		{
			return;
		}
		int32_t Allies = 0;
		bool bEngaged = false;
		for (const Unit& U : Sim.Units())
		{
			if (U.State == UnitState::Dying)
			{
				continue;
			}
			const float Dist = std::fabs(U.X - Champ->X);
			if (U.Team == Team && !U.Champion && Dist <= CD->AbilityRadius)
			{
				++Allies;
			}
			else if (U.Team != Team && Dist <= 500.f)
			{
				bEngaged = true;
			}
		}
		bool bUse = bEngaged && (Allies >= (Config.Difficulty == AiDifficulty::Hard ? 3 : 4) || HpRatio < 0.5f);
		if (Config.Difficulty == AiDifficulty::Easy)
		{
			bUse = bEngaged && Random01() < 0.3f;
		}
		if (bUse)
		{
			Command C;
			C.Type = CommandType::ChampionAbility;
			Issue(Sim, C);
		}
	}

	void AiPlayer::TryLastStand(Simulation& Sim, const Assessment& A)
	{
		const TeamState& S = Sim.Team(Team);
		if (S.LastStandUsed || S.BaseMaxHp <= 0.f)
		{
			return;
		}
		// 基地失血严重且敌军压到城下时才用（简单难度更晚、也更容易错过时机）
		const float Threshold = Config.Difficulty == AiDifficulty::Easy ? 0.25f : 0.4f;
		if (S.BaseHp > S.BaseMaxHp * Threshold || A.EnemyFrontDistToMyBase > 1200.f)
		{
			return;
		}
		if (Config.Difficulty == AiDifficulty::Easy && Random01() < 0.5f)
		{
			return;
		}
		Command C;
		C.Type = CommandType::LastStand;
		Issue(Sim, C);
	}

	bool AiPlayer::TryUpgradeAge(Simulation& Sim, const Assessment& A)
	{
		Command C;
		C.Type = CommandType::UpgradeAge;
		if (Sim.Check(Team, C) != CommandResult::Ok)
		{
			return false;
		}
		const TeamState& S = Sim.Team(Team);
		const AgeDef& Next = Sim.Data().Ages[static_cast<size_t>(S.Age + 1)];
		const float SafePressure = Config.Difficulty == AiDifficulty::Easy ? 0.3f : 0.45f;
		// 压力大时，只有升级后仍留有防守资金才升级（升级同时提升基地生命上限）
		if (A.Pressure < SafePressure || S.Gold >= static_cast<double>(Next.GoldToEnter + 120))
		{
			return Issue(Sim, C);
		}
		return false;
	}

	int32_t AiPlayer::ChooseTurretDef(const Simulation& Sim, const Assessment& A) const
	{
		const GameData& Data = Sim.Data();
		const int32_t Age = Sim.Team(Team).Age;
		const std::vector<int32_t> Options = Data.TurretsUpToAge(Age);
		int32_t Best = InvalidIndex;
		float BestScore = -1.0e9f;
		const bool bVsHeavy = A.EnemyHeavyArmor * 2 > A.EnemyLightArmor;
		for (const int32_t Idx : Options)
		{
			const TurretDef& T = Data.Turrets[static_cast<size_t>(Idx)];
			float Score = static_cast<float>(T.Age) * 100.f; // 新时代炮塔优先
			const bool bAntiHeavy = T.DmgType == DamageType::Siege;
			Score += bAntiHeavy == bVsHeavy ? 30.f : 0.f;
			if (Score > BestScore)
			{
				BestScore = Score;
				Best = Idx;
			}
		}
		return Best;
	}

	bool AiPlayer::TryBuildTurret(Simulation& Sim, const Assessment& A, SaveGoal Goal, int32_t GoalCost)
	{
		const TeamState& S = Sim.Team(Team);
		if (S.Gold < GoalCost)
		{
			return false;
		}
		if (Goal == SaveGoal::TurretSlot)
		{
			Command C;
			C.Type = CommandType::BuyTurretSlot;
			return Issue(Sim, C);
		}
		if (Goal == SaveGoal::Economy)
		{
			Command C;
			C.Type = CommandType::UpgradeEconomy;
			return Issue(Sim, C);
		}
		if (Goal != SaveGoal::Turret)
		{
			return false;
		}
		for (size_t I = 0; I < S.Turrets.size(); ++I)
		{
			if (S.Turrets[I].Unlocked && S.Turrets[I].Def == InvalidIndex)
			{
				Command C;
				C.Type = CommandType::BuildTurret;
				C.A = static_cast<int32_t>(I);
				C.B = ChooseTurretDef(Sim, A);
				return Issue(Sim, C);
			}
		}
		return false;
	}

	bool AiPlayer::TryImproveTurrets(Simulation& Sim, const Assessment& A, int32_t Reserve)
	{
		const GameData& Data = Sim.Data();
		const TeamState& S = Sim.Team(Team);
		const double Gold = S.Gold;
		const int32_t WantedDef = ChooseTurretDef(Sim, A);
		// 旧时代炮塔：富余且安全时出售，空槽会在下一轮被“炮塔目标”重建为新时代炮塔
		if (WantedDef != InvalidIndex && A.Pressure < 0.3f)
		{
			const TurretDef& Wanted = Data.Turrets[static_cast<size_t>(WantedDef)];
			for (size_t I = 0; I < S.Turrets.size(); ++I)
			{
				const TurretSlot& Slot = S.Turrets[I];
				if (Slot.Def != InvalidIndex && Data.Turrets[static_cast<size_t>(Slot.Def)].Age < S.Age
					&& Gold + Sim.TurretSellValue(Team, static_cast<int32_t>(I)) >= static_cast<double>(Wanted.Cost + Reserve + 150))
				{
					Command C;
					C.Type = CommandType::SellTurret;
					C.A = static_cast<int32_t>(I);
					return Issue(Sim, C);
				}
			}
		}
		// 富余时升级炮塔（简单难度不升级炮塔）
		for (size_t I = 0; I < S.Turrets.size() && Config.Difficulty != AiDifficulty::Easy; ++I)
		{
			const int32_t Cost = Sim.TurretUpgradeCost(Team, static_cast<int32_t>(I));
			if (Cost > 0 && Gold >= static_cast<double>(Cost + Reserve + 300))
			{
				Command C;
				C.Type = CommandType::UpgradeTurret;
				C.A = static_cast<int32_t>(I);
				return Issue(Sim, C);
			}
		}
		return false;
	}

	int32_t AiPlayer::ChooseUnitSlot(const Simulation& Sim, const Assessment& A)
	{
		const GameData& Data = Sim.Data();
		const std::vector<int32_t> List = Sim.TrainableUnits(Team);
		if (List.empty())
		{
			return InvalidIndex;
		}
		if (ReactionNoise > 0.f && Random01() < ReactionNoise)
		{
			return static_cast<int32_t>(Random01() * static_cast<float>(List.size())) % static_cast<int32_t>(List.size());
		}

		// 当前兵力 + 队列中的单位
		int32_t Count[3] = { A.MyRoleCount[0], A.MyRoleCount[1], A.MyRoleCount[2] };
		for (const QueueItem& Q : Sim.Team(Team).Queue)
		{
			Count[static_cast<int32_t>(Data.Units[static_cast<size_t>(Q.Def)].Role)] += 1;
		}
		const int32_t Total = Count[0] + Count[1] + Count[2];

		// 定位 → 训练面板槽位
		int32_t RoleSlot[3] = { InvalidIndex, InvalidIndex, InvalidIndex };
		for (size_t I = 0; I < List.size(); ++I)
		{
			const int32_t Role = static_cast<int32_t>(Data.Units[static_cast<size_t>(List[I])].Role);
			if (RoleSlot[Role] == InvalidIndex)
			{
				RoleSlot[Role] = static_cast<int32_t>(I);
			}
		}

		// 前排缺失：优先补近战
		if (Total == 0 || (!A.bMyFrontIsMelee && Count[0] + Count[2] == 0))
		{
			return RoleSlot[0] != InvalidIndex ? RoleSlot[0] : 0;
		}

		// 基础配比：普通/困难使用数据表中本时代的配比倾向，简单难度使用通用配比
		float Want[3] = { 0.45f, 0.35f, 0.20f };
		const int32_t MyAge = Sim.Team(Team).Age;
		if (Config.Difficulty != AiDifficulty::Easy && MyAge >= 0 && MyAge < static_cast<int32_t>(Data.Ages.size()))
		{
			const AgeDef& Doctrine = Data.Ages[static_cast<size_t>(MyAge)];
			Want[0] = Doctrine.AiMelee;
			Want[1] = Doctrine.AiRanged;
			Want[2] = Doctrine.AiHeavy;
		}
		const int32_t EnemyTotal = std::max(A.EnemyRoleCount[0] + A.EnemyRoleCount[1] + A.EnemyRoleCount[2], 1);
		if (A.EnemyRoleCount[1] >= 2 && A.EnemyRoleCount[1] * 2 >= EnemyTotal)
		{
			Want[2] += 0.15f; // 敌方远程多：重型顶上去
			Want[1] -= 0.10f;
		}
		if (A.EnemyHeavyArmor >= 2)
		{
			Want[0] += 0.15f; // 普通伤害克制重甲
			Want[2] -= 0.05f;
			if (RoleSlot[1] != InvalidIndex)
			{
				const UnitDef& MyRanged = Data.Units[static_cast<size_t>(List[static_cast<size_t>(RoleSlot[1])])];
				Want[1] += MyRanged.DmgType == DamageType::Siege ? 0.10f : -0.10f;
			}
		}
		if (A.EnemyLightArmor >= 4)
		{
			Want[1] += 0.15f; // 远程克制轻甲
		}

		// 克制评分（普通/困难）：每金币的“对当前敌军的输出 × 存活时间”，按伤害矩阵计算
		float Counter[3] = { 1.f, 1.f, 1.f };
		if (Config.Difficulty != AiDifficulty::Easy && EnemyTotal > 0)
		{
			float MaxScore = 0.f;
			for (int32_t R = 0; R < 3; ++R)
			{
				if (RoleSlot[R] == InvalidIndex)
				{
					continue;
				}
				const UnitDef& Me = Data.Units[static_cast<size_t>(List[static_cast<size_t>(RoleSlot[R])])];
				const float MyDps = Me.Damage / Me.AttackInterval;
				float Offense = 0.f;
				float Threat = 0.f;
				int32_t N = 0;
				for (const Unit& Foe : Sim.Units())
				{
					if (Foe.Team == Team || Foe.State == UnitState::Dying)
					{
						continue;
					}
					const UnitDef& FD = Data.Units[static_cast<size_t>(Foe.Def)];
					Offense += MyDps * Data.DamageMultiplier(Me.DmgType, FD.Armor) / FD.MaxHp * static_cast<float>(FD.Cost);
					Threat += FD.Damage / FD.AttackInterval * Data.DamageMultiplier(FD.DmgType, Me.Armor);
					++N;
				}
				if (N == 0)
				{
					break;
				}
				const float Survive = Me.MaxHp / std::max(Threat / static_cast<float>(N), 1.f);
				Counter[R] = Offense / static_cast<float>(N) * Survive / static_cast<float>(Me.Cost);
				MaxScore = std::max(MaxScore, Counter[R]);
			}
			if (MaxScore > 0.f)
			{
				for (float& C : Counter)
				{
					C /= MaxScore;
				}
			}
		}

		int32_t BestSlot = 0;
		float BestScore = -1.0e9f;
		for (int32_t R = 0; R < 3; ++R)
		{
			if (RoleSlot[R] == InvalidIndex)
			{
				continue;
			}
			const float Deficit = Want[R] - static_cast<float>(Count[R]) / static_cast<float>(std::max(Total, 1));
			const float Score = Deficit + (Config.Difficulty == AiDifficulty::Hard ? 0.35f : 0.2f) * Counter[R];
			if (Score > BestScore)
			{
				BestScore = Score;
				BestSlot = RoleSlot[R];
			}
		}
		return BestSlot;
	}

	bool AiPlayer::TryTrain(Simulation& Sim, const Assessment& A, int32_t Reserve)
	{
		const TeamState& S = Sim.Team(Team);
		const size_t MaxQueue = Config.Difficulty == AiDifficulty::Easy ? 1u : 2u;
		if (S.Queue.size() >= MaxQueue)
		{
			return false;
		}
		const int32_t Slot = ChooseUnitSlot(Sim, A);
		if (Slot == InvalidIndex)
		{
			return false;
		}
		const std::vector<int32_t> List = Sim.TrainableUnits(Team);
		const int32_t Cost = Sim.UnitCost(Team, List[static_cast<size_t>(Slot)]);
		Command C;
		C.Type = CommandType::Train;
		C.A = Slot;
		if (S.Gold - Cost >= Reserve)
		{
			return Issue(Sim, C);
		}
		// 攒钱期间：只有敌军逼近且兵力明显落后时才补充最便宜的单位（否则交给基地与炮塔防守，避免“越落后越送”）
		if (A.EnemyFrontDistToMyBase < 1500.f && A.MyArmyValue + 40.f < A.EnemyArmyValue * 0.8f)
		{
			int32_t Cheapest = 0;
			for (size_t I = 1; I < List.size(); ++I)
			{
				if (Sim.UnitCost(Team, List[I]) < Sim.UnitCost(Team, List[static_cast<size_t>(Cheapest)]))
				{
					Cheapest = static_cast<int32_t>(I);
				}
			}
			C.A = Cheapest;
			return Issue(Sim, C);
		}
		return false;
	}
}
