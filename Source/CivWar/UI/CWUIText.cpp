#include "UI/CWUIText.h"

#include "Sim/SimState.h"

#define LOCTEXT_NAMESPACE "CivWarUI"

namespace CWUIText
{
	FText FromUtf8(const std::string& S)
	{
		return FText::FromString(FString(UTF8_TO_TCHAR(S.c_str())));
	}

	FText CommandResult(uint8 Result)
	{
		if (Result == 255)
		{
			return LOCTEXT("RateLimited", "操作过于频繁");
		}
		switch (static_cast<cw::CommandResult>(Result))
		{
		case cw::CommandResult::Ok: return FText::GetEmpty();
		case cw::CommandResult::MatchNotRunning: return LOCTEXT("NotRunning", "对局未在进行");
		case cw::CommandResult::InvalidTeam: return LOCTEXT("InvalidTeam", "你不控制任何阵营");
		case cw::CommandResult::InvalidParam: return LOCTEXT("InvalidParam", "无效操作");
		case cw::CommandResult::NotEnoughGold: return LOCTEXT("NoGold", "金币不足");
		case cw::CommandResult::NotEnoughXp: return LOCTEXT("NoXp", "经验不足");
		case cw::CommandResult::QueueFull: return LOCTEXT("QueueFull", "训练队列已满");
		case cw::CommandResult::LockedByAge: return LOCTEXT("LockedByAge", "需要更高时代");
		case cw::CommandResult::AgeMax: return LOCTEXT("AgeMax", "已是最高时代");
		case cw::CommandResult::AgeNotImplemented: return LOCTEXT("AgeNotImpl", "下一时代尚未实装");
		case cw::CommandResult::Upgrading: return LOCTEXT("Upgrading", "正在升级时代");
		case cw::CommandResult::SlotLocked: return LOCTEXT("SlotLocked", "炮塔槽位未解锁");
		case cw::CommandResult::SlotOccupied: return LOCTEXT("SlotOccupied", "该槽位已有炮塔");
		case cw::CommandResult::SlotEmpty: return LOCTEXT("SlotEmpty", "该槽位没有炮塔");
		case cw::CommandResult::NoMoreSlots: return LOCTEXT("NoMoreSlots", "炮塔槽位已达上限");
		case cw::CommandResult::MaxLevel: return LOCTEXT("MaxLevel", "炮塔已满级");
		case cw::CommandResult::OnCooldown: return LOCTEXT("OnCooldown", "技能冷却中");
		case cw::CommandResult::BadTarget: return LOCTEXT("BadTarget", "无效落点：不能贴近敌方基地");
		case cw::CommandResult::NoOffer: return LOCTEXT("NoOffer", "当前没有可选的国策");
		case cw::CommandResult::ChampionDead: return LOCTEXT("ChampionDead", "统帅阵亡中，复活后才能下令");
		case cw::CommandResult::NoChampion: return LOCTEXT("NoChampion", "本局没有统帅");
		case cw::CommandResult::Unavailable: return LOCTEXT("Unavailable", "基地生命降到一半以下才能背水一战");
		case cw::CommandResult::AlreadyUsed: return LOCTEXT("AlreadyUsed", "背水一战每局只能发动一次");
		default: return LOCTEXT("Unknown", "操作失败");
		}
	}

	FText RoleName(cw::UnitRole Role)
	{
		switch (Role)
		{
		case cw::UnitRole::Melee: return LOCTEXT("Melee", "近战");
		case cw::UnitRole::Ranged: return LOCTEXT("Ranged", "远程");
		case cw::UnitRole::Heavy: return LOCTEXT("Heavy", "重型");
		default: return FText::GetEmpty();
		}
	}

	FText DamageTypeName(cw::DamageType Type)
	{
		switch (Type)
		{
		case cw::DamageType::Normal: return LOCTEXT("DmgNormal", "普通");
		case cw::DamageType::Pierce: return LOCTEXT("DmgPierce", "穿刺");
		case cw::DamageType::Siege: return LOCTEXT("DmgSiege", "攻城");
		case cw::DamageType::Energy: return LOCTEXT("DmgEnergy", "能量");
		default: return FText::GetEmpty();
		}
	}

	FText ArmorName(cw::ArmorType Armor)
	{
		switch (Armor)
		{
		case cw::ArmorType::Light: return LOCTEXT("ArmorLight", "轻甲");
		case cw::ArmorType::Shielded: return LOCTEXT("ArmorShield", "持盾");
		case cw::ArmorType::Heavy: return LOCTEXT("ArmorHeavy", "重甲");
		case cw::ArmorType::Building: return LOCTEXT("ArmorBuilding", "建筑");
		default: return FText::GetEmpty();
		}
	}

	FText TargetRuleName(cw::TargetRule Rule)
	{
		switch (Rule)
		{
		case cw::TargetRule::Nearest: return LOCTEXT("RuleNearest", "最近目标");
		case cw::TargetRule::LowestHp: return LOCTEXT("RuleLowHp", "残血优先");
		case cw::TargetRule::PreferRanged: return LOCTEXT("RuleRanged", "远程优先");
		case cw::TargetRule::PreferHeavy: return LOCTEXT("RuleHeavy", "重型优先");
		case cw::TargetRule::PreferStructure: return LOCTEXT("RuleStructure", "基地优先");
		default: return FText::GetEmpty();
		}
	}

	FText UnitTooltip(const cw::UnitDef& D, const FText& Description)
	{
		FString Extra;
		if (D.ChargeMultiplier > 1.f)
		{
			Extra += FString::Printf(TEXT("\n冲锋：行军后首击 ×%.1f"), D.ChargeMultiplier);
		}
		if (D.StructureMultiplier != 1.f)
		{
			Extra += FString::Printf(TEXT("\n对基地伤害 ×%.1f"), D.StructureMultiplier);
		}
		if (D.SplashRadius > 0.f)
		{
			Extra += FString::Printf(TEXT("\n范围伤害 %.0f"), D.SplashRadius);
		}
		return FText::FromString(FString::Printf(
			TEXT("%s · %s\n%s\n\n生命 %.0f    攻击 %.0f / %.1f秒\n射程 %.0f    速度 %.0f\n伤害 %s    防御 %s\n目标 %s    训练 %.1f秒%s"),
			*FromUtf8(D.DisplayName).ToString(), *RoleName(D.Role).ToString(), *Description.ToString(),
			D.MaxHp, D.Damage, D.AttackInterval, D.Range, D.MoveSpeed,
			*DamageTypeName(D.DmgType).ToString(), *ArmorName(D.Armor).ToString(), *TargetRuleName(D.Targeting).ToString(),
			D.TrainTime, *Extra));
	}

	FText TurretTooltip(const cw::TurretDef& D, const FText& Description, int32 Level)
	{
		const int32 L = FMath::Max(Level, 1);
		const float Damage = D.Damage * (1.f + D.DamagePerLevel * (L - 1));
		const float Range = D.Range * (1.f + D.RangePerLevel * (L - 1));
		return FText::FromString(FString::Printf(TEXT("%s  %d 级\n%s\n\n伤害 %.0f（%s）  间隔 %.2f秒\n射程 %.0f%s"),
			*FromUtf8(D.DisplayName).ToString(), L, *Description.ToString(), Damage, *DamageTypeName(D.DmgType).ToString(),
			D.AttackInterval, Range, D.SplashRadius > 0.f ? *FString::Printf(TEXT("  范围 %.0f"), D.SplashRadius) : TEXT("")));
	}

	FText Clock(float Seconds)
	{
		const int32 Total = FMath::Max(0, FMath::FloorToInt(Seconds));
		return FText::FromString(FString::Printf(TEXT("%02d:%02d"), Total / 60, Total % 60));
	}
}

#undef LOCTEXT_NAMESPACE
