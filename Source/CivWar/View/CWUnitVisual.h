// 血战文明 - 单位表现：插值网络位置，播放行走/攻击/受击/死亡程序化动画
// 攻击动作的“命中/出手”时刻与数据表中的 AttackWindup 一致，服务器在同一时刻结算伤害或发射投射物。
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "View/CWModels.h"
#include "View/CWVisualMotion.h"
#include "View/CWVisualMotionTrace.h"
#include "CWUnitVisual.generated.h"

struct FCWUnitNetItem;
class UPointLightComponent;
class UStaticMeshComponent;
class UProceduralMeshComponent;
class UCWSkeletalUnitPresentation;

UCLASS(NotPlaceable)
class CIVWAR_API ACWUnitVisual : public AActor
{
	GENERATED_BODY()

public:
	ACWUnitVisual();

	void Init(int32 InId, int32 InTeam, int32 InDef, FName VisualKey, float InMaxHp, float InMoveSpeed, float InWindup, float InX, float InLaneY);
	// 统帅：脚下显示光环范围
	void SetupChampion(float AuraRadius);
	void ApplyNetState(const FCWUnitNetItem& Item);
	void UpdateVisual(float Dt);

	int32 GetUnitId() const { return UnitId; }
	int32 GetTeam() const { return Team; }
	int32 GetDef() const { return Def; }
	float GetVisualX() const { return VisualX; }
	float GetHpRatio() const { return MaxHp > 0.f ? Hp / MaxHp : 0.f; }
	bool IsDying() const { return bDying; }
	bool KeepDeathVisual() const;
	bool HasSkeletalArtPilot() const { return SkeletalPresentation != nullptr; }
	float GetHeight() const { return Rig.Height; }
	float GetTimeSinceHit() const { return TimeSinceHit; }
	FVector GetMuzzleLocation() const;
	FVector GetHitLocation() const;
	// 一次性表现事件（音效等），读取后清除
	bool ConsumeReleaseEvent(); // 到达出手/命中时刻
	bool ConsumeHitEvent();     // 受击
	bool ConsumeDeathEvent();   // 开始死亡
	bool ConsumePromotionEvent(); // 晋升老兵
	bool IsChampion() const { return bChampion; }
	int32 GetRank() const { return Rank; }
	bool IsRallied() const { return bRallied; }
	ECWAttackStyle GetAttackStyle() const { return Rig.Style; }
	bool IsVehicle() const { return Rig.bVehicle; }

private:
	void StartAttack();
	void AnimateWalk(float Dt, float Speed);
	void AnimateAttack();
	void AnimateDeath(float Dt);
	void ApplyFlash();
	void TraceMotion(float Dt);
	float GetPresentationServerTime() const;

	UPROPERTY(Transient)
	TObjectPtr<UCWSkeletalUnitPresentation> SkeletalPresentation;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Model;

	UPROPERTY(Transient)
	TObjectPtr<UStaticMeshComponent> MuzzleFlash;

	UPROPERTY(Transient)
	TObjectPtr<UProceduralMeshComponent> AuraRing;

	UPROPERTY(Transient)
	TObjectPtr<UStaticMeshComponent> RallyRing;

	FCWUnitRig Rig;
	FCWVisualMotion Motion;
	int32 UnitId = 0;
	int32 Team = 0;
	int32 Def = 0;
	float MaxHp = 1.f;
	float Hp = 1.f;
	float MoveSpeed = 150.f;
	float Windup = 0.3f;
	float TargetX = 0.f;
	float VisualX = 0.f;
	float LaneY = 0.f;
	uint8 NetState = 0;
	uint8 LastAttackSeq = 0;
	uint8 LastHitSeq = 0;
	bool bSeqInitialized = false;
	bool bDying = false;
	bool bReleasePending = false;
	bool bReleasedThisAttack = false;
	bool bHitEvent = false;
	bool bDeathEvent = false;
	float AttackClock = -1.f;  // 攻击开始后的时间；<0 表示未在攻击
	float HitFlash = 0.f;
	float TimeSinceHit = 100.f;
	float DeathClock = 0.f;
	float WalkPhase = 0.f;
	float SpawnClock = 0.f;
	float FlashClock = 0.f;
	float WheelAngle = 0.f;
	float CurrentYaw = 0.f;   // 撤退时转身：表现层朝向
	bool bFacingBack = false;
	bool bChampion = false;
	bool bRallied = false;
	bool bPromotedEvent = false;
	int32 Rank = 0;
	bool bRankInitialized = false;
	FCWVisualMotionTrace MotionTrace;
	bool bMotionTraceComplete = false;
};
