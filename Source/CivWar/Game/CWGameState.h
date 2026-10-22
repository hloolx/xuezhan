// 血战文明 - 对局状态（服务器写入，复制到所有客户端）
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameStateBase.h"
#include "Net/CWNetTypes.h"
#include "CWGameState.generated.h"

class ACWBattleReplicator;

namespace cw
{
	class Simulation;
}

UCLASS()
class CIVWAR_API ACWGameState : public AGameStateBase
{
	GENERATED_BODY()

public:
	ACWGameState();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	// ---------- 服务器写入 ----------
	void SetPhase(ECWMatchPhase NewPhase, float PhaseDuration = 0.f);
	void SyncFromSim(const cw::Simulation& Sim);
	void ResetMatchState(int32 StartGoldHint, float BaseHp);
	void SetResult(int32 InWinner, ECWEndReason InReason);
	void SetStatusMessage(const FString& Message);

	// ---------- 读取 ----------
	ECWMatchPhase GetPhase() const { return Phase; }
	float GetPhaseTimeLeft() const;
	const FCWTeamNetState& GetTeam(int32 Team) const;
	int32 GetWinner() const { return WinnerTeam; }
	ECWEndReason GetEndReason() const { return EndReason; }
	float GetMatchTime() const { return MatchTime; }
	ACWBattleReplicator* GetReplicator() const { return Replicator; }
	const TArray<FCWSkillCastNet>& GetSkillCasts() const { return SkillCasts; }
	const TArray<FCWLobbySlot>& GetLobbySlots() const { return LobbySlots; }
	const FString& GetStatusMessage() const { return StatusMessage; }

	UPROPERTY(Replicated)
	TObjectPtr<ACWBattleReplicator> Replicator;

	UPROPERTY(Replicated)
	bool bSinglePlayer = false;

	UPROPERTY(Replicated)
	uint8 AiDifficulty = 1;

	UPROPERTY(Replicated)
	uint32 DataChecksum = 0;

	UPROPERTY(Replicated)
	TArray<FCWLobbySlot> LobbySlots;

	UPROPERTY(Replicated)
	FString HostAddress;

	// 用于判断“决战阶段”等基于对局时间的界面提示
	UPROPERTY(Replicated)
	float MatchTime = 0.f;

private:
	UPROPERTY(Replicated)
	ECWMatchPhase Phase = ECWMatchPhase::Menu;

	UPROPERTY(Replicated)
	float PhaseEndServerTime = 0.f;

	UPROPERTY(Replicated)
	TArray<FCWTeamNetState> Teams;

	UPROPERTY(Replicated)
	int32 WinnerTeam = -1;

	UPROPERTY(Replicated)
	ECWEndReason EndReason = ECWEndReason::None;

	UPROPERTY(Replicated)
	TArray<FCWSkillCastNet> SkillCasts;

	UPROPERTY(Replicated)
	FString StatusMessage;
};
