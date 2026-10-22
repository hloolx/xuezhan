#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "View/CWModels.h"
#include "CWSkeletalUnitPresentation.generated.h"

class AActor;
class USceneComponent;
class USkeletalMeshComponent;
class UStaticMeshComponent;
class UAnimSequence;
struct FCWUnitNetItem;

USTRUCT()
struct FCWSkeletalArtPart
{
	GENERATED_BODY()

	UPROPERTY(Transient)
	TObjectPtr<USkeletalMeshComponent> Component;

	UPROPERTY(Transient)
	TMap<FName, TObjectPtr<UAnimSequence>> Clips;
};

UCLASS()
class CIVWAR_API UCWSkeletalUnitPresentation : public UObject
{
	GENERATED_BODY()

public:
	static UCWSkeletalUnitPresentation* TryCreate(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team);
	void ApplyState(const FCWUnitNetItem& Item, float ServerNow);
	void Update(float Dt, float Speed, float ServerNow);
	float GetAttackElapsed(float ServerNow) const;
	bool ConsumeReleaseEvent();
	void DescribeRig(FCWUnitRig& Rig) const;
	FVector GetMuzzleLocation() const;
	bool HasMuzzleSocket() const { return MuzzlePart != nullptr && !MuzzleSocket.IsNone(); }
	float GetDeathDuration() const;

private:
	static UCWSkeletalUnitPresentation* TryCreateConfigured(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team);
	void Sample(FName Clip, float Time, float Dt = 0.f);

	UPROPERTY(Transient)
	TObjectPtr<USkeletalMeshComponent> Body;

	UPROPERTY(Transient)
	TObjectPtr<UStaticMeshComponent> Weapon;

	UPROPERTY(Transient)
	TMap<FName, TObjectPtr<UAnimSequence>> Clips;

	UPROPERTY(Transient)
	TArray<FCWSkeletalArtPart> AdditionalParts;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> Attachments;

	UPROPERTY(Transient)
	TObjectPtr<USkeletalMeshComponent> MuzzlePart;

	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> MuzzleAnchor;

	FName MuzzleSocket;
	FName AssetKey = TEXT("Unit_StoneAxe");
	ECWAttackStyle AttackStyle = ECWAttackStyle::Chop;
	float VisualHeight = 150.f;
	float StrideLength = 102.f;
	FName CurrentClip;
	float ReferenceMoveSpeed = 170.f;
	float ContactTime = 0.35f;
	float AttackStartTime = -1.f;
	float AttackEndTime = -1.f;
	float HitClock = -1.f;
	float DeathClock = 0.f;
	float IdleClock = 0.f;
	float MoveClock = 0.f;
	uint8 LastAttackSeq = 0;
	uint8 AttackOutcome = 0;
	uint8 LastHitSeq = 0;
	int32 UnitId = 0;
	bool bInitialized = false;
	bool bDying = false;
	bool bContactConsumed = true;
	bool bReleaseEvidenceConsumed = true;
	bool bReleasePending = false;
	bool bRestartAttackBlend = false;
	bool bRestartHitBlend = false;
	bool bMoving = false;
	bool bVehicle = false;
	bool bQuadruped = false;
};
