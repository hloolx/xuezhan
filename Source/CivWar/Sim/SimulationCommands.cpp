// 血战文明 - 规则核心：玩家指令校验与执行、界面/AI 查询
// 所有资源消耗、时代条件、冷却和落点都在这里校验；客户端发来的参数一律视为不可信。
#include "Simulation.h"

#include <algorithm>
#include <cmath>

namespace cw
{
	std::vector<int32_t> Simulation::TrainableUnits(int32_t InTeam) const
	{
		return GameDataRef.UnitsForAge(Teams[InTeam].Age);
	}

	int32_t Simulation::UnlockedTurretSlots(int32_t InTeam) const
	{
		int32_t Count = 0;
		for (const TurretSlot& S : Teams[InTeam].Turrets)
		{
			Count += S.Unlocked ? 1 : 0;
		}
		return Count;
	}

	int32_t Simulation::EconomyUpgradeCost(int32_t InTeam) const
	{
		const RulesDef& R = GameDataRef.Rules;
		const int32_t Level = Teams[InTeam].EconomyLevel;
		return Level >= R.EconomyMaxLevel ? -1 : R.EconomyBaseCost * (Level + 1);
	}

	float Simulation::IncomePerSecond(int32_t InTeam) const
	{
		const TeamState& S = Teams[InTeam];
		const float Base = GameDataRef.Ages[static_cast<size_t>(S.Age)].IncomePerSec;
		return Base * (1.f + GameDataRef.Rules.EconomyIncomeBonus * static_cast<float>(S.EconomyLevel)) * std::max(1.f + S.Effects.Income, 0.f)
			* IncomeMultiplier();
	}

	int32_t Simulation::UnitCost(int32_t InTeam, int32_t InDef) const
	{
		return GameDataRef.EffectiveUnitCost(Teams[InTeam].Effects, InDef);
	}

	float Simulation::UnitTrainTime(int32_t InTeam, int32_t InDef) const
	{
		return GameDataRef.EffectiveTrainTime(Teams[InTeam].Effects, InDef);
	}

	float Simulation::TurretDamageFor(int32_t InTeam, int32_t TurretDefIndex, int32_t Level) const
	{
		return TurretDamage(TurretDefIndex, Level) * std::max(1.f + Teams[InTeam].Effects.TurretDamage, 0.f);
	}

	float Simulation::TurretRangeFor(int32_t InTeam, int32_t TurretDefIndex, int32_t Level) const
	{
		return TurretRange(TurretDefIndex, Level) * std::max(1.f + Teams[InTeam].Effects.TurretRange, 0.5f);
	}

	float Simulation::HoldLineX(int32_t InTeam) const
	{
		return BaseFrontX(InTeam) + static_cast<float>(Dir(InTeam)) * GameDataRef.Rules.HoldLineDistance;
	}

	int32_t Simulation::NextTurretSlotCost(int32_t InTeam) const
	{
		const RulesDef& R = GameDataRef.Rules;
		const int32_t Unlocked = UnlockedTurretSlots(InTeam);
		if (Unlocked >= static_cast<int32_t>(Teams[InTeam].Turrets.size()))
		{
			return -1;
		}
		const int32_t ExtraIndex = Unlocked - R.InitialTurretSlots + 1;
		return R.TurretSlotCostBase * std::max(ExtraIndex, 1);
	}

	int32_t Simulation::TurretUpgradeCost(int32_t InTeam, int32_t Slot) const
	{
		const std::vector<TurretSlot>& Slots = Teams[InTeam].Turrets;
		if (Slot < 0 || Slot >= static_cast<int32_t>(Slots.size()) || Slots[static_cast<size_t>(Slot)].Def == InvalidIndex)
		{
			return -1;
		}
		const TurretSlot& S = Slots[static_cast<size_t>(Slot)];
		const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(S.Def)];
		if (S.Level >= D.MaxLevel)
		{
			return -1;
		}
		return static_cast<int32_t>(static_cast<float>(D.Cost) * D.UpgradeCostRatio * static_cast<float>(S.Level) + 0.5f);
	}

	int32_t Simulation::TurretSellValue(int32_t InTeam, int32_t Slot) const
	{
		const std::vector<TurretSlot>& Slots = Teams[InTeam].Turrets;
		if (Slot < 0 || Slot >= static_cast<int32_t>(Slots.size()) || Slots[static_cast<size_t>(Slot)].Def == InvalidIndex)
		{
			return 0;
		}
		return static_cast<int32_t>(static_cast<float>(Slots[static_cast<size_t>(Slot)].Invested) * GameDataRef.Rules.SellRefundRatio + 0.5f);
	}

	float Simulation::TurretDamage(int32_t TurretDefIndex, int32_t Level) const
	{
		const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(TurretDefIndex)];
		return D.Damage * (1.f + D.DamagePerLevel * static_cast<float>(std::max(Level - 1, 0)));
	}

	float Simulation::TurretRange(int32_t TurretDefIndex, int32_t Level) const
	{
		const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(TurretDefIndex)];
		return D.Range * (1.f + D.RangePerLevel * static_cast<float>(std::max(Level - 1, 0)));
	}

	void Simulation::SkillTargetRange(int32_t InTeam, float& OutMin, float& OutMax) const
	{
		const float MinDist = GameDataRef.Rules.SkillMinDistanceFromEnemyBase;
		OutMin = BaseFrontX(0);
		OutMax = BaseFrontX(1);
		if (InTeam == 0)
		{
			OutMax -= MinDist;
		}
		else
		{
			OutMin += MinDist;
		}
	}

	CommandResult Simulation::Check(int32_t InTeam, const Command& Cmd) const
	{
		if (InTeam < 0 || InTeam >= TeamCount)
		{
			return CommandResult::InvalidTeam;
		}
		if (CurrentPhase != MatchPhase::Running)
		{
			return CommandResult::MatchNotRunning;
		}
		const TeamState& S = Teams[InTeam];
		const RulesDef& R = GameDataRef.Rules;
		const int32_t SlotCount = static_cast<int32_t>(S.Turrets.size());

		switch (Cmd.Type)
		{
		case CommandType::Train:
		{
			const std::vector<int32_t> List = GameDataRef.UnitsForAge(S.Age);
			if (Cmd.A < 0 || Cmd.A >= static_cast<int32_t>(List.size()))
			{
				return CommandResult::InvalidParam;
			}
			if (static_cast<int32_t>(S.Queue.size()) >= R.QueueCapacity)
			{
				return CommandResult::QueueFull;
			}
			if (S.Gold < UnitCost(InTeam, List[static_cast<size_t>(Cmd.A)]))
			{
				return CommandResult::NotEnoughGold;
			}
			return CommandResult::Ok;
		}
		case CommandType::CancelTrain:
			if (Cmd.A < 0 || Cmd.A >= static_cast<int32_t>(S.Queue.size()))
			{
				return CommandResult::InvalidParam;
			}
			return CommandResult::Ok;
		case CommandType::UpgradeAge:
		{
			const int32_t Next = S.Age + 1;
			if (S.Upgrading)
			{
				return CommandResult::Upgrading;
			}
			if (Next >= static_cast<int32_t>(GameDataRef.Ages.size()))
			{
				return CommandResult::AgeMax;
			}
			const AgeDef& A = GameDataRef.Ages[static_cast<size_t>(Next)];
			if (!A.Implemented)
			{
				return CommandResult::AgeNotImplemented;
			}
			if (S.Xp < A.XpToEnter)
			{
				return CommandResult::NotEnoughXp;
			}
			if (S.Gold < A.GoldToEnter)
			{
				return CommandResult::NotEnoughGold;
			}
			return CommandResult::Ok;
		}
		case CommandType::BuyTurretSlot:
		{
			const int32_t Cost = NextTurretSlotCost(InTeam);
			if (Cost < 0)
			{
				return CommandResult::NoMoreSlots;
			}
			return S.Gold < Cost ? CommandResult::NotEnoughGold : CommandResult::Ok;
		}
		case CommandType::BuildTurret:
		{
			if (Cmd.A < 0 || Cmd.A >= SlotCount || Cmd.B < 0 || Cmd.B >= static_cast<int32_t>(GameDataRef.Turrets.size()))
			{
				return CommandResult::InvalidParam;
			}
			const TurretSlot& Slot = S.Turrets[static_cast<size_t>(Cmd.A)];
			if (!Slot.Unlocked)
			{
				return CommandResult::SlotLocked;
			}
			if (Slot.Def != InvalidIndex)
			{
				return CommandResult::SlotOccupied;
			}
			const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(Cmd.B)];
			if (D.Age > S.Age)
			{
				return CommandResult::LockedByAge;
			}
			return S.Gold < D.Cost ? CommandResult::NotEnoughGold : CommandResult::Ok;
		}
		case CommandType::UpgradeTurret:
		{
			if (Cmd.A < 0 || Cmd.A >= SlotCount)
			{
				return CommandResult::InvalidParam;
			}
			const TurretSlot& Slot = S.Turrets[static_cast<size_t>(Cmd.A)];
			if (Slot.Def == InvalidIndex)
			{
				return CommandResult::SlotEmpty;
			}
			const int32_t Cost = TurretUpgradeCost(InTeam, Cmd.A);
			if (Cost < 0)
			{
				return CommandResult::MaxLevel;
			}
			return S.Gold < Cost ? CommandResult::NotEnoughGold : CommandResult::Ok;
		}
		case CommandType::SellTurret:
			if (Cmd.A < 0 || Cmd.A >= SlotCount)
			{
				return CommandResult::InvalidParam;
			}
			return S.Turrets[static_cast<size_t>(Cmd.A)].Def == InvalidIndex ? CommandResult::SlotEmpty : CommandResult::Ok;
		case CommandType::CastSkill:
		{
			const int32_t Skill = GameDataRef.SkillForAge(S.Age);
			if (Skill == InvalidIndex)
			{
				return CommandResult::InvalidParam;
			}
			if (S.SkillCooldown > 0.f)
			{
				return CommandResult::OnCooldown;
			}
			if (S.Gold < GameDataRef.Skills[static_cast<size_t>(Skill)].Cost)
			{
				return CommandResult::NotEnoughGold;
			}
			float Min = 0.f;
			float Max = 0.f;
			SkillTargetRange(InTeam, Min, Max);
			if (!(Cmd.X >= Min && Cmd.X <= Max)) // 同时拒绝 NaN
			{
				return CommandResult::BadTarget;
			}
			return CommandResult::Ok;
		}
		case CommandType::UpgradeEconomy:
		{
			const int32_t Cost = EconomyUpgradeCost(InTeam);
			if (Cost < 0)
			{
				return CommandResult::MaxLevel;
			}
			return S.Gold < Cost ? CommandResult::NotEnoughGold : CommandResult::Ok;
		}
		case CommandType::SetStance:
			return Cmd.A == 0 || Cmd.A == 1 ? CommandResult::Ok : CommandResult::InvalidParam;
		case CommandType::ChooseDoctrine:
			if (S.Offer.empty())
			{
				return CommandResult::NoOffer;
			}
			return Cmd.A >= 0 && Cmd.A < static_cast<int32_t>(S.Offer.size()) ? CommandResult::Ok : CommandResult::InvalidParam;
		case CommandType::ChampionMove:
			if (GameDataRef.Champions.empty())
			{
				return CommandResult::NoChampion;
			}
			if (Cmd.A == 1)
			{
				return CommandResult::Ok;
			}
			// 坚守位置必须在两座城门之间（同时拒绝 NaN）
			return Cmd.A == 0 && Cmd.X >= BaseFrontX(0) && Cmd.X <= BaseFrontX(1) ? CommandResult::Ok : CommandResult::InvalidParam;
		case CommandType::ChampionAbility:
			if (GameDataRef.Champions.empty())
			{
				return CommandResult::NoChampion;
			}
			if (ChampionUnit(InTeam) == nullptr)
			{
				return CommandResult::ChampionDead;
			}
			return S.ChampionCooldown > 0.f ? CommandResult::OnCooldown : CommandResult::Ok;
		case CommandType::LastStand:
			if (S.LastStandUsed)
			{
				return CommandResult::AlreadyUsed;
			}
			return S.BaseMaxHp > 0.f && S.BaseHp <= S.BaseMaxHp * R.LastStandBaseHpRatio ? CommandResult::Ok : CommandResult::Unavailable;
		default:
			return CommandResult::InvalidParam;
		}
	}

	CommandResult Simulation::Apply(int32_t InTeam, const Command& Cmd)
	{
		const CommandResult Result = Check(InTeam, Cmd);
		if (Result != CommandResult::Ok)
		{
			return Result;
		}
		TeamState& S = Teams[InTeam];
		switch (Cmd.Type)
		{
		case CommandType::Train:
		{
			const int32_t Def = GameDataRef.UnitsForAge(S.Age)[static_cast<size_t>(Cmd.A)];
			const int32_t Cost = UnitCost(InTeam, Def);
			Pay(InTeam, Cost);
			QueueItem Item;
			Item.Def = Def;
			Item.PaidGold = Cost;
			S.Queue.push_back(Item);
			break;
		}
		case CommandType::CancelTrain:
		{
			// 取消返还全部已付金币
			const QueueItem Item = S.Queue[static_cast<size_t>(Cmd.A)];
			S.Gold += Item.PaidGold;
			S.Stats.GoldSpent -= Item.PaidGold;
			S.Queue.erase(S.Queue.begin() + Cmd.A);
			break;
		}
		case CommandType::UpgradeAge:
		{
			const AgeDef& Next = GameDataRef.Ages[static_cast<size_t>(S.Age + 1)];
			Pay(InTeam, Next.GoldToEnter);
			S.Upgrading = true;
			S.UpgradeTimeLeft = Next.UpgradeDuration;
			Emit(EventType::AgeUpgradeStart, InTeam, S.Age + 1);
			break;
		}
		case CommandType::BuyTurretSlot:
		{
			Pay(InTeam, NextTurretSlotCost(InTeam));
			for (TurretSlot& Slot : S.Turrets)
			{
				if (!Slot.Unlocked)
				{
					Slot.Unlocked = true;
					break;
				}
			}
			break;
		}
		case CommandType::BuildTurret:
		{
			const TurretDef& D = GameDataRef.Turrets[static_cast<size_t>(Cmd.B)];
			Pay(InTeam, D.Cost);
			TurretSlot& Slot = S.Turrets[static_cast<size_t>(Cmd.A)];
			Slot.Def = Cmd.B;
			Slot.Level = 1;
			Slot.Cooldown = 0.5f;
			Slot.RetargetTimer = 0.f;
			Slot.TargetId = TargetNone;
			Slot.Invested = D.Cost;
			break;
		}
		case CommandType::UpgradeTurret:
		{
			const int32_t Cost = TurretUpgradeCost(InTeam, Cmd.A);
			Pay(InTeam, Cost);
			TurretSlot& Slot = S.Turrets[static_cast<size_t>(Cmd.A)];
			Slot.Level += 1;
			Slot.Invested += Cost;
			break;
		}
		case CommandType::SellTurret:
		{
			const int32_t Refund = TurretSellValue(InTeam, Cmd.A);
			S.Gold += Refund;
			TurretSlot& Slot = S.Turrets[static_cast<size_t>(Cmd.A)];
			const bool bUnlocked = Slot.Unlocked;
			Slot = TurretSlot();
			Slot.Unlocked = bUnlocked;
			break;
		}
		case CommandType::CastSkill:
		{
			const int32_t Skill = GameDataRef.SkillForAge(S.Age);
			const SkillDef& D = GameDataRef.Skills[static_cast<size_t>(Skill)];
			Pay(InTeam, D.Cost);
			S.SkillCooldown = D.Cooldown * std::max(1.f + S.Effects.SkillCooldown, 0.3f);
			SkillCast Cast;
			Cast.Id = NextCastId++;
			Cast.Team = InTeam;
			Cast.Skill = Skill;
			Cast.X = Cmd.X;
			Cast.TimeLeft = D.Delay;
			CastList.push_back(Cast);
			Emit(EventType::SkillCast, InTeam, Cast.Id, Skill, Cmd.X, D.Radius);
			break;
		}
		case CommandType::UpgradeEconomy:
		{
			Pay(InTeam, EconomyUpgradeCost(InTeam));
			S.EconomyLevel += 1;
			Emit(EventType::EconomyUpgraded, InTeam, S.EconomyLevel);
			break;
		}
		case CommandType::SetStance:
			S.Stance = Cmd.A == 1 ? ArmyStance::Hold : ArmyStance::Advance;
			Emit(EventType::StanceChanged, InTeam, Cmd.A);
			break;
		case CommandType::ChooseDoctrine:
		{
			const int32_t Pick = S.Offer[static_cast<size_t>(Cmd.A)];
			S.Doctrines.push_back(Pick);
			S.Offer.clear();
			S.PendingPicks = std::max(S.PendingPicks - 1, 0);
			ApplyDoctrineEffects(InTeam);
			Emit(EventType::DoctrineChosen, InTeam, Pick);
			if (S.PendingPicks > 0)
			{
				GenerateOffer(InTeam); // 还有未使用的选择次数（例如连续升级时代）
			}
			break;
		}
		case CommandType::ChampionMove:
			if (Cmd.A == 1)
			{
				S.Order = ChampionOrder::Follow;
			}
			else
			{
				S.Order = ChampionOrder::Hold;
				S.ChampionHoldX = Cmd.X;
			}
			break;
		case CommandType::ChampionAbility:
		{
			const ChampionDef* CD = CurrentChampion(InTeam);
			const Unit* Champ = ChampionUnit(InTeam);
			const float CenterX = Champ->X;
			const int32_t ChampId = Champ->Id;
			int32_t Affected = 0;
			for (Unit& U : UnitList)
			{
				if (U.Team != InTeam || !IsAlive(U) || std::fabs(U.X - CenterX) > CD->AbilityRadius + GameDataRef.Units[static_cast<size_t>(U.Def)].Radius)
				{
					continue;
				}
				U.BuffTime = CD->AbilityDuration;
				U.BuffDamage = CD->AbilityDamageBonus;
				U.BuffAttackSpeed = CD->AbilityAttackSpeedBonus;
				U.Hp = std::min(U.MaxHp, U.Hp + U.MaxHp * CD->AbilityHeal);
				Affected += U.Champion ? 0 : 1;
			}
			S.ChampionCooldown = ChampionAbilityCooldown(InTeam);
			S.ChampionAbilitySeq = static_cast<uint8_t>(S.ChampionAbilitySeq + 1);
			Emit(EventType::ChampionAbility, InTeam, ChampId, Affected, CenterX, CD->AbilityRadius);
			break;
		}
		case CommandType::LastStand:
		{
			// 背水一战：修复城墙、全军鼓舞、炮塔强化、免费征召本时代近战兵；阵亡的统帅立即复活
			const RulesDef& Rules = GameDataRef.Rules;
			S.LastStandUsed = true;
			S.BaseHp = std::min(S.BaseMaxHp, S.BaseHp + S.BaseMaxHp * Rules.LastStandRepair);
			S.TurretBoostTime = Rules.LastStandTurretDuration;
			for (Unit& U : UnitList)
			{
				if (U.Team == InTeam && IsAlive(U))
				{
					U.BuffTime = std::max(U.BuffTime, Rules.LastStandBuffDuration);
					U.BuffDamage = std::max(U.BuffDamage, Rules.LastStandDamageBonus);
					U.BuffAttackSpeed = std::max(U.BuffAttackSpeed, Rules.LastStandAttackSpeedBonus);
				}
			}
			const std::vector<int32_t> List = GameDataRef.UnitsForAge(S.Age);
			int32_t Militia = 0;
			if (!List.empty())
			{
				for (int32_t I = 0; I < Rules.LastStandMilitia; ++I)
				{
					// 免费、无需训练时间：插到队列最前，出生点空出来就立刻出阵
					QueueItem Item;
					Item.Def = List[0];
					Item.Progress = UnitTrainTime(InTeam, List[0]);
					Item.PaidGold = 0;
					S.Queue.insert(S.Queue.begin(), Item);
					++Militia;
				}
			}
			if (S.ChampionId < 0 && !GameDataRef.Champions.empty())
			{
				S.ChampionRespawn = 0.f;
			}
			Emit(EventType::LastStand, InTeam, Militia);
			break;
		}
		default:
			break;
		}
		return CommandResult::Ok;
	}
}
