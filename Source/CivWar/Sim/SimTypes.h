// 血战文明 - 规则核心：静态数据定义
// 本目录（Sim/）不依赖 Unreal Engine，可以同时编译进游戏模块和独立测试程序。
// 约束：不使用异常、RTTI；避免变量遮蔽；所有数值来自数据表，不在代码中写死。
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace cw
{
	constexpr int32_t TeamCount = 2;
	constexpr int32_t InvalidIndex = -1;
	constexpr int32_t MaxLaneRows = 8;

	// 伤害类别
	enum class DamageType : uint8_t
	{
		Normal = 0, // 近战劈砍/钝击
		Pierce,     // 投射物：石弹、弩箭、子弹
		Siege,      // 攻城/爆炸：对建筑、重甲有效
		Energy,     // 未来科技（未实装时代预留）
		Count
	};

	// 防御类别
	enum class ArmorType : uint8_t
	{
		Light = 0, // 轻甲步兵
		Shielded,  // 持盾：克制远程
		Heavy,     // 重甲/坐骑/载具
		Building,  // 基地
		Count
	};

	// 兵种定位
	enum class UnitRole : uint8_t
	{
		Melee = 0,
		Ranged,
		Heavy,
		Count
	};

	// 目标选择规则（在射程内的候选目标中选择）
	enum class TargetRule : uint8_t
	{
		Nearest = 0,     // 最近的敌人（默认）
		LowestHp,        // 剩余生命最低的敌人（补刀）
		PreferRanged,    // 优先远程单位（越过前排点射）
		PreferHeavy,     // 优先重型单位（反装甲）
		PreferStructure, // 优先基地（攻城）
		Count
	};

	// 国策作用对象
	enum class DoctrineTarget : uint8_t
	{
		None = 0, // 只有全局效果（经济、炮塔、技能、统帅……）
		All,      // 全部兵种
		Melee,
		Ranged,
		Heavy,
		Count
	};

	struct UnitDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t Age = 0; // 0 起始：0=石器 1=中世纪 2=工业 3=现代 4=未来
		bool IsChampion = false; // 统帅的战斗属性：不出现在训练面板
		UnitRole Role = UnitRole::Melee;
		float MaxHp = 100.f;
		float Damage = 10.f;
		float AttackInterval = 1.f; // 两次攻击开始之间的间隔（秒）
		float AttackWindup = 0.3f;  // 攻击开始到命中/出手的前摇（秒），表现层据此对齐动画
		float Range = 20.f;         // 边缘距离（厘米），近战约 15~30
		float MoveSpeed = 200.f;    // 厘米/秒
		float Radius = 40.f;        // 碰撞半径（厘米）
		int32_t Cost = 15;
		float TrainTime = 1.5f;
		TargetRule Targeting = TargetRule::Nearest;
		DamageType DmgType = DamageType::Normal;
		ArmorType Armor = ArmorType::Light;
		float ProjectileSpeed = 0.f;   // 0 = 近战立即结算；>0 = 发射投射物
		float SplashRadius = 0.f;      // >0 = 范围伤害（以命中点为中心）
		float ChargeMultiplier = 1.f;  // >1 = 冲锋：行军后的第一次攻击伤害倍率
		float StructureMultiplier = 1.f; // 对建筑额外倍率（工兵爆破等）
		int32_t XpReward = 10;         // 击杀者获得的经验
		std::string VisualKey;         // 表现层使用的模型键
	};

	struct AgeDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t Index = 0;
		bool Implemented = true;     // false = 规划中，界面显示“未实装”，规则层拒绝升级
		int32_t XpToEnter = 0;       // 升级进入本时代需要的经验
		int32_t GoldToEnter = 0;     // 升级进入本时代需要的金币
		float UpgradeDuration = 3.f; // 升级过程时长（秒），期间播放建筑变化
		float BaseMaxHp = 1500.f;
		float IncomePerSec = 5.f;    // 本时代的基础金币收入
		// AI 在本时代的兵种配比倾向（普通/困难难度使用；可依据 SimHarness --balance 的对抗矩阵调整）
		float AiMelee = 0.45f;
		float AiRanged = 0.35f;
		float AiHeavy = 0.2f;
		std::string VisualKey;
	};

	struct TurretDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t Age = 0;
		int32_t Cost = 100;
		float Range = 900.f;
		float Damage = 20.f;
		float AttackInterval = 1.5f;
		float ProjectileSpeed = 1800.f;
		float SplashRadius = 0.f;
		DamageType DmgType = DamageType::Pierce;
		int32_t MaxLevel = 3;
		float UpgradeCostRatio = 0.6f;   // 每级升级费用 = Cost * 比例 * 当前等级
		float DamagePerLevel = 0.35f;    // 每级伤害加成
		float RangePerLevel = 0.08f;     // 每级射程加成
		std::string VisualKey;
	};

	struct SkillDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t Age = 0;
		int32_t Cost = 0;
		float Cooldown = 45.f;
		float Delay = 1.5f;  // 预警时长：圈出现到伤害结算
		float Radius = 350.f;
		float Damage = 120.f;
		DamageType DmgType = DamageType::Siege;
		std::string VisualKey;
	};

	// 统帅：每方一名，随时代进化；玩家指挥站位并施放“战吼”
	struct ChampionDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t Age = 0;
		int32_t UnitDefIndex = InvalidIndex; // 战斗属性在 GameData::Units 中的下标
		float RespawnTime = 20.f;            // 阵亡后复活时间（秒）
		int32_t Bounty = 60;                 // 击杀方获得的金币
		float AuraRadius = 450.f;            // 光环：范围内友军伤害提高
		float AuraDamageBonus = 0.15f;
		std::string AbilityName;
		float AbilityCooldown = 40.f;
		float AbilityRadius = 600.f;
		float AbilityDuration = 6.f;
		float AbilityDamageBonus = 0.3f;
		float AbilityAttackSpeedBonus = 0.25f;
		float AbilityHeal = 0.12f;           // 立即恢复范围内友军（含统帅）最大生命的比例
		float BaseRegen = 0.04f;             // 位于己方城门附近时，每秒恢复最大生命的比例
	};

	// 国策：开局与每次进入新时代时三选一，效果永久叠加
	struct DoctrineDef
	{
		std::string Id;
		std::string DisplayName;
		int32_t MinAge = 0;
		int32_t MaxAge = -1; // -1 = 不限
		DoctrineTarget Target = DoctrineTarget::None;
		// 作用于 Target 兵种（加成为比例，负数表示减少）
		float UnitHpBonus = 0.f;
		float UnitDamageBonus = 0.f;
		float UnitSpeedBonus = 0.f;
		float UnitRangeBonus = 0.f;
		float UnitAttackSpeedBonus = 0.f;
		float UnitCostBonus = 0.f;
		float UnitTrainTimeBonus = 0.f;
		int32_t UnitStartRank = 0;
		// 全局
		float IncomeBonus = 0.f;
		float KillGoldBonus = 0.f;
		float XpBonus = 0.f;
		float TurretDamageBonus = 0.f;
		float TurretRangeBonus = 0.f;
		float BaseHpBonus = 0.f;
		float SkillCooldownBonus = 0.f;
		float SkillDamageBonus = 0.f;
		float StructureDamageBonus = 0.f;
		float VeteranGainBonus = 0.f;
		float ChampionHpBonus = 0.f;
		float ChampionDamageBonus = 0.f;
		float ChampionCooldownBonus = 0.f;
		float ChampionRespawnBonus = 0.f;
		float AiWeight = 1.f; // AI 选择倾向
	};

	// 已选国策的累计效果（同类加成按加法叠加）；兵种类数组按 UnitRole 下标
	struct DoctrineEffects
	{
		float Hp[3] = { 0.f, 0.f, 0.f };
		float Damage[3] = { 0.f, 0.f, 0.f };
		float Speed[3] = { 0.f, 0.f, 0.f };
		float Range[3] = { 0.f, 0.f, 0.f };
		float AttackSpeed[3] = { 0.f, 0.f, 0.f };
		float Cost[3] = { 0.f, 0.f, 0.f };
		float TrainTime[3] = { 0.f, 0.f, 0.f };
		int32_t StartRank[3] = { 0, 0, 0 };
		float Income = 0.f;
		float KillGold = 0.f;
		float Xp = 0.f;
		float TurretDamage = 0.f;
		float TurretRange = 0.f;
		float BaseHp = 0.f;
		float SkillCooldown = 0.f;
		float SkillDamage = 0.f;
		float StructureDamage = 0.f;
		float VeteranGain = 0.f;
		float ChampionHp = 0.f;
		float ChampionDamage = 0.f;
		float ChampionCooldown = 0.f;
		float ChampionRespawn = 0.f;
	};

	// 全局规则（单行数据表）
	struct RulesDef
	{
		float LaneLength = 6000.f;        // 两座基地中心的距离（厘米）
		float BaseHalfWidth = 300.f;      // 基地中心到城门（前沿）的距离；时代升级不改变，避免与敌军重叠
		// 队列宽度：同一条战线上并列的行数。友军只在同一行内互相阻挡；敌方前沿对所有行生效（不能穿越敌军）
		int32_t LaneRows = 3;
		float RowSpacing = 85.f;          // 表现层：行与行之间的横向间距（厘米），不参与规则判定
		int32_t StartGold = 175;
		int32_t QueueCapacity = 5;
		float KillGoldRatio = 0.5f;       // 击杀金币 = 造价 * 比例
		float TurretKillGoldFactor = 0.5f; // 炮塔击杀只获得上述金币的一部分，避免防守方滚雪球
		float LoserXpRatio = 0.25f;       // 单位阵亡时，阵亡方获得的经验 = XpReward * 比例
		float PassiveXpPerSec = 1.f;
		float AllySpacingFactor = 0.8f;   // 友军最小间距 = (r1 + r2) * 系数
		float DeathDuration = 1.6f;       // 死亡表现时长，期间不可选中、不阻挡
		float RetargetInterval = 0.25f;   // 周期性重新索敌间隔
		float ChargeRechargeTime = 1.2f;  // 连续行军多久后冲锋重新就绪
		float SplashSecondaryRatio = 0.6f; // 范围伤害对非主目标的伤害比例
		float TurretRetargetInterval = 0.2f;
		int32_t InitialTurretSlots = 1;
		int32_t MaxTurretSlots = 3;
		int32_t TurretSlotCostBase = 120; // 第 n 个额外槽位费用 = Base * n
		float SellRefundRatio = 0.5f;
		float SkillMinDistanceFromEnemyBase = 600.f; // 技能落点不能贴近敌方基地（防止技能偷家）
		float TurretOffset = 120.f;       // 炮塔相对基地前沿向内的距离
		// 决战阶段：到时后基地承受伤害逐步提高、收入提高，保证对局收敛（界面会明确提示）
		float SuddenDeathTime = 720.f;
		float SuddenDeathBaseDamage = 1.5f;
		float SuddenDeathRampPerMinute = 0.5f;
		float SuddenDeathMaxMultiplier = 5.f;
		float SuddenDeathIncomeMultiplier = 1.5f;
		float SuddenDeathTurretDecayPerMinute = 0.12f; // 决战阶段炮塔伤害每分钟下降比例
		float SuddenDeathTurretMin = 0.3f;              // 炮塔伤害下限
		// 金矿升级：第 n 级费用 = EconomyBaseCost × n；每级收入 +EconomyIncomeBonus（按比例）
		int32_t EconomyMaxLevel = 3;
		int32_t EconomyBaseCost = 180;
		float EconomyIncomeBonus = 0.2f;
		// 驻守：单位不越过距己方城门 HoldLineDistance 的驻守线；未交战的越线单位以 RetreatSpeedFactor 倍速后撤
		float HoldLineDistance = 1800.f;
		float RetreatSpeedFactor = 0.8f;
		// 时间上限：到时比较基地剩余生命比例（相同则比较击杀数，仍相同为平局）
		float MatchTimeLimit = 1500.f;
		// 老兵：累计击杀价值达到“自身造价 × 比例”时晋升；每级提高生命与伤害，晋升时恢复部分生命
		float VeteranRank1Ratio = 1.f;
		float VeteranRank2Ratio = 2.5f;
		float VeteranRank3Ratio = 5.f;
		float VeteranHpBonus = 0.15f;
		float VeteranDamageBonus = 0.12f;
		float VeteranPromotionHeal = 0.3f;
		// 统帅：城门附近的回血范围；场上没有友军时“随军”统帅守在城门前的距离
		float ChampionBaseHealRadius = 700.f;
		float ChampionGuardDistance = 300.f;
		// 国策：每次提供的选项数量
		int32_t DoctrineChoices = 3;
		// 背水一战：基地生命不高于该比例时可用，每局一次
		float LastStandBaseHpRatio = 0.5f;
		int32_t LastStandMilitia = 4;          // 免费征召的本时代近战兵数量
		float LastStandBuffDuration = 12.f;    // 全军鼓舞（与统帅战吼相同的加成）持续时间
		float LastStandDamageBonus = 0.3f;
		float LastStandAttackSpeedBonus = 0.25f;
		float LastStandTurretBonus = 0.5f;     // 炮塔伤害加成
		float LastStandTurretDuration = 20.f;
		float LastStandRepair = 0.1f;          // 立即修复基地最大生命的比例
		// 伤害倍率矩阵 [DamageType][ArmorType]
		float DamageMatrix[static_cast<int32_t>(DamageType::Count)][static_cast<int32_t>(ArmorType::Count)] = {
			// Light Shielded Heavy Building
			{ 1.0f, 0.9f, 1.25f, 0.6f }, // Normal
			{ 1.25f, 0.5f, 0.6f, 0.35f }, // Pierce
			{ 0.9f, 1.0f, 1.25f, 1.5f },  // Siege
			{ 1.0f, 1.0f, 1.0f, 1.0f },   // Energy
		};
	};

	struct GameData
	{
		RulesDef Rules;
		std::vector<UnitDef> Units; // 可训练兵种在前，统帅的战斗属性追加在后
		std::vector<AgeDef> Ages;
		std::vector<TurretDef> Turrets;
		std::vector<SkillDef> Skills;
		std::vector<ChampionDef> Champions; // 为空 = 不启用统帅
		std::vector<DoctrineDef> Doctrines; // 为空 = 不启用国策

		int32_t FindUnit(const std::string& InId) const;
		int32_t FindTurret(const std::string& InId) const;
		int32_t FindDoctrine(const std::string& InId) const;
		// 某时代可训练兵种（按 Role 排序：近战、远程、重型；不含统帅）
		std::vector<int32_t> UnitsForAge(int32_t InAge) const;
		std::vector<int32_t> TurretsUpToAge(int32_t InAge) const;
		int32_t SkillForAge(int32_t InAge) const;
		// 不高于该时代的最高时代统帅（Champions 下标）
		int32_t ChampionForAge(int32_t InAge) const;
		float DamageMultiplier(DamageType InDamage, ArmorType InArmor) const;
		// 国策：服务器与客户端用同一套计算（客户端据此显示实际造价/训练时间）
		DoctrineEffects ComputeEffects(const std::vector<int32_t>& Picks) const;
		int32_t EffectiveUnitCost(const DoctrineEffects& E, int32_t InDef) const;
		float EffectiveTrainTime(const DoctrineEffects& E, int32_t InDef) const;
		// 把 UnitDef 生成的统帅属性追加到 Units（数据加载器在读取统帅表后调用）
		void AppendChampion(const UnitDef& Combat, ChampionDef Def);
		// 数据完整性检查：返回空字符串表示通过
		std::string Validate() const;
	};

	const char* ToString(DamageType V);
	const char* ToString(ArmorType V);
	const char* ToString(UnitRole V);
	const char* ToString(TargetRule V);
	const char* ToString(DoctrineTarget V);
	bool ParseDamageType(const std::string& S, DamageType& Out);
	bool ParseArmorType(const std::string& S, ArmorType& Out);
	bool ParseUnitRole(const std::string& S, UnitRole& Out);
	bool ParseTargetRule(const std::string& S, TargetRule& Out);
	bool ParseDoctrineTarget(const std::string& S, DoctrineTarget& Out);
}
