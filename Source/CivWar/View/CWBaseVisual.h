// 血战文明 - 基地表现：按时代切换建筑、升级动画、受击反馈、炮塔槽位与炮塔动作
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "View/CWModels.h"
#include "CWBaseVisual.generated.h"

struct FCWTeamNetState;
class UCWGameDataSubsystem;
class UStaticMeshComponent;

DECLARE_MULTICAST_DELEGATE_FourParams(FCWOnTurretFired, int32 /*Team*/, int32 /*Slot*/, int32 /*TurretDef*/, FVector /*Muzzle*/);

UCLASS(NotPlaceable)
class CIVWAR_API ACWBaseVisual : public AActor
{
	GENERATED_BODY()

public:
	ACWBaseVisual();

	void Init(int32 InTeam, float InX, float InHalfWidth);
	// 新对局开始：静默恢复为石器时代外观并清空一次性事件（不播放升级动画）
	void ResetForMatch();
	void SyncState(const FCWTeamNetState& State, const UCWGameDataSubsystem* Data);
	void UpdateVisual(float Dt);

	FVector GetTurretMuzzle(int32 Slot) const;
	FVector GetGateLocation() const;
	float GetHeight() const { return Rig.Height; }
	int32 GetTeam() const { return Team; }
	int32 GetAge() const { return CurrentAge; }
	// 一次性事件（供音效/界面）
	bool ConsumeAgeUpEvent();
	bool ConsumeHitEvent();
	bool ConsumeBuildEvent();

	FCWOnTurretFired OnTurretFired;

private:
	void RebuildStructure(int32 Age);
	void RebuildTurret(int32 Slot, int32 Def, FName VisualKey);
	void ClearComponentTree(USceneComponent* Parent);
	void SpawnDebris();

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> Structure;

	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> UpgradeRing;

	UPROPERTY(Transient)
	TArray<TObjectPtr<USceneComponent>> SlotRoots;

	FCWBaseRig Rig;
	TArray<FCWTurretRig> TurretRigs;
	TArray<int32> TurretDefs;
	TArray<uint8> TurretFireSeqs;
	TArray<float> TurretRecoil;
	TArray<FVector> AimBase;
	TArray<bool> SlotUnlocked;

	struct FDebris
	{
		UStaticMeshComponent* Mesh = nullptr;
		FVector Velocity = FVector::ZeroVector;
		FVector InitialScale = FVector::OneVector;
		float Life = 0.f;
	};
	TArray<FDebris> Debris;

	int32 Team = 0;
	float HalfWidth = 300.f;
	int32 CurrentAge = -1;
	uint8 LastHitSeq = 0;
	bool bHitSeqInit = false;
	float HitFlash = 0.f;
	float Shake = 0.f;
	float RiseClock = -1.f;
	bool bUpgrading = false;
	bool bAgeUpEvent = false;
	bool bHitEvent = false;
	bool bBuildEvent = false;
	bool bSlotsInitialized = false;
	float Clock = 0.f;
};
