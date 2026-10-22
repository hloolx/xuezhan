#pragma once

#include "Animation/AnimSingleNodeInstance.h"
#include "CWSmoothUnitAnimInstance.generated.h"

// Same explicit sample clock as SingleNode; only the transition pose is blended.
// In particular, this does not advance/restart the authoritative attack clock.
UCLASS(Transient)
class CIVWAR_API UCWSmoothUnitAnimInstance : public UAnimSingleNodeInstance
{
	GENERATED_BODY()

public:
	void PrepareBlend(bool bNewPose, float Duration, float Dt);

protected:
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
};
