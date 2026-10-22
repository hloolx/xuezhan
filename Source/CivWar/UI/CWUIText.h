// 血战文明 - 界面文案（中文，简洁）
#pragma once

#include "CoreMinimal.h"
#include "Sim/SimTypes.h"

namespace CWUIText
{
	// 服务器拒绝指令的原因（255 = 操作过于频繁）
	FText CommandResult(uint8 Result);
	FText RoleName(cw::UnitRole Role);
	FText DamageTypeName(cw::DamageType Type);
	FText ArmorName(cw::ArmorType Armor);
	FText TargetRuleName(cw::TargetRule Rule);
	FText UnitTooltip(const cw::UnitDef& D, const FText& Description);
	FText TurretTooltip(const cw::TurretDef& D, const FText& Description, int32 Level);
	FText Clock(float Seconds);
	FText FromUtf8(const std::string& S);
}
