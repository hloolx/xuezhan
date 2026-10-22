#pragma once

#include "CoreMinimal.h"
#include "Engine/LocalPlayer.h"
#include "CWLocalPlayer.generated.h"

// Unreal applies game login options after the platform nickname for both local
// host spawning and remote login. Keep the user's chosen name authoritative here.
UCLASS()
class CIVWAR_API UCWLocalPlayer : public ULocalPlayer
{
	GENERATED_BODY()

public:
	virtual FString GetGameLoginOptions() const override;
};
