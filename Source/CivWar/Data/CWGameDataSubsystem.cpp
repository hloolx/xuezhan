#include "Data/CWGameDataSubsystem.h"

#include "CivWar.h"
#include "Data/CWDataTypes.h"
#include "Engine/DataTable.h"
#include "Misc/Crc.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

// UE 枚举与规则核心枚举按相同顺序定义，可以直接转换
static_assert(static_cast<uint8>(ECWDamageType::Energy) == static_cast<uint8>(cw::DamageType::Energy), "DamageType 顺序不一致");
static_assert(static_cast<uint8>(ECWArmorType::Building) == static_cast<uint8>(cw::ArmorType::Building), "ArmorType 顺序不一致");
static_assert(static_cast<uint8>(ECWUnitRole::Heavy) == static_cast<uint8>(cw::UnitRole::Heavy), "UnitRole 顺序不一致");
static_assert(static_cast<uint8>(ECWTargetRule::PreferStructure) == static_cast<uint8>(cw::TargetRule::PreferStructure), "TargetRule 顺序不一致");
static_assert(static_cast<uint8>(ECWDoctrineTarget::Heavy) == static_cast<uint8>(cw::DoctrineTarget::Heavy), "DoctrineTarget 顺序不一致");

static std::string CWData_ToStd(const FString& S)
{
	return std::string(TCHAR_TO_UTF8(*S));
}

static FText CWData_ToText(const std::string& S)
{
	return FText::FromString(FString(UTF8_TO_TCHAR(S.c_str())));
}

void UCWGameDataSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	FString Error;
	bLoaded = LoadAll(Error);
	LoadError = Error;
	if (bLoaded)
	{
		UE_LOG(LogCivWar, Log, TEXT("数据加载完成：%d 个时代，%d 个兵种，%d 种炮塔，%d 个技能，校验值 %08x"),
			static_cast<int32>(Data.Ages.size()), static_cast<int32>(Data.Units.size()),
			static_cast<int32>(Data.Turrets.size()), static_cast<int32>(Data.Skills.size()), Checksum);
	}
	else
	{
		UE_LOG(LogCivWar, Error, TEXT("数据加载失败：%s"), *LoadError);
	}
}

FString UCWGameDataSubsystem::GetDataDirectory()
{
	return FPaths::ProjectContentDir() / TEXT("Data");
}

UDataTable* UCWGameDataSubsystem::LoadTable(const FString& FileName, UScriptStruct* RowStruct, FString& OutError)
{
	const FString Path = GetDataDirectory() / FileName;
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		OutError = FString::Printf(TEXT("无法读取数据文件 %s"), *Path);
		return nullptr;
	}
	// 校验值忽略换行符差异（不同机器的 git 换行设置可能不同）
	FString Normalized = Json;
	Normalized.ReplaceInline(TEXT("\r"), TEXT(""));
	Checksum = FCrc::StrCrc32(*Normalized, Checksum);

	UDataTable* Table = NewObject<UDataTable>(this, NAME_None, RF_Transient);
	Table->RowStruct = RowStruct;
	const TArray<FString> Problems = Table->CreateTableFromJSONString(Json);
	if (Problems.Num() > 0)
	{
		OutError = FString::Printf(TEXT("%s：%s"), *FileName, *FString::Join(Problems, TEXT("；")));
		return nullptr;
	}
	return Table;
}

bool UCWGameDataSubsystem::LoadAll(FString& OutError)
{
	Data = cw::GameData();
	Checksum = 0;
	RulesTable = LoadTable(TEXT("Rules.json"), FCWRulesRow::StaticStruct(), OutError);
	if (!RulesTable) return false;
	MatrixTable = LoadTable(TEXT("DamageMatrix.json"), FCWDamageMatrixRow::StaticStruct(), OutError);
	if (!MatrixTable) return false;
	AgeTable = LoadTable(TEXT("Ages.json"), FCWAgeRow::StaticStruct(), OutError);
	if (!AgeTable) return false;
	UnitTable = LoadTable(TEXT("Units.json"), FCWUnitRow::StaticStruct(), OutError);
	if (!UnitTable) return false;
	TurretTable = LoadTable(TEXT("Turrets.json"), FCWTurretRow::StaticStruct(), OutError);
	if (!TurretTable) return false;
	SkillTable = LoadTable(TEXT("Skills.json"), FCWSkillRow::StaticStruct(), OutError);
	if (!SkillTable) return false;
	ChampionTable = LoadTable(TEXT("Champions.json"), FCWChampionRow::StaticStruct(), OutError);
	if (!ChampionTable) return false;
	DoctrineTable = LoadTable(TEXT("Doctrines.json"), FCWDoctrineRow::StaticStruct(), OutError);
	if (!DoctrineTable) return false;

	// 全局规则
	const FCWRulesRow* RulesRow = RulesTable->FindRow<FCWRulesRow>(TEXT("Default"), TEXT("Rules"));
	if (!RulesRow)
	{
		OutError = TEXT("Rules.json 缺少 Default 行");
		return false;
	}
	cw::RulesDef& R = Data.Rules;
	R.LaneLength = RulesRow->LaneLength;
	R.BaseHalfWidth = RulesRow->BaseHalfWidth;
	R.LaneRows = RulesRow->LaneRows;
	R.RowSpacing = RulesRow->RowSpacing;
	R.StartGold = RulesRow->StartGold;
	R.QueueCapacity = RulesRow->QueueCapacity;
	R.KillGoldRatio = RulesRow->KillGoldRatio;
	R.TurretKillGoldFactor = RulesRow->TurretKillGoldFactor;
	R.LoserXpRatio = RulesRow->LoserXpRatio;
	R.PassiveXpPerSec = RulesRow->PassiveXpPerSec;
	R.AllySpacingFactor = RulesRow->AllySpacingFactor;
	R.DeathDuration = RulesRow->DeathDuration;
	R.RetargetInterval = RulesRow->RetargetInterval;
	R.TurretRetargetInterval = RulesRow->TurretRetargetInterval;
	R.ChargeRechargeTime = RulesRow->ChargeRechargeTime;
	R.SplashSecondaryRatio = RulesRow->SplashSecondaryRatio;
	R.InitialTurretSlots = RulesRow->InitialTurretSlots;
	R.MaxTurretSlots = RulesRow->MaxTurretSlots;
	R.TurretSlotCostBase = RulesRow->TurretSlotCostBase;
	R.SellRefundRatio = RulesRow->SellRefundRatio;
	R.SkillMinDistanceFromEnemyBase = RulesRow->SkillMinDistanceFromEnemyBase;
	R.TurretOffset = RulesRow->TurretOffset;
	R.SuddenDeathTime = RulesRow->SuddenDeathTime;
	R.SuddenDeathBaseDamage = RulesRow->SuddenDeathBaseDamage;
	R.SuddenDeathRampPerMinute = RulesRow->SuddenDeathRampPerMinute;
	R.SuddenDeathMaxMultiplier = RulesRow->SuddenDeathMaxMultiplier;
	R.SuddenDeathIncomeMultiplier = RulesRow->SuddenDeathIncomeMultiplier;
	R.SuddenDeathTurretDecayPerMinute = RulesRow->SuddenDeathTurretDecayPerMinute;
	R.SuddenDeathTurretMin = RulesRow->SuddenDeathTurretMin;
	R.MatchTimeLimit = RulesRow->MatchTimeLimit;
	R.EconomyMaxLevel = RulesRow->EconomyMaxLevel;
	R.EconomyBaseCost = RulesRow->EconomyBaseCost;
	R.EconomyIncomeBonus = RulesRow->EconomyIncomeBonus;
	R.HoldLineDistance = RulesRow->HoldLineDistance;
	R.RetreatSpeedFactor = RulesRow->RetreatSpeedFactor;
	R.VeteranRank1Ratio = RulesRow->VeteranRank1Ratio;
	R.VeteranRank2Ratio = RulesRow->VeteranRank2Ratio;
	R.VeteranRank3Ratio = RulesRow->VeteranRank3Ratio;
	R.VeteranHpBonus = RulesRow->VeteranHpBonus;
	R.VeteranDamageBonus = RulesRow->VeteranDamageBonus;
	R.VeteranPromotionHeal = RulesRow->VeteranPromotionHeal;
	R.ChampionBaseHealRadius = RulesRow->ChampionBaseHealRadius;
	R.ChampionGuardDistance = RulesRow->ChampionGuardDistance;
	R.DoctrineChoices = RulesRow->DoctrineChoices;
	R.LastStandBaseHpRatio = RulesRow->LastStandBaseHpRatio;
	R.LastStandMilitia = RulesRow->LastStandMilitia;
	R.LastStandBuffDuration = RulesRow->LastStandBuffDuration;
	R.LastStandDamageBonus = RulesRow->LastStandDamageBonus;
	R.LastStandAttackSpeedBonus = RulesRow->LastStandAttackSpeedBonus;
	R.LastStandTurretBonus = RulesRow->LastStandTurretBonus;
	R.LastStandTurretDuration = RulesRow->LastStandTurretDuration;
	R.LastStandRepair = RulesRow->LastStandRepair;

	// 伤害倍率矩阵：行名为伤害类别
	const UEnum* DamageEnum = StaticEnum<ECWDamageType>();
	for (const TPair<FName, uint8*>& Pair : MatrixTable->GetRowMap())
	{
		const int64 Value = DamageEnum->GetValueByNameString(Pair.Key.ToString());
		if (Value == INDEX_NONE || Value >= static_cast<int64>(cw::DamageType::Count))
		{
			OutError = FString::Printf(TEXT("DamageMatrix.json 行名无效：%s"), *Pair.Key.ToString());
			return false;
		}
		const FCWDamageMatrixRow* Row = reinterpret_cast<const FCWDamageMatrixRow*>(Pair.Value);
		float* Dst = R.DamageMatrix[Value];
		Dst[static_cast<int32>(cw::ArmorType::Light)] = Row->Light;
		Dst[static_cast<int32>(cw::ArmorType::Shielded)] = Row->Shielded;
		Dst[static_cast<int32>(cw::ArmorType::Heavy)] = Row->Heavy;
		Dst[static_cast<int32>(cw::ArmorType::Building)] = Row->Building;
	}

	// 时代
	for (const TPair<FName, uint8*>& Pair : AgeTable->GetRowMap())
	{
		const FCWAgeRow* Row = reinterpret_cast<const FCWAgeRow*>(Pair.Value);
		cw::AgeDef D;
		D.Id = CWData_ToStd(Pair.Key.ToString());
		D.DisplayName = CWData_ToStd(Row->DisplayName);
		D.Index = Row->Index;
		D.Implemented = Row->Implemented;
		D.XpToEnter = Row->XpToEnter;
		D.GoldToEnter = Row->GoldToEnter;
		D.UpgradeDuration = Row->UpgradeDuration;
		D.BaseMaxHp = Row->BaseMaxHp;
		D.IncomePerSec = Row->IncomePerSec;
		D.AiMelee = Row->AiMelee;
		D.AiRanged = Row->AiRanged;
		D.AiHeavy = Row->AiHeavy;
		D.VisualKey = CWData_ToStd(Row->VisualKey.ToString());
		Data.Ages.push_back(D);
	}

	// 兵种（顺序即网络同步使用的兵种编号，所有客户端读取同一份文件）
	for (const TPair<FName, uint8*>& Pair : UnitTable->GetRowMap())
	{
		const FCWUnitRow* Row = reinterpret_cast<const FCWUnitRow*>(Pair.Value);
		cw::UnitDef D;
		D.Id = CWData_ToStd(Pair.Key.ToString());
		D.DisplayName = CWData_ToStd(Row->DisplayName);
		D.Age = Row->Age;
		D.Role = static_cast<cw::UnitRole>(Row->Role);
		D.MaxHp = Row->MaxHp;
		D.Damage = Row->Damage;
		D.AttackInterval = Row->AttackInterval;
		D.AttackWindup = Row->AttackWindup;
		D.Range = Row->Range;
		D.MoveSpeed = Row->MoveSpeed;
		D.Radius = Row->Radius;
		D.Cost = Row->Cost;
		D.TrainTime = Row->TrainTime;
		D.Targeting = static_cast<cw::TargetRule>(Row->Targeting);
		D.DmgType = static_cast<cw::DamageType>(Row->DamageType);
		D.Armor = static_cast<cw::ArmorType>(Row->ArmorType);
		D.ProjectileSpeed = Row->ProjectileSpeed;
		D.SplashRadius = Row->SplashRadius;
		D.ChargeMultiplier = Row->ChargeMultiplier;
		D.StructureMultiplier = Row->StructureMultiplier;
		D.XpReward = Row->XpReward;
		D.VisualKey = CWData_ToStd(Row->VisualKey.ToString());
		Data.Units.push_back(D);
		UnitDescriptions.Add(Row->Description);
		UnitVisualKeys.Add(Row->VisualKey);
	}

	// 炮塔
	for (const TPair<FName, uint8*>& Pair : TurretTable->GetRowMap())
	{
		const FCWTurretRow* Row = reinterpret_cast<const FCWTurretRow*>(Pair.Value);
		cw::TurretDef D;
		D.Id = CWData_ToStd(Pair.Key.ToString());
		D.DisplayName = CWData_ToStd(Row->DisplayName);
		D.Age = Row->Age;
		D.Cost = Row->Cost;
		D.Range = Row->Range;
		D.Damage = Row->Damage;
		D.AttackInterval = Row->AttackInterval;
		D.ProjectileSpeed = Row->ProjectileSpeed;
		D.SplashRadius = Row->SplashRadius;
		D.DmgType = static_cast<cw::DamageType>(Row->DamageType);
		D.MaxLevel = Row->MaxLevel;
		D.UpgradeCostRatio = Row->UpgradeCostRatio;
		D.DamagePerLevel = Row->DamagePerLevel;
		D.RangePerLevel = Row->RangePerLevel;
		D.VisualKey = CWData_ToStd(Row->VisualKey.ToString());
		Data.Turrets.push_back(D);
		TurretDescriptions.Add(Row->Description);
		TurretVisualKeys.Add(Row->VisualKey);
	}

	// 技能
	for (const TPair<FName, uint8*>& Pair : SkillTable->GetRowMap())
	{
		const FCWSkillRow* Row = reinterpret_cast<const FCWSkillRow*>(Pair.Value);
		cw::SkillDef D;
		D.Id = CWData_ToStd(Pair.Key.ToString());
		D.DisplayName = CWData_ToStd(Row->DisplayName);
		D.Age = Row->Age;
		D.Cost = Row->Cost;
		D.Cooldown = Row->Cooldown;
		D.Delay = Row->Delay;
		D.Radius = Row->Radius;
		D.Damage = Row->Damage;
		D.DmgType = static_cast<cw::DamageType>(Row->DamageType);
		D.VisualKey = CWData_ToStd(Row->VisualKey.ToString());
		Data.Skills.push_back(D);
		SkillDescriptions.Add(Row->Description);
	}

	// 统帅：战斗属性追加到兵种列表末尾（顺序与独立测试程序一致，网络同步使用同一编号）
	for (const TPair<FName, uint8*>& Pair : ChampionTable->GetRowMap())
	{
		const FCWChampionRow* Row = reinterpret_cast<const FCWChampionRow*>(Pair.Value);
		cw::UnitDef U;
		U.Id = CWData_ToStd(Pair.Key.ToString());
		U.DisplayName = CWData_ToStd(Row->DisplayName);
		U.Age = Row->Age;
		U.Role = cw::UnitRole::Heavy;
		U.MaxHp = Row->MaxHp;
		U.Damage = Row->Damage;
		U.AttackInterval = Row->AttackInterval;
		U.AttackWindup = Row->AttackWindup;
		U.Range = Row->Range;
		U.MoveSpeed = Row->MoveSpeed;
		U.Radius = Row->Radius;
		U.DmgType = static_cast<cw::DamageType>(Row->DamageType);
		U.Armor = static_cast<cw::ArmorType>(Row->ArmorType);
		U.ProjectileSpeed = Row->ProjectileSpeed;
		U.SplashRadius = Row->SplashRadius;
		U.XpReward = Row->XpReward;
		U.VisualKey = CWData_ToStd(Row->VisualKey.ToString());
		U.Cost = FMath::Max(Row->Bounty * 3, 1); // 统帅不能训练：造价只用于估算兵力价值
		U.TrainTime = 1.f;
		cw::ChampionDef C;
		C.Id = U.Id;
		C.DisplayName = U.DisplayName;
		C.Age = Row->Age;
		C.RespawnTime = Row->RespawnTime;
		C.Bounty = Row->Bounty;
		C.AuraRadius = Row->AuraRadius;
		C.AuraDamageBonus = Row->AuraDamageBonus;
		C.AbilityName = CWData_ToStd(Row->AbilityName);
		C.AbilityCooldown = Row->AbilityCooldown;
		C.AbilityRadius = Row->AbilityRadius;
		C.AbilityDuration = Row->AbilityDuration;
		C.AbilityDamageBonus = Row->AbilityDamageBonus;
		C.AbilityAttackSpeedBonus = Row->AbilityAttackSpeedBonus;
		C.AbilityHeal = Row->AbilityHeal;
		C.BaseRegen = Row->BaseRegen;
		Data.AppendChampion(U, C);
		UnitDescriptions.Add(Row->Description);
		UnitVisualKeys.Add(Row->VisualKey);
		ChampionDescriptions.Add(Row->Description);
		ChampionAbilityNames.Add(Row->AbilityName);
		ChampionAbilityDescriptions.Add(Row->AbilityDescription);
	}

	// 国策
	for (const TPair<FName, uint8*>& Pair : DoctrineTable->GetRowMap())
	{
		const FCWDoctrineRow* Row = reinterpret_cast<const FCWDoctrineRow*>(Pair.Value);
		cw::DoctrineDef D;
		D.Id = CWData_ToStd(Pair.Key.ToString());
		D.DisplayName = CWData_ToStd(Row->DisplayName);
		D.MinAge = Row->MinAge;
		D.MaxAge = Row->MaxAge;
		D.Target = static_cast<cw::DoctrineTarget>(Row->Target);
		D.UnitHpBonus = Row->UnitHpBonus;
		D.UnitDamageBonus = Row->UnitDamageBonus;
		D.UnitSpeedBonus = Row->UnitSpeedBonus;
		D.UnitRangeBonus = Row->UnitRangeBonus;
		D.UnitAttackSpeedBonus = Row->UnitAttackSpeedBonus;
		D.UnitCostBonus = Row->UnitCostBonus;
		D.UnitTrainTimeBonus = Row->UnitTrainTimeBonus;
		D.UnitStartRank = Row->UnitStartRank;
		D.IncomeBonus = Row->IncomeBonus;
		D.KillGoldBonus = Row->KillGoldBonus;
		D.XpBonus = Row->XpBonus;
		D.TurretDamageBonus = Row->TurretDamageBonus;
		D.TurretRangeBonus = Row->TurretRangeBonus;
		D.BaseHpBonus = Row->BaseHpBonus;
		D.SkillCooldownBonus = Row->SkillCooldownBonus;
		D.SkillDamageBonus = Row->SkillDamageBonus;
		D.StructureDamageBonus = Row->StructureDamageBonus;
		D.VeteranGainBonus = Row->VeteranGainBonus;
		D.ChampionHpBonus = Row->ChampionHpBonus;
		D.ChampionDamageBonus = Row->ChampionDamageBonus;
		D.ChampionCooldownBonus = Row->ChampionCooldownBonus;
		D.ChampionRespawnBonus = Row->ChampionRespawnBonus;
		D.AiWeight = Row->AiWeight;
		Data.Doctrines.push_back(D);
		DoctrineDescriptions.Add(Row->Description);
		DoctrineCategories.Add(Row->Category);
	}

	const std::string Problem = Data.Validate();
	if (!Problem.empty())
	{
		OutError = FString(UTF8_TO_TCHAR(Problem.c_str()));
		return false;
	}
	return true;
}

FText UCWGameDataSubsystem::GetUnitName(int32 UnitIndex) const
{
	return Data.Units.size() > static_cast<size_t>(UnitIndex) && UnitIndex >= 0 ? CWData_ToText(Data.Units[UnitIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetUnitDescription(int32 UnitIndex) const
{
	return UnitDescriptions.IsValidIndex(UnitIndex) ? FText::FromString(UnitDescriptions[UnitIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetAgeName(int32 AgeIndex) const
{
	return Data.Ages.size() > static_cast<size_t>(AgeIndex) && AgeIndex >= 0 ? CWData_ToText(Data.Ages[AgeIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetTurretName(int32 TurretIndex) const
{
	return Data.Turrets.size() > static_cast<size_t>(TurretIndex) && TurretIndex >= 0 ? CWData_ToText(Data.Turrets[TurretIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetTurretDescription(int32 TurretIndex) const
{
	return TurretDescriptions.IsValidIndex(TurretIndex) ? FText::FromString(TurretDescriptions[TurretIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetSkillName(int32 SkillIndex) const
{
	return Data.Skills.size() > static_cast<size_t>(SkillIndex) && SkillIndex >= 0 ? CWData_ToText(Data.Skills[SkillIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetSkillDescription(int32 SkillIndex) const
{
	return SkillDescriptions.IsValidIndex(SkillIndex) ? FText::FromString(SkillDescriptions[SkillIndex]) : FText::GetEmpty();
}

FName UCWGameDataSubsystem::GetUnitVisualKey(int32 UnitIndex) const
{
	return UnitVisualKeys.IsValidIndex(UnitIndex) ? UnitVisualKeys[UnitIndex] : NAME_None;
}

FName UCWGameDataSubsystem::GetTurretVisualKey(int32 TurretIndex) const
{
	return TurretVisualKeys.IsValidIndex(TurretIndex) ? TurretVisualKeys[TurretIndex] : NAME_None;
}

FText UCWGameDataSubsystem::GetChampionName(int32 ChampionIndex) const
{
	return ChampionIndex >= 0 && Data.Champions.size() > static_cast<size_t>(ChampionIndex) ? CWData_ToText(Data.Champions[ChampionIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetChampionDescription(int32 ChampionIndex) const
{
	return ChampionDescriptions.IsValidIndex(ChampionIndex) ? FText::FromString(ChampionDescriptions[ChampionIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetChampionAbilityName(int32 ChampionIndex) const
{
	return ChampionAbilityNames.IsValidIndex(ChampionIndex) ? FText::FromString(ChampionAbilityNames[ChampionIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetChampionAbilityDescription(int32 ChampionIndex) const
{
	return ChampionAbilityDescriptions.IsValidIndex(ChampionIndex) ? FText::FromString(ChampionAbilityDescriptions[ChampionIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetDoctrineName(int32 DoctrineIndex) const
{
	return DoctrineIndex >= 0 && Data.Doctrines.size() > static_cast<size_t>(DoctrineIndex) ? CWData_ToText(Data.Doctrines[DoctrineIndex].DisplayName) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetDoctrineDescription(int32 DoctrineIndex) const
{
	return DoctrineDescriptions.IsValidIndex(DoctrineIndex) ? FText::FromString(DoctrineDescriptions[DoctrineIndex]) : FText::GetEmpty();
}

FText UCWGameDataSubsystem::GetDoctrineCategory(int32 DoctrineIndex) const
{
	return DoctrineCategories.IsValidIndex(DoctrineIndex) ? FText::FromString(DoctrineCategories[DoctrineIndex]) : FText::GetEmpty();
}
