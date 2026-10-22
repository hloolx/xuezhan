#include "JsonDataLoader.h"
#include "MiniJson.h"

#include <algorithm>
#include <fstream>
#include <sstream>

namespace harness
{
	namespace
	{
		bool ReadFile(const std::string& Path, std::string& Out)
		{
			std::ifstream File(Path, std::ios::binary);
			if (!File)
			{
				return false;
			}
			std::stringstream Buffer;
			Buffer << File.rdbuf();
			Out = Buffer.str();
			// 跳过 UTF-8 BOM
			if (Out.size() >= 3 && static_cast<unsigned char>(Out[0]) == 0xEF && static_cast<unsigned char>(Out[1]) == 0xBB
				&& static_cast<unsigned char>(Out[2]) == 0xBF)
			{
				Out.erase(0, 3);
			}
			return true;
		}

		bool LoadTable(const std::string& Path, mj::Value& Out, std::string& Error)
		{
			std::string Text;
			if (!ReadFile(Path, Text))
			{
				Error = "无法读取 " + Path;
				return false;
			}
			mj::Parser P(Text);
			if (!P.Parse(Out, Error))
			{
				Error = Path + ": " + Error;
				return false;
			}
			if (Out.T != mj::Type::Array)
			{
				Error = Path + ": 顶层必须是数组";
				return false;
			}
			return true;
		}

		float F(const mj::Value& Row, const char* Key, float Default)
		{
			const mj::Value* V = Row.Get(Key);
			return V != nullptr && V->T == mj::Type::Number ? static_cast<float>(V->N) : Default;
		}

		int32_t I(const mj::Value& Row, const char* Key, int32_t Default)
		{
			const mj::Value* V = Row.Get(Key);
			return V != nullptr && V->T == mj::Type::Number ? static_cast<int32_t>(V->N) : Default;
		}

		bool B(const mj::Value& Row, const char* Key, bool Default)
		{
			const mj::Value* V = Row.Get(Key);
			return V != nullptr && V->T == mj::Type::Bool ? V->B : Default;
		}

		std::string S(const mj::Value& Row, const char* Key)
		{
			const mj::Value* V = Row.Get(Key);
			return V != nullptr && V->T == mj::Type::String ? V->S : std::string();
		}

		template <typename EnumT, typename ParseFn>
		bool E(const mj::Value& Row, const char* Key, EnumT& Out, ParseFn Fn, std::string& Error)
		{
			const std::string Text = S(Row, Key);
			if (Text.empty())
			{
				return true; // 使用默认值
			}
			if (!Fn(Text, Out))
			{
				Error = "行 " + S(Row, "Name") + " 字段 " + Key + " 枚举值无效: " + Text;
				return false;
			}
			return true;
		}
	}

	bool LoadGameData(const std::string& DataDir, cw::GameData& Out, std::string& Error)
	{
		Out = cw::GameData();
		mj::Value Table;

		// 全局规则
		if (!LoadTable(DataDir + "/Rules.json", Table, Error))
		{
			return false;
		}
		if (Table.Items.empty())
		{
			Error = "Rules.json 为空";
			return false;
		}
		{
			const mj::Value& R = Table.Items[0];
			cw::RulesDef& D = Out.Rules;
			D.LaneLength = F(R, "LaneLength", D.LaneLength);
			D.BaseHalfWidth = F(R, "BaseHalfWidth", D.BaseHalfWidth);
			D.LaneRows = I(R, "LaneRows", D.LaneRows);
			D.RowSpacing = F(R, "RowSpacing", D.RowSpacing);
			D.StartGold = I(R, "StartGold", D.StartGold);
			D.QueueCapacity = I(R, "QueueCapacity", D.QueueCapacity);
			D.KillGoldRatio = F(R, "KillGoldRatio", D.KillGoldRatio);
			D.TurretKillGoldFactor = F(R, "TurretKillGoldFactor", D.TurretKillGoldFactor);
			D.LoserXpRatio = F(R, "LoserXpRatio", D.LoserXpRatio);
			D.PassiveXpPerSec = F(R, "PassiveXpPerSec", D.PassiveXpPerSec);
			D.AllySpacingFactor = F(R, "AllySpacingFactor", D.AllySpacingFactor);
			D.DeathDuration = F(R, "DeathDuration", D.DeathDuration);
			D.RetargetInterval = F(R, "RetargetInterval", D.RetargetInterval);
			D.TurretRetargetInterval = F(R, "TurretRetargetInterval", D.TurretRetargetInterval);
			D.ChargeRechargeTime = F(R, "ChargeRechargeTime", D.ChargeRechargeTime);
			D.SplashSecondaryRatio = F(R, "SplashSecondaryRatio", D.SplashSecondaryRatio);
			D.InitialTurretSlots = I(R, "InitialTurretSlots", D.InitialTurretSlots);
			D.MaxTurretSlots = I(R, "MaxTurretSlots", D.MaxTurretSlots);
			D.TurretSlotCostBase = I(R, "TurretSlotCostBase", D.TurretSlotCostBase);
			D.SellRefundRatio = F(R, "SellRefundRatio", D.SellRefundRatio);
			D.SkillMinDistanceFromEnemyBase = F(R, "SkillMinDistanceFromEnemyBase", D.SkillMinDistanceFromEnemyBase);
			D.TurretOffset = F(R, "TurretOffset", D.TurretOffset);
			D.SuddenDeathTime = F(R, "SuddenDeathTime", D.SuddenDeathTime);
			D.SuddenDeathBaseDamage = F(R, "SuddenDeathBaseDamage", D.SuddenDeathBaseDamage);
			D.SuddenDeathRampPerMinute = F(R, "SuddenDeathRampPerMinute", D.SuddenDeathRampPerMinute);
			D.SuddenDeathMaxMultiplier = F(R, "SuddenDeathMaxMultiplier", D.SuddenDeathMaxMultiplier);
			D.SuddenDeathIncomeMultiplier = F(R, "SuddenDeathIncomeMultiplier", D.SuddenDeathIncomeMultiplier);
			D.SuddenDeathTurretDecayPerMinute = F(R, "SuddenDeathTurretDecayPerMinute", D.SuddenDeathTurretDecayPerMinute);
			D.SuddenDeathTurretMin = F(R, "SuddenDeathTurretMin", D.SuddenDeathTurretMin);
			D.MatchTimeLimit = F(R, "MatchTimeLimit", D.MatchTimeLimit);
			D.EconomyMaxLevel = I(R, "EconomyMaxLevel", D.EconomyMaxLevel);
			D.EconomyBaseCost = I(R, "EconomyBaseCost", D.EconomyBaseCost);
			D.EconomyIncomeBonus = F(R, "EconomyIncomeBonus", D.EconomyIncomeBonus);
			D.HoldLineDistance = F(R, "HoldLineDistance", D.HoldLineDistance);
			D.RetreatSpeedFactor = F(R, "RetreatSpeedFactor", D.RetreatSpeedFactor);
			D.VeteranRank1Ratio = F(R, "VeteranRank1Ratio", D.VeteranRank1Ratio);
			D.VeteranRank2Ratio = F(R, "VeteranRank2Ratio", D.VeteranRank2Ratio);
			D.VeteranRank3Ratio = F(R, "VeteranRank3Ratio", D.VeteranRank3Ratio);
			D.VeteranHpBonus = F(R, "VeteranHpBonus", D.VeteranHpBonus);
			D.VeteranDamageBonus = F(R, "VeteranDamageBonus", D.VeteranDamageBonus);
			D.VeteranPromotionHeal = F(R, "VeteranPromotionHeal", D.VeteranPromotionHeal);
			D.ChampionBaseHealRadius = F(R, "ChampionBaseHealRadius", D.ChampionBaseHealRadius);
			D.ChampionGuardDistance = F(R, "ChampionGuardDistance", D.ChampionGuardDistance);
			D.DoctrineChoices = I(R, "DoctrineChoices", D.DoctrineChoices);
			D.LastStandBaseHpRatio = F(R, "LastStandBaseHpRatio", D.LastStandBaseHpRatio);
			D.LastStandMilitia = I(R, "LastStandMilitia", D.LastStandMilitia);
			D.LastStandBuffDuration = F(R, "LastStandBuffDuration", D.LastStandBuffDuration);
			D.LastStandDamageBonus = F(R, "LastStandDamageBonus", D.LastStandDamageBonus);
			D.LastStandAttackSpeedBonus = F(R, "LastStandAttackSpeedBonus", D.LastStandAttackSpeedBonus);
			D.LastStandTurretBonus = F(R, "LastStandTurretBonus", D.LastStandTurretBonus);
			D.LastStandTurretDuration = F(R, "LastStandTurretDuration", D.LastStandTurretDuration);
			D.LastStandRepair = F(R, "LastStandRepair", D.LastStandRepair);
		}

		// 伤害倍率矩阵
		Table = mj::Value();
		if (!LoadTable(DataDir + "/DamageMatrix.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::DamageType DT = cw::DamageType::Normal;
			if (!cw::ParseDamageType(S(Row, "Name"), DT))
			{
				Error = "DamageMatrix 行名无效: " + S(Row, "Name");
				return false;
			}
			for (int32_t A = 0; A < static_cast<int32_t>(cw::ArmorType::Count); ++A)
			{
				const char* ArmorName = cw::ToString(static_cast<cw::ArmorType>(A));
				Out.Rules.DamageMatrix[static_cast<int32_t>(DT)][A] = F(Row, ArmorName, 1.f);
			}
		}

		// 时代
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Ages.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::AgeDef D;
			D.Id = S(Row, "Name");
			D.DisplayName = S(Row, "DisplayName");
			D.Index = I(Row, "Index", 0);
			D.Implemented = B(Row, "Implemented", true);
			D.XpToEnter = I(Row, "XpToEnter", 0);
			D.GoldToEnter = I(Row, "GoldToEnter", 0);
			D.UpgradeDuration = F(Row, "UpgradeDuration", 0.f);
			D.BaseMaxHp = F(Row, "BaseMaxHp", 1000.f);
			D.IncomePerSec = F(Row, "IncomePerSec", 5.f);
			D.AiMelee = F(Row, "AiMelee", D.AiMelee);
			D.AiRanged = F(Row, "AiRanged", D.AiRanged);
			D.AiHeavy = F(Row, "AiHeavy", D.AiHeavy);
			D.VisualKey = S(Row, "VisualKey");
			Out.Ages.push_back(D);
		}

		// 兵种
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Units.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::UnitDef D;
			D.Id = S(Row, "Name");
			D.DisplayName = S(Row, "DisplayName");
			D.Age = I(Row, "Age", 0);
			D.MaxHp = F(Row, "MaxHp", D.MaxHp);
			D.Damage = F(Row, "Damage", D.Damage);
			D.AttackInterval = F(Row, "AttackInterval", D.AttackInterval);
			D.AttackWindup = F(Row, "AttackWindup", D.AttackWindup);
			D.Range = F(Row, "Range", D.Range);
			D.MoveSpeed = F(Row, "MoveSpeed", D.MoveSpeed);
			D.Radius = F(Row, "Radius", D.Radius);
			D.Cost = I(Row, "Cost", D.Cost);
			D.TrainTime = F(Row, "TrainTime", D.TrainTime);
			D.ProjectileSpeed = F(Row, "ProjectileSpeed", 0.f);
			D.SplashRadius = F(Row, "SplashRadius", 0.f);
			D.ChargeMultiplier = F(Row, "ChargeMultiplier", 1.f);
			D.StructureMultiplier = F(Row, "StructureMultiplier", 1.f);
			D.XpReward = I(Row, "XpReward", D.XpReward);
			D.VisualKey = S(Row, "VisualKey");
			if (!E(Row, "Role", D.Role, cw::ParseUnitRole, Error)
				|| !E(Row, "Targeting", D.Targeting, cw::ParseTargetRule, Error)
				|| !E(Row, "DamageType", D.DmgType, cw::ParseDamageType, Error)
				|| !E(Row, "ArmorType", D.Armor, cw::ParseArmorType, Error))
			{
				return false;
			}
			Out.Units.push_back(D);
		}

		// 炮塔
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Turrets.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::TurretDef D;
			D.Id = S(Row, "Name");
			D.DisplayName = S(Row, "DisplayName");
			D.Age = I(Row, "Age", 0);
			D.Cost = I(Row, "Cost", D.Cost);
			D.Range = F(Row, "Range", D.Range);
			D.Damage = F(Row, "Damage", D.Damage);
			D.AttackInterval = F(Row, "AttackInterval", D.AttackInterval);
			D.ProjectileSpeed = F(Row, "ProjectileSpeed", D.ProjectileSpeed);
			D.SplashRadius = F(Row, "SplashRadius", 0.f);
			D.MaxLevel = I(Row, "MaxLevel", D.MaxLevel);
			D.UpgradeCostRatio = F(Row, "UpgradeCostRatio", D.UpgradeCostRatio);
			D.DamagePerLevel = F(Row, "DamagePerLevel", D.DamagePerLevel);
			D.RangePerLevel = F(Row, "RangePerLevel", D.RangePerLevel);
			D.VisualKey = S(Row, "VisualKey");
			if (!E(Row, "DamageType", D.DmgType, cw::ParseDamageType, Error))
			{
				return false;
			}
			Out.Turrets.push_back(D);
		}

		// 技能
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Skills.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::SkillDef D;
			D.Id = S(Row, "Name");
			D.DisplayName = S(Row, "DisplayName");
			D.Age = I(Row, "Age", 0);
			D.Cost = I(Row, "Cost", 0);
			D.Cooldown = F(Row, "Cooldown", D.Cooldown);
			D.Delay = F(Row, "Delay", D.Delay);
			D.Radius = F(Row, "Radius", D.Radius);
			D.Damage = F(Row, "Damage", D.Damage);
			D.VisualKey = S(Row, "VisualKey");
			if (!E(Row, "DamageType", D.DmgType, cw::ParseDamageType, Error))
			{
				return false;
			}
			Out.Skills.push_back(D);
		}

		// 统帅（战斗属性追加到兵种列表末尾，顺序与游戏内加载一致）
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Champions.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::UnitDef U;
			U.Id = S(Row, "Name");
			U.DisplayName = S(Row, "DisplayName");
			U.Age = I(Row, "Age", 0);
			U.Role = cw::UnitRole::Heavy;
			U.MaxHp = F(Row, "MaxHp", U.MaxHp);
			U.Damage = F(Row, "Damage", U.Damage);
			U.AttackInterval = F(Row, "AttackInterval", U.AttackInterval);
			U.AttackWindup = F(Row, "AttackWindup", U.AttackWindup);
			U.Range = F(Row, "Range", U.Range);
			U.MoveSpeed = F(Row, "MoveSpeed", U.MoveSpeed);
			U.Radius = F(Row, "Radius", U.Radius);
			U.ProjectileSpeed = F(Row, "ProjectileSpeed", 0.f);
			U.SplashRadius = F(Row, "SplashRadius", 0.f);
			U.XpReward = I(Row, "XpReward", U.XpReward);
			U.VisualKey = S(Row, "VisualKey");
			if (!E(Row, "DamageType", U.DmgType, cw::ParseDamageType, Error) || !E(Row, "ArmorType", U.Armor, cw::ParseArmorType, Error))
			{
				return false;
			}
			cw::ChampionDef C;
			C.Id = U.Id;
			C.DisplayName = U.DisplayName;
			C.Age = U.Age;
			C.RespawnTime = F(Row, "RespawnTime", C.RespawnTime);
			C.Bounty = I(Row, "Bounty", C.Bounty);
			C.AuraRadius = F(Row, "AuraRadius", C.AuraRadius);
			C.AuraDamageBonus = F(Row, "AuraDamageBonus", C.AuraDamageBonus);
			C.AbilityName = S(Row, "AbilityName");
			C.AbilityCooldown = F(Row, "AbilityCooldown", C.AbilityCooldown);
			C.AbilityRadius = F(Row, "AbilityRadius", C.AbilityRadius);
			C.AbilityDuration = F(Row, "AbilityDuration", C.AbilityDuration);
			C.AbilityDamageBonus = F(Row, "AbilityDamageBonus", C.AbilityDamageBonus);
			C.AbilityAttackSpeedBonus = F(Row, "AbilityAttackSpeedBonus", C.AbilityAttackSpeedBonus);
			C.AbilityHeal = F(Row, "AbilityHeal", C.AbilityHeal);
			C.BaseRegen = F(Row, "BaseRegen", C.BaseRegen);
			// 统帅不能训练：造价只用于估算兵力价值与老兵晋升门槛
			U.Cost = std::max(C.Bounty * 3, 1);
			U.TrainTime = 1.f;
			Out.AppendChampion(U, C);
		}

		// 国策
		Table = mj::Value();
		if (!LoadTable(DataDir + "/Doctrines.json", Table, Error))
		{
			return false;
		}
		for (const mj::Value& Row : Table.Items)
		{
			cw::DoctrineDef D;
			D.Id = S(Row, "Name");
			D.DisplayName = S(Row, "DisplayName");
			D.MinAge = I(Row, "MinAge", 0);
			D.MaxAge = I(Row, "MaxAge", -1);
			D.UnitHpBonus = F(Row, "UnitHpBonus", 0.f);
			D.UnitDamageBonus = F(Row, "UnitDamageBonus", 0.f);
			D.UnitSpeedBonus = F(Row, "UnitSpeedBonus", 0.f);
			D.UnitRangeBonus = F(Row, "UnitRangeBonus", 0.f);
			D.UnitAttackSpeedBonus = F(Row, "UnitAttackSpeedBonus", 0.f);
			D.UnitCostBonus = F(Row, "UnitCostBonus", 0.f);
			D.UnitTrainTimeBonus = F(Row, "UnitTrainTimeBonus", 0.f);
			D.UnitStartRank = I(Row, "UnitStartRank", 0);
			D.IncomeBonus = F(Row, "IncomeBonus", 0.f);
			D.KillGoldBonus = F(Row, "KillGoldBonus", 0.f);
			D.XpBonus = F(Row, "XpBonus", 0.f);
			D.TurretDamageBonus = F(Row, "TurretDamageBonus", 0.f);
			D.TurretRangeBonus = F(Row, "TurretRangeBonus", 0.f);
			D.BaseHpBonus = F(Row, "BaseHpBonus", 0.f);
			D.SkillCooldownBonus = F(Row, "SkillCooldownBonus", 0.f);
			D.SkillDamageBonus = F(Row, "SkillDamageBonus", 0.f);
			D.StructureDamageBonus = F(Row, "StructureDamageBonus", 0.f);
			D.VeteranGainBonus = F(Row, "VeteranGainBonus", 0.f);
			D.ChampionHpBonus = F(Row, "ChampionHpBonus", 0.f);
			D.ChampionDamageBonus = F(Row, "ChampionDamageBonus", 0.f);
			D.ChampionCooldownBonus = F(Row, "ChampionCooldownBonus", 0.f);
			D.ChampionRespawnBonus = F(Row, "ChampionRespawnBonus", 0.f);
			D.AiWeight = F(Row, "AiWeight", 1.f);
			if (!E(Row, "Target", D.Target, cw::ParseDoctrineTarget, Error))
			{
				return false;
			}
			Out.Doctrines.push_back(D);
		}

		Error = Out.Validate();
		return Error.empty();
	}
}
