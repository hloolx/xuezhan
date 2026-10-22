#pragma once

#include "CoreMinimal.h"

class AActor;
class USceneComponent;
struct FCWBaseRig;

namespace CWStaticBasePilot
{
	bool TryBuild(AActor* Owner, USceneComponent* Parent, int32 Age, int32 Team, FCWBaseRig& Rig);
}
