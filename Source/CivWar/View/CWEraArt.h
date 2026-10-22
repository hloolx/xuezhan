#pragma once

#include "CoreMinimal.h"
#include "UObject/StrongObjectPtr.h"

class AActor;
class FJsonObject;
class UAnimSequence;
class USkeletalMeshComponent;
class USceneComponent;
class UMaterialInstanceDynamic;
struct FCWBaseRig;
struct FCWTurretRig;
namespace cw { struct UnitDef; }

struct FCWEraMotionFrame
{
	float Time = 0.f;
	FVector Translation = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	float Scalar = 0.f;
	bool bVisible = true;
};

struct FCWEraMotionChannel
{
	USceneComponent* Component = nullptr;
	UMaterialInstanceDynamic* Material = nullptr;
	FName ScalarParameter;
	float ReadyScalar = 0.f;
	FTransform ReadyTransform = FTransform::Identity;
	TArray<FCWEraMotionFrame> Frames;
};

struct FCWEraSkeletalPart
{
	USkeletalMeshComponent* Component = nullptr;
	// The inactive clip must remain alive too; this rig is not a reflected UObject.
	TStrongObjectPtr<UAnimSequence> ReadyClip;
	TStrongObjectPtr<UAnimSequence> FireClip;
	UAnimSequence* SampledClip = nullptr;
};

namespace CWEraArt
{
	// Runtime GameData includes the combat rows synthesized from Champions.json.
	const cw::UnitDef* FindUnit(AActor* Owner, FName VisualKey);
	TSharedPtr<FJsonObject> LoadEntry(FName VisualKey, const TCHAR* Kind);
	bool TryBuildBase(AActor* Owner, USceneComponent* Parent, int32 Age, int32 Team, FCWBaseRig& Rig);
	bool TryBuildTurret(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team, FCWTurretRig& Rig);
	FCWEraMotionFrame SampleMotion(const TArray<FCWEraMotionFrame>& Frames, float Time);
	void BeginFire(FCWTurretRig& Rig);
	bool UpdateTurret(FCWTurretRig& Rig, float Dt);
}
