// 血战文明 - 规则核心：运行时状态、玩家指令与事件
#pragma once

#include "SimTypes.h"

namespace cw
{
	enum class UnitState : uint8_t
	{
		Walking = 0, // 行军
		Blocked,     // 被友军挡住，原地等待
		Attacking,   // 目标在射程内：停下攻击
		Dying,       // 死亡表现中：不可选中、不阻挡、不攻击
	};

	// 目标编码：>=0 为单位 Id；TargetBase 表示敌方基地；TargetNone 表示无目标
	constexpr int32_t TargetNone = -1;
	constexpr int32_t TargetBase = -2;

	enum class AttackOutcome : uint8_t
	{
		None = 0,
		Windup,
		Released,
		Cancelled,
	};

	struct Unit
	{
		int32_t Id = 0;
		int32_t Team = 0;
		int32_t Def = 0;
		int32_t Row = 0;          // 所在队列行（0..LaneRows-1）
		float X = 0.f;
		float Hp = 0.f;
		UnitState State = UnitState::Walking;
		int32_t TargetId = TargetNone;
		float Cooldown = 0.f;     // 距离下一次可以开始攻击的时间
		float Windup = 0.f;       // >0 表示正在前摇
		float RetargetTimer = 0.f;
		float DeathTimer = 0.f;
		uint8_t AttackSeq = 0;    // 每次开始攻击 +1，表现层据此播放攻击动作
		float AttackStartSimTime = -1.f;
		AttackOutcome AttackResult = AttackOutcome::None;
		float AttackEndSimTime = -1.f;
		uint8_t HitSeq = 0;       // 每次受击 +1，表现层据此播放受击
		bool ChargeReady = true;  // 行军后首击（冲锋）
		float WalkTime = 0.f;     // 连续行军时长，用于重新蓄力冲锋
		int32_t LastAttackerTeam = -1;
		bool Champion = false;    // 统帅：不受友军阻挡、也不阻挡友军；可由玩家指挥前后移动
		// 实际属性（数据表数值 × 国策 × 老兵等级 × 统帅加成），由 RefreshUnitStats 计算
		float MaxHp = 0.f;
		float DamageMul = 1.f;
		float SpeedMul = 1.f;
		float RangeMul = 1.f;
		float AttackSpeedMul = 1.f;
		int32_t Rank = 0;         // 老兵等级 0..3
		float KillValue = 0.f;    // 累计击杀价值（决定晋升）
		float BuffTime = 0.f;     // 统帅战吼的剩余时间
		float BuffDamage = 0.f;
		float BuffAttackSpeed = 0.f;
	};

	struct Projectile
	{
		int32_t Id = 0;
		int32_t Team = 0;      // 发射方
		int32_t SourceUnit = -1; // 发射单位 Id（炮塔为 -1）
		int32_t SourceTurretSlot = -1;
		int32_t TargetId = TargetNone;
		float X = 0.f;         // 当前水平位置
		float TargetX = 0.f;   // 最后已知目标位置
		float Speed = 1000.f;
		float Damage = 0.f;
		float SplashRadius = 0.f;
		float StructureMultiplier = 1.f;
		DamageType DmgType = DamageType::Pierce;
	};

	struct QueueItem
	{
		int32_t Def = 0;
		float Progress = 0.f; // 已训练时长
		int32_t PaidGold = 0;
	};

	struct TurretSlot
	{
		bool Unlocked = false;
		int32_t Def = InvalidIndex; // 空槽 = InvalidIndex
		int32_t Level = 0;
		float Cooldown = 0.f;
		float RetargetTimer = 0.f;
		int32_t TargetId = TargetNone;
		int32_t Invested = 0;  // 累计投入，用于出售返还
		uint8_t FireSeq = 0;
	};

	struct SkillCast
	{
		int32_t Id = 0;
		int32_t Team = 0;
		int32_t Skill = 0;
		float X = 0.f;
		float TimeLeft = 0.f;
	};

	struct TeamStats
	{
		int32_t UnitsTrained = 0;
		int32_t UnitsLost = 0;
		int32_t Kills = 0;
		int32_t GoldEarned = 0;
		int32_t GoldSpent = 0;
		float DamageToBase = 0.f;
		int32_t Promotions = 0;    // 老兵晋升次数
		int32_t ChampionKills = 0; // 击杀敌方统帅次数
	};

	// 军队姿态：推进（默认）/ 驻守（不越过驻守线，未交战的越线单位后撤）
	enum class ArmyStance : uint8_t
	{
		Advance = 0,
		Hold = 1,
	};

	// 统帅指令：随军（跟随己方最前方的部队）/ 坚守（停在指定位置）
	enum class ChampionOrder : uint8_t
	{
		Follow = 0,
		Hold = 1,
	};

	struct TeamState
	{
		double Gold = 0.0;
		double Xp = 0.0;
		int32_t Age = 0;
		bool Upgrading = false;
		float UpgradeTimeLeft = 0.f;
		float BaseHp = 0.f;
		float BaseMaxHp = 0.f;
		std::vector<QueueItem> Queue;
		std::vector<TurretSlot> Turrets;
		float SkillCooldown = 0.f;
		int32_t EconomyLevel = 0;               // 金矿等级：每级提高收入
		ArmyStance Stance = ArmyStance::Advance;
		uint8_t BaseHitSeq = 0;
		TeamStats Stats;
		// 国策
		std::vector<int32_t> Doctrines; // 已选（Doctrines 下标，按选择顺序）
		std::vector<int32_t> Offer;     // 当前可选项（空 = 没有待选）
		int32_t PendingPicks = 0;       // 尚未使用的选择次数（含当前 Offer）
		DoctrineEffects Effects;
		// 统帅
		int32_t ChampionId = -1;                 // 存活时为单位 Id，阵亡时为 -1
		int32_t ChampionDef = InvalidIndex;      // 当前时代的统帅（Champions 下标）
		float ChampionRespawn = 0.f;             // 阵亡后剩余复活时间
		ChampionOrder Order = ChampionOrder::Follow;
		float ChampionHoldX = 0.f;
		float ChampionCooldown = 0.f;
		uint8_t ChampionAbilitySeq = 0;          // 每次施放战吼 +1，表现层据此播放特效
		// 背水一战（每局一次）
		bool LastStandUsed = false;
		float TurretBoostTime = 0.f;             // 炮塔强化剩余时间
	};

	enum class MatchPhase : uint8_t
	{
		NotStarted = 0,
		Running,
		Ended,
	};

	// ---------------- 玩家指令 ----------------
	// 指令由服务器以“发起方阵营”调用；客户端不能指定阵营。
	enum class CommandType : uint8_t
	{
		Train = 0,     // A = 兵种在本时代列表中的槽位(0..2)
		CancelTrain,   // A = 队列下标
		UpgradeAge,
		BuyTurretSlot,
		BuildTurret,   // A = 槽位, B = 炮塔定义下标
		UpgradeTurret, // A = 槽位
		SellTurret,    // A = 槽位
		CastSkill,     // X = 落点
		UpgradeEconomy, // 金矿升级
		SetStance,     // A = 0 推进 / 1 驻守
		ChooseDoctrine, // A = 当前国策选项的下标
		ChampionMove,  // A = 0 坚守于 X / 1 随军
		ChampionAbility, // 统帅战吼
		LastStand,     // 背水一战
		Count
	};

	struct Command
	{
		CommandType Type = CommandType::Train;
		int32_t A = 0;
		int32_t B = 0;
		float X = 0.f;
	};

	enum class CommandResult : uint8_t
	{
		Ok = 0,
		MatchNotRunning,
		InvalidTeam,
		InvalidParam,
		NotEnoughGold,
		NotEnoughXp,
		QueueFull,
		LockedByAge,
		AgeMax,
		AgeNotImplemented,
		Upgrading,
		SlotLocked,
		SlotOccupied,
		SlotEmpty,
		NoMoreSlots,
		MaxLevel,
		OnCooldown,
		BadTarget,
		NoOffer,       // 没有待选的国策
		ChampionDead,  // 统帅阵亡中
		NoChampion,    // 未启用统帅
		Unavailable,   // 条件未满足（背水一战：基地生命仍高于门槛）
		AlreadyUsed,   // 每局一次，已经用过
	};

	const char* ToString(CommandResult V);

	// ---------------- 事件（每步清空，供表现层/网络层使用） ----------------
	enum class EventType : uint8_t
	{
		UnitSpawned = 0,
		UnitAttackStart, // A=单位Id, B=目标Id
		UnitHit,         // A=单位Id, Value=伤害
		UnitDied,        // A=单位Id, B=击杀方阵营
		ProjectileFired, // A=投射物Id, B=发射单位Id(炮塔为-1)
		ProjectileImpact,// A=投射物Id, X=落点
		BaseHit,         // Team=基地所属, Value=伤害
		KillReward,      // Team=获得方, A=金币, B=经验
		AgeUpgradeStart, // Team, A=目标时代
		AgeUpgradeDone,  // Team, A=新时代
		TurretFired,     // Team, A=槽位, B=目标Id
		SkillCast,       // Team, A=施放Id, X=落点
		SkillImpact,     // Team, A=施放Id, X=落点, B=命中数量
		EconomyUpgraded, // Team, A=新等级
		StanceChanged,   // Team, A=姿态
		SuddenDeath,     // 决战阶段开始
		MatchEnded,      // Team=胜方
		ChampionSpawned, // Team, A=单位Id, X=位置
		ChampionDied,    // Team=阵亡方, A=单位Id, B=击杀方阵营, Value=赏金
		ChampionAbility, // Team, A=单位Id, B=受影响友军数, X=位置, Value=半径
		UnitPromoted,    // Team, A=单位Id, B=新等级, X=位置
		DoctrineOffered, // Team, A=选项数量
		DoctrineChosen,  // Team, A=国策下标
		LastStand,       // Team, A=征召人数
	};

	struct SimEvent
	{
		EventType Type = EventType::UnitSpawned;
		int32_t Team = 0;
		int32_t A = 0;
		int32_t B = 0;
		float X = 0.f;
		float Value = 0.f;
	};
}
