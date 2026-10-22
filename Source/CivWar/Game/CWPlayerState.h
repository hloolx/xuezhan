// 血战文明 - 玩家状态：阵营归属由服务器分配，客户端不能修改
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerState.h"
#include "CWPlayerState.generated.h"

UCLASS()
class CIVWAR_API ACWPlayerState : public APlayerState
{
	GENERATED_BODY()

public:
	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	int32 GetTeam() const { return Team; }
	bool IsReady() const { return bReady; }

	// 仅服务器
	void SetTeam(int32 InTeam) { Team = InTeam; }
	void SetReady(bool bInReady) { bReady = bInReady; }

private:
	// -1 = 未分配（观战/房间已满）
	UPROPERTY(Replicated)
	int32 Team = -1;

	UPROPERTY(Replicated)
	bool bReady = false;
};
