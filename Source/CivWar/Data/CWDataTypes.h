// 血战文明 - 数据表行结构
// 字段名与 Content/Data/*.json 一一对应；JSON 由 UDataTable::CreateTableFromJSONString 读取，
// 也可以在编辑器中以这些行结构把 JSON 导入为 DataTable 资源查看。
#pragma once

#include "CoreMinimal.h"
#include "Engine/DataTable.h"
#include "CWDataTypes.generated.h"

UENUM(BlueprintType)
enum class ECWDamageType : uint8
{
	Normal,
	Pierce,
	Siege,
	Energy,
};

UENUM(BlueprintType)
enum class ECWArmorType : uint8
{
	Light,
	Shielded,
	Heavy,
	Building,
};

UENUM(BlueprintType)
enum class ECWUnitRole : uint8
{
	Melee,
	Ranged,
	Heavy,
};

UENUM(BlueprintType)
enum class ECWTargetRule : uint8
{
	Nearest,
	LowestHp,
	PreferRanged,
	PreferHeavy,
	PreferStructure,
};

UENUM(BlueprintType)
enum class ECWDoctrineTarget : uint8
{
	None,
	All,
	Melee,
	Ranged,
	Heavy,
};

USTRUCT(BlueprintType)
struct FCWRulesRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LaneLength = 6000.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float BaseHalfWidth = 300.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 LaneRows = 3;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float RowSpacing = 85.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 StartGold = 200;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 QueueCapacity = 5;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float KillGoldRatio = 0.4f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TurretKillGoldFactor = 0.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LoserXpRatio = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float PassiveXpPerSec = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AllySpacingFactor = 0.8f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float DeathDuration = 1.6f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float RetargetInterval = 0.25f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TurretRetargetInterval = 0.2f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChargeRechargeTime = 1.2f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SplashSecondaryRatio = 0.6f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 InitialTurretSlots = 1;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 MaxTurretSlots = 3;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 TurretSlotCostBase = 150;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SellRefundRatio = 0.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SkillMinDistanceFromEnemyBase = 600.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TurretOffset = 120.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathTime = 660.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathBaseDamage = 2.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathRampPerMinute = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathMaxMultiplier = 5.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathIncomeMultiplier = 1.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathTurretDecayPerMinute = 0.12f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SuddenDeathTurretMin = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float MatchTimeLimit = 1500.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 EconomyMaxLevel = 3;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 EconomyBaseCost = 180;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float EconomyIncomeBonus = 0.2f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float HoldLineDistance = 1800.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float RetreatSpeedFactor = 0.8f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranRank1Ratio = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranRank2Ratio = 2.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranRank3Ratio = 5.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranHpBonus = 0.15f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranDamageBonus = 0.12f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranPromotionHeal = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionBaseHealRadius = 700.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionGuardDistance = 300.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 DoctrineChoices = 3;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandBaseHpRatio = 0.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 LastStandMilitia = 6;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandBuffDuration = 15.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandDamageBonus = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandAttackSpeedBonus = 0.25f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandTurretBonus = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandTurretDuration = 20.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float LastStandRepair = 0.2f;
};

// 行名 = 伤害类别（Normal/Pierce/Siege/Energy）
USTRUCT(BlueprintType)
struct FCWDamageMatrixRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Light = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Shielded = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Heavy = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Building = 1.f;
};

USTRUCT(BlueprintType)
struct FCWAgeRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Index = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) bool Implemented = true;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 XpToEnter = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 GoldToEnter = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UpgradeDuration = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float BaseMaxHp = 1500.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float IncomePerSec = 6.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AiMelee = 0.45f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AiRanged = 0.35f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AiHeavy = 0.2f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FName VisualKey;
};

USTRUCT(BlueprintType)
struct FCWUnitRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Description;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Age = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWUnitRole Role = ECWUnitRole::Melee;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float MaxHp = 100.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Damage = 10.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AttackInterval = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AttackWindup = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Range = 25.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float MoveSpeed = 170.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Radius = 40.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Cost = 20;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TrainTime = 2.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWTargetRule Targeting = ECWTargetRule::Nearest;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWDamageType DamageType = ECWDamageType::Normal;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWArmorType ArmorType = ECWArmorType::Light;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ProjectileSpeed = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SplashRadius = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChargeMultiplier = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float StructureMultiplier = 1.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 XpReward = 10;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FName VisualKey;
};

USTRUCT(BlueprintType)
struct FCWTurretRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Description;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Age = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Cost = 100;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Range = 800.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Damage = 20.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AttackInterval = 1.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ProjectileSpeed = 1800.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SplashRadius = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWDamageType DamageType = ECWDamageType::Pierce;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 MaxLevel = 3;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UpgradeCostRatio = 0.75f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float DamagePerLevel = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float RangePerLevel = 0.08f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FName VisualKey;
};

// 统帅：每个时代一行，战斗属性在加载时追加到兵种列表末尾
USTRUCT(BlueprintType)
struct FCWChampionRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Description;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Age = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float MaxHp = 600.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Damage = 24.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AttackInterval = 0.9f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AttackWindup = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Range = 35.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float MoveSpeed = 200.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Radius = 45.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWDamageType DamageType = ECWDamageType::Normal;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWArmorType ArmorType = ECWArmorType::Heavy;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ProjectileSpeed = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SplashRadius = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float RespawnTime = 20.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Bounty = 60;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 XpReward = 40;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AuraRadius = 450.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AuraDamageBonus = 0.15f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString AbilityName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString AbilityDescription;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityCooldown = 40.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityRadius = 600.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityDuration = 6.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityDamageBonus = 0.3f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityAttackSpeedBonus = 0.25f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AbilityHeal = 0.12f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float BaseRegen = 0.04f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FName VisualKey;
};

// 国策：加成为比例（0.2 = +20%），负数表示减少
USTRUCT(BlueprintType)
struct FCWDoctrineRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Description;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Category;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 MinAge = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 MaxAge = -1;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWDoctrineTarget Target = ECWDoctrineTarget::None;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitHpBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitDamageBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitSpeedBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitRangeBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitAttackSpeedBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitCostBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float UnitTrainTimeBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 UnitStartRank = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float IncomeBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float KillGoldBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float XpBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TurretDamageBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float TurretRangeBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float BaseHpBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SkillCooldownBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float SkillDamageBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float StructureDamageBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float VeteranGainBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionHpBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionDamageBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionCooldownBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float ChampionRespawnBonus = 0.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float AiWeight = 1.f;
};

USTRUCT(BlueprintType)
struct FCWSkillRow : public FTableRowBase
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString DisplayName;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FString Description;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Age = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) int32 Cost = 0;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Cooldown = 45.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Delay = 1.5f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Radius = 350.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) float Damage = 120.f;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) ECWDamageType DamageType = ECWDamageType::Siege;
	UPROPERTY(EditAnywhere, BlueprintReadOnly) FName VisualKey;
};
