#pragma once

#include "CoreMinimal.h"

class AActor;
class USceneComponent;
struct FCWTurretRig;

namespace CWStaticTurretPilot
{
	struct FRockTowerPose
	{
		float Pitch = 35.f;
		bool bStoneVisible = true;
	};

	FRockTowerPose SamplePose(float Elapsed);
	bool TryBuild(AActor* Owner, USceneComponent* Mount, FName VisualKey, int32 Team, int32 Slot, bool bBasePilot, FCWTurretRig& Rig);
	void BeginFire(FCWTurretRig& Rig);
	bool Update(FCWTurretRig& Rig, float DeltaSeconds);
}
