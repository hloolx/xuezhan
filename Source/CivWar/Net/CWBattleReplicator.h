// 血战文明 - 战场状态复制器：服务器把规则核心的单位/投射物导出为 FastArray，所有客户端只读
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Info.h"
#include "Net/CWNetTypes.h"
#include "CWBattleReplicator.generated.h"

namespace cw
{
	class Simulation;
}

DECLARE_MULTICAST_DELEGATE_FiveParams(FCWOnSkillImpact, uint8 /*Team*/, uint8 /*Skill*/, float /*X*/, float /*Radius*/, int32 /*Hits*/);

UCLASS()
class CIVWAR_API ACWBattleReplicator : public AInfo
{
	GENERATED_BODY()

public:
	ACWBattleReplicator();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	// 仅服务器：每个模拟步之后调用
	void SyncFromSim(const cw::Simulation& Sim, float ServerTime, float SnapshotServerTime);
	void ClearAll();

	const FCWUnitNetArray& GetUnits() const { return Units; }
	const FCWProjectileNetArray& GetProjectiles() const { return Projectiles; }

	// 技能落地：一次性表现事件（不可靠多播，丢失只影响特效，不影响结果）
	UFUNCTION(NetMulticast, Unreliable)
	void MulticastSkillImpact(uint8 Team, uint8 Skill, float X, float Radius, int32 Hits);

	FCWOnSkillImpact OnSkillImpact;

private:
	UPROPERTY(Replicated)
	FCWUnitNetArray Units;

	UPROPERTY(Replicated)
	FCWProjectileNetArray Projectiles;

	// 服务器端索引
	TMap<int32, int32> UnitIdToItem;
	TMap<int32, float> UnitAttackStartSimTimes;
	TMap<int32, float> UnitAttackEndSimTimes;
	TMap<int32, float> ProjectileExpire; // 已命中的投射物延迟移除，保证客户端至少收到一次
	TSet<int32> KnownProjectiles;
};
