#include "SimTypes.h"
#include "SimState.h"

#include <algorithm>

namespace cw
{
	int32_t GameData::FindUnit(const std::string& InId) const
	{
		for (size_t I = 0; I < Units.size(); ++I)
		{
			if (Units[I].Id == InId)
			{
				return static_cast<int32_t>(I);
			}
		}
		return InvalidIndex;
	}

	int32_t GameData::FindTurret(const std::string& InId) const
	{
		for (size_t I = 0; I < Turrets.size(); ++I)
		{
			if (Turrets[I].Id == InId)
			{
				return static_cast<int32_t>(I);
			}
		}
		return InvalidIndex;
	}

	int32_t GameData::FindDoctrine(const std::string& InId) const
	{
		for (size_t I = 0; I < Doctrines.size(); ++I)
		{
			if (Doctrines[I].Id == InId)
			{
				return static_cast<int32_t>(I);
			}
		}
		return InvalidIndex;
	}

	std::vector<int32_t> GameData::UnitsForAge(int32_t InAge) const
	{
		std::vector<int32_t> Result;
		for (size_t I = 0; I < Units.size(); ++I)
		{
			if (Units[I].Age == InAge && !Units[I].IsChampion)
			{
				Result.push_back(static_cast<int32_t>(I));
			}
		}
		std::stable_sort(Result.begin(), Result.end(), [this](int32_t L, int32_t R)
		{
			return static_cast<int32_t>(Units[L].Role) < static_cast<int32_t>(Units[R].Role);
		});
		return Result;
	}

	std::vector<int32_t> GameData::TurretsUpToAge(int32_t InAge) const
	{
		std::vector<int32_t> Result;
		for (size_t I = 0; I < Turrets.size(); ++I)
		{
			if (Turrets[I].Age <= InAge)
			{
				Result.push_back(static_cast<int32_t>(I));
			}
		}
		return Result;
	}

	int32_t GameData::SkillForAge(int32_t InAge) const
	{
		// 取不高于当前时代的最高时代技能
		int32_t Best = InvalidIndex;
		for (size_t I = 0; I < Skills.size(); ++I)
		{
			if (Skills[I].Age <= InAge && (Best == InvalidIndex || Skills[I].Age > Skills[Best].Age))
			{
				Best = static_cast<int32_t>(I);
			}
		}
		return Best;
	}

	int32_t GameData::ChampionForAge(int32_t InAge) const
	{
		int32_t Best = InvalidIndex;
		for (size_t I = 0; I < Champions.size(); ++I)
		{
			if (Champions[I].Age <= InAge && (Best == InvalidIndex || Champions[I].Age > Champions[static_cast<size_t>(Best)].Age))
			{
				Best = static_cast<int32_t>(I);
			}
		}
		return Best;
	}

	void GameData::AppendChampion(const UnitDef& Combat, ChampionDef Def)
	{
		UnitDef U = Combat;
		U.IsChampion = true;
		Def.UnitDefIndex = static_cast<int32_t>(Units.size());
		Units.push_back(U);
		Champions.push_back(Def);
	}

	DoctrineEffects GameData::ComputeEffects(const std::vector<int32_t>& Picks) const
	{
		DoctrineEffects E;
		for (const int32_t Pick : Picks)
		{
			if (Pick < 0 || Pick >= static_cast<int32_t>(Doctrines.size()))
			{
				continue;
			}
			const DoctrineDef& D = Doctrines[static_cast<size_t>(Pick)];
			bool Roles[3] = { false, false, false };
			switch (D.Target)
			{
			case DoctrineTarget::All: Roles[0] = Roles[1] = Roles[2] = true; break;
			case DoctrineTarget::Melee: Roles[0] = true; break;
			case DoctrineTarget::Ranged: Roles[1] = true; break;
			case DoctrineTarget::Heavy: Roles[2] = true; break;
			default: break;
			}
			for (int32_t R = 0; R < 3; ++R)
			{
				if (!Roles[R])
				{
					continue;
				}
				E.Hp[R] += D.UnitHpBonus;
				E.Damage[R] += D.UnitDamageBonus;
				E.Speed[R] += D.UnitSpeedBonus;
				E.Range[R] += D.UnitRangeBonus;
				E.AttackSpeed[R] += D.UnitAttackSpeedBonus;
				E.Cost[R] += D.UnitCostBonus;
				E.TrainTime[R] += D.UnitTrainTimeBonus;
				E.StartRank[R] += D.UnitStartRank;
			}
			E.Income += D.IncomeBonus;
			E.KillGold += D.KillGoldBonus;
			E.Xp += D.XpBonus;
			E.TurretDamage += D.TurretDamageBonus;
			E.TurretRange += D.TurretRangeBonus;
			E.BaseHp += D.BaseHpBonus;
			E.SkillCooldown += D.SkillCooldownBonus;
			E.SkillDamage += D.SkillDamageBonus;
			E.StructureDamage += D.StructureDamageBonus;
			E.VeteranGain += D.VeteranGainBonus;
			E.ChampionHp += D.ChampionHpBonus;
			E.ChampionDamage += D.ChampionDamageBonus;
			E.ChampionCooldown += D.ChampionCooldownBonus;
			E.ChampionRespawn += D.ChampionRespawnBonus;
		}
		return E;
	}

	int32_t GameData::EffectiveUnitCost(const DoctrineEffects& E, int32_t InDef) const
	{
		if (InDef < 0 || InDef >= static_cast<int32_t>(Units.size()))
		{
			return 0;
		}
		const UnitDef& D = Units[static_cast<size_t>(InDef)];
		const float Mul = std::max(1.f + E.Cost[static_cast<int32_t>(D.Role)], 0.2f);
		return std::max(static_cast<int32_t>(static_cast<float>(D.Cost) * Mul + 0.5f), 1);
	}

	float GameData::EffectiveTrainTime(const DoctrineEffects& E, int32_t InDef) const
	{
		if (InDef < 0 || InDef >= static_cast<int32_t>(Units.size()))
		{
			return 1.f;
		}
		const UnitDef& D = Units[static_cast<size_t>(InDef)];
		return std::max(D.TrainTime * std::max(1.f + E.TrainTime[static_cast<int32_t>(D.Role)], 0.2f), 0.3f);
	}

	float GameData::DamageMultiplier(DamageType InDamage, ArmorType InArmor) const
	{
		const int32_t D = static_cast<int32_t>(InDamage);
		const int32_t A = static_cast<int32_t>(InArmor);
		if (D < 0 || D >= static_cast<int32_t>(DamageType::Count) || A < 0 || A >= static_cast<int32_t>(ArmorType::Count))
		{
			return 1.f;
		}
		return Rules.DamageMatrix[D][A];
	}

	std::string GameData::Validate() const
	{
		if (Ages.empty())
		{
			return "没有时代数据";
		}
		for (size_t I = 0; I < Ages.size(); ++I)
		{
			if (Ages[I].Index != static_cast<int32_t>(I))
			{
				return "时代 Index 必须从 0 连续递增: " + Ages[I].Id;
			}
		}
		for (const AgeDef& Age : Ages)
		{
			if (!Age.Implemented)
			{
				continue;
			}
			if (UnitsForAge(Age.Index).size() < 3)
			{
				return "已实装时代至少需要 3 个兵种: " + Age.Id;
			}
			if (SkillForAge(Age.Index) == InvalidIndex)
			{
				return "已实装时代缺少技能: " + Age.Id;
			}
		}
		for (const UnitDef& U : Units)
		{
			if (U.Age < 0 || U.Age >= static_cast<int32_t>(Ages.size()))
			{
				return "兵种时代越界: " + U.Id;
			}
			if (U.MaxHp <= 0.f || U.AttackInterval <= 0.f || U.AttackWindup < 0.f || U.AttackWindup > U.AttackInterval
				|| U.Radius <= 0.f || U.MoveSpeed <= 0.f || U.Cost <= 0 || U.TrainTime <= 0.f || U.Range < 0.f)
			{
				return "兵种数值非法: " + U.Id;
			}
		}
		for (const TurretDef& T : Turrets)
		{
			if (T.Age < 0 || T.Age >= static_cast<int32_t>(Ages.size()) || T.AttackInterval <= 0.f || T.Range <= 0.f || T.MaxLevel < 1)
			{
				return "炮塔数值非法: " + T.Id;
			}
		}
		if (Rules.QueueCapacity <= 0 || Rules.InitialTurretSlots < 0 || Rules.MaxTurretSlots < Rules.InitialTurretSlots
			|| Rules.LaneRows < 1 || Rules.LaneRows > MaxLaneRows)
		{
			return "全局规则非法";
		}
		if (!Champions.empty())
		{
			if (ChampionForAge(0) == InvalidIndex)
			{
				return "统帅表缺少石器时代（Age 0）的统帅";
			}
			for (const ChampionDef& C : Champions)
			{
				if (C.UnitDefIndex < 0 || C.UnitDefIndex >= static_cast<int32_t>(Units.size()) || !Units[static_cast<size_t>(C.UnitDefIndex)].IsChampion
					|| C.Age < 0 || C.Age >= static_cast<int32_t>(Ages.size()) || C.RespawnTime <= 0.f || C.AbilityCooldown <= 0.f || C.AbilityRadius <= 0.f)
				{
					return "统帅数值非法: " + C.Id;
				}
			}
		}
		if (!Doctrines.empty() && static_cast<int32_t>(Doctrines.size()) < std::max(Rules.DoctrineChoices, 1) * 2)
		{
			return "国策数量太少：至少需要每次选项数的两倍";
		}
		for (const DoctrineDef& D : Doctrines)
		{
			if (D.MinAge < 0 || (D.MaxAge >= 0 && D.MaxAge < D.MinAge) || D.UnitStartRank < 0 || D.UnitStartRank > 3)
			{
				return "国策数值非法: " + D.Id;
			}
		}
		return std::string();
	}

	const char* ToString(DamageType V)
	{
		switch (V)
		{
		case DamageType::Normal: return "Normal";
		case DamageType::Pierce: return "Pierce";
		case DamageType::Siege: return "Siege";
		case DamageType::Energy: return "Energy";
		default: return "Unknown";
		}
	}

	const char* ToString(ArmorType V)
	{
		switch (V)
		{
		case ArmorType::Light: return "Light";
		case ArmorType::Shielded: return "Shielded";
		case ArmorType::Heavy: return "Heavy";
		case ArmorType::Building: return "Building";
		default: return "Unknown";
		}
	}

	const char* ToString(UnitRole V)
	{
		switch (V)
		{
		case UnitRole::Melee: return "Melee";
		case UnitRole::Ranged: return "Ranged";
		case UnitRole::Heavy: return "Heavy";
		default: return "Unknown";
		}
	}

	const char* ToString(TargetRule V)
	{
		switch (V)
		{
		case TargetRule::Nearest: return "Nearest";
		case TargetRule::LowestHp: return "LowestHp";
		case TargetRule::PreferRanged: return "PreferRanged";
		case TargetRule::PreferHeavy: return "PreferHeavy";
		case TargetRule::PreferStructure: return "PreferStructure";
		default: return "Unknown";
		}
	}

	const char* ToString(DoctrineTarget V)
	{
		switch (V)
		{
		case DoctrineTarget::None: return "None";
		case DoctrineTarget::All: return "All";
		case DoctrineTarget::Melee: return "Melee";
		case DoctrineTarget::Ranged: return "Ranged";
		case DoctrineTarget::Heavy: return "Heavy";
		default: return "Unknown";
		}
	}

	const char* ToString(CommandResult V)
	{
		switch (V)
		{
		case CommandResult::Ok: return "Ok";
		case CommandResult::MatchNotRunning: return "MatchNotRunning";
		case CommandResult::InvalidTeam: return "InvalidTeam";
		case CommandResult::InvalidParam: return "InvalidParam";
		case CommandResult::NotEnoughGold: return "NotEnoughGold";
		case CommandResult::NotEnoughXp: return "NotEnoughXp";
		case CommandResult::QueueFull: return "QueueFull";
		case CommandResult::LockedByAge: return "LockedByAge";
		case CommandResult::AgeMax: return "AgeMax";
		case CommandResult::AgeNotImplemented: return "AgeNotImplemented";
		case CommandResult::Upgrading: return "Upgrading";
		case CommandResult::SlotLocked: return "SlotLocked";
		case CommandResult::SlotOccupied: return "SlotOccupied";
		case CommandResult::SlotEmpty: return "SlotEmpty";
		case CommandResult::NoMoreSlots: return "NoMoreSlots";
		case CommandResult::MaxLevel: return "MaxLevel";
		case CommandResult::OnCooldown: return "OnCooldown";
		case CommandResult::BadTarget: return "BadTarget";
		case CommandResult::NoOffer: return "NoOffer";
		case CommandResult::ChampionDead: return "ChampionDead";
		case CommandResult::NoChampion: return "NoChampion";
		case CommandResult::Unavailable: return "Unavailable";
		case CommandResult::AlreadyUsed: return "AlreadyUsed";
		default: return "Unknown";
		}
	}

	template <typename EnumT>
	static bool ParseEnumByName(const std::string& S, EnumT& Out, EnumT CountValue)
	{
		for (int32_t I = 0; I < static_cast<int32_t>(CountValue); ++I)
		{
			const EnumT Candidate = static_cast<EnumT>(I);
			if (S == ToString(Candidate))
			{
				Out = Candidate;
				return true;
			}
		}
		return false;
	}

	bool ParseDamageType(const std::string& S, DamageType& Out) { return ParseEnumByName(S, Out, DamageType::Count); }
	bool ParseArmorType(const std::string& S, ArmorType& Out) { return ParseEnumByName(S, Out, ArmorType::Count); }
	bool ParseUnitRole(const std::string& S, UnitRole& Out) { return ParseEnumByName(S, Out, UnitRole::Count); }
	bool ParseTargetRule(const std::string& S, TargetRule& Out) { return ParseEnumByName(S, Out, TargetRule::Count); }
	bool ParseDoctrineTarget(const std::string& S, DoctrineTarget& Out) { return ParseEnumByName(S, Out, DoctrineTarget::Count); }
}
