// 血战文明 - 网络同步数据结构
// 服务器从规则核心导出状态，客户端只读这些结构并负责表现。
#pragma once

#include "CoreMinimal.h"
#include "Net/Serialization/FastArraySerializer.h"
#include "CWNetTypes.generated.h"

UENUM(BlueprintType)
enum class ECWMatchPhase : uint8
{
	Menu,       // 主菜单（本地独立实例，无对局）
	Lobby,      // 房间：等待玩家加入与准备
	Countdown,  // 开局倒计时
	InMatch,    // 对局进行中
	PostMatch,  // 结算
};

// 会话模式：由地图 URL 参数 ?mode= 决定
UENUM(BlueprintType)
enum class ECWSessionMode : uint8
{
	Menu,   // 主菜单背景
	Single, // 单人对战 AI
	Lobby,  // 联机房间（监听服务器）
};

UENUM(BlueprintType)
enum class ECWEndReason : uint8
{
	None,
	BaseDestroyed,
	Forfeit,   // 对手离开/断线
	TimeLimit, // 到达时间上限（胜者为 -1 表示平局）
};

// ---------------- 单位（FastArray：只同步变化的单位） ----------------
USTRUCT()
struct FCWUnitNetItem : public FFastArraySerializerItem
{
	GENERATED_BODY()

	UPROPERTY() int32 Id = 0;
	UPROPERTY() uint8 Team = 0;
	UPROPERTY() uint8 Row = 0;
	UPROPERTY() uint16 Def = 0;
	UPROPERTY() float X = 0.f;
	UPROPERTY() uint16 Hp = 0;
	UPROPERTY() uint8 State = 0;      // cw::UnitState
	UPROPERTY() uint8 AttackSeq = 0;  // 变化 = 开始一次攻击（表现层播放攻击动作）
	UPROPERTY() float AttackStartServerTime = -1.f;
	UPROPERTY() uint8 AttackOutcome = 0;
	UPROPERTY() float AttackEndServerTime = -1.f;
	UPROPERTY() uint8 HitSeq = 0;     // 变化 = 受击
	UPROPERTY() int32 TargetId = -1;  // -2 = 敌方基地
	UPROPERTY() uint16 MaxHp = 1;     // 实际生命上限（含国策、老兵等级）
	UPROPERTY() uint8 Rank = 0;       // 老兵等级 0..3
	UPROPERTY() uint8 Flags = 0;      // CWUnitFlags
};

// FCWUnitNetItem::Flags
namespace CWUnitFlags
{
	constexpr uint8 Champion = 1 << 0; // 统帅
	constexpr uint8 Rallied = 1 << 1;  // 战吼增益中
}

USTRUCT()
struct FCWUnitNetArray : public FFastArraySerializer
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FCWUnitNetItem> Items;

	bool NetDeltaSerialize(FNetDeltaSerializeInfo& DeltaParms)
	{
		return FFastArraySerializer::FastArrayDeltaSerialize<FCWUnitNetItem, FCWUnitNetArray>(Items, DeltaParms, *this);
	}
};

template <>
struct TStructOpsTypeTraits<FCWUnitNetArray> : public TStructOpsTypeTraitsBase2<FCWUnitNetArray>
{
	enum
	{
		WithNetDeltaSerializer = true,
	};
};

// ---------------- 投射物（只同步发射，飞行由客户端按相同速度表现） ----------------
USTRUCT()
struct FCWProjectileNetItem : public FFastArraySerializerItem
{
	GENERATED_BODY()

	UPROPERTY() int32 Id = 0;
	UPROPERTY() uint8 Team = 0;
	UPROPERTY() int32 SourceUnit = -1;   // 发射单位 Id；炮塔为 -1
	UPROPERTY() int8 SourceSlot = -1;    // 炮塔槽位
	UPROPERTY() int32 TargetId = -1;     // -2 = 基地
	UPROPERTY() float StartX = 0.f;
	UPROPERTY() float TargetX = 0.f;
	UPROPERTY() float Speed = 1000.f;
	UPROPERTY() float Splash = 0.f;
	UPROPERTY() uint16 VisualDef = 0;    // 单位或炮塔的定义下标，用于选择弹体外观
};

USTRUCT()
struct FCWProjectileNetArray : public FFastArraySerializer
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FCWProjectileNetItem> Items;

	bool NetDeltaSerialize(FNetDeltaSerializeInfo& DeltaParms)
	{
		return FFastArraySerializer::FastArrayDeltaSerialize<FCWProjectileNetItem, FCWProjectileNetArray>(Items, DeltaParms, *this);
	}
};

template <>
struct TStructOpsTypeTraits<FCWProjectileNetArray> : public TStructOpsTypeTraitsBase2<FCWProjectileNetArray>
{
	enum
	{
		WithNetDeltaSerializer = true,
	};
};

// ---------------- 阵营状态 ----------------
USTRUCT()
struct FCWQueueNetItem
{
	GENERATED_BODY()

	UPROPERTY() uint16 Def = 0;
	UPROPERTY() float Progress = 0.f;
};

USTRUCT()
struct FCWTurretNetSlot
{
	GENERATED_BODY()

	UPROPERTY() bool bUnlocked = false;
	UPROPERTY() int16 Def = -1;
	UPROPERTY() uint8 Level = 0;
	UPROPERTY() int32 TargetId = -1;
	UPROPERTY() uint8 FireSeq = 0;
	UPROPERTY() int32 Invested = 0; // 界面显示出售返还
};

USTRUCT()
struct FCWTeamNetState
{
	GENERATED_BODY()

	UPROPERTY() int32 Gold = 0;
	UPROPERTY() int32 Xp = 0;
	UPROPERTY() uint8 Age = 0;
	UPROPERTY() bool bUpgrading = false;
	UPROPERTY() float UpgradeTimeLeft = 0.f;
	UPROPERTY() float BaseHp = 0.f;
	UPROPERTY() float BaseMaxHp = 1.f;
	UPROPERTY() float SkillCooldown = 0.f;
	UPROPERTY() uint8 BaseHitSeq = 0;
	UPROPERTY() uint8 EconomyLevel = 0; // 金矿等级
	UPROPERTY() uint8 Stance = 0;       // 0 推进 / 1 驻守
	// 国策
	UPROPERTY() TArray<uint8> Doctrines; // 已选（数据表下标）
	UPROPERTY() TArray<uint8> Offer;     // 当前可选项；空 = 没有待选
	UPROPERTY() uint8 PendingPicks = 0;
	// 统帅
	UPROPERTY() int32 ChampionId = -1;      // 阵亡时为 -1
	UPROPERTY() int16 ChampionDef = -1;     // 当前时代的统帅（Champions 下标）
	UPROPERTY() float ChampionRespawn = 0.f;
	UPROPERTY() uint8 ChampionOrder = 0;    // 0 随军 / 1 坚守
	UPROPERTY() float ChampionHoldX = 0.f;
	UPROPERTY() float ChampionCooldown = 0.f;
	UPROPERTY() uint8 ChampionAbilitySeq = 0;
	// 背水一战
	UPROPERTY() bool bLastStandUsed = false;
	UPROPERTY() float TurretBoostTime = 0.f;
	UPROPERTY() TArray<FCWQueueNetItem> Queue;
	UPROPERTY() TArray<FCWTurretNetSlot> Turrets;
	// 结算统计
	UPROPERTY() int32 UnitsTrained = 0;
	UPROPERTY() int32 UnitsLost = 0;
	UPROPERTY() int32 Kills = 0;
	UPROPERTY() int32 GoldSpent = 0;
	UPROPERTY() float DamageToBase = 0.f;
	UPROPERTY() int32 Promotions = 0;
	UPROPERTY() int32 ChampionKills = 0;
};

USTRUCT()
struct FCWSkillCastNet
{
	GENERATED_BODY()

	UPROPERTY() int32 Id = 0;
	UPROPERTY() uint8 Team = 0;
	UPROPERTY() uint8 Skill = 0;
	UPROPERTY() float X = 0.f;
	UPROPERTY() float Radius = 0.f;
	UPROPERTY() float ImpactServerTime = 0.f; // 以 GameState 服务器时间计
};

// 房间内玩家信息
USTRUCT()
struct FCWLobbySlot
{
	GENERATED_BODY()

	UPROPERTY() bool bOccupied = false;
	UPROPERTY() bool bReady = false;
	UPROPERTY() bool bIsAI = false;
	UPROPERTY() FString Name;
};
