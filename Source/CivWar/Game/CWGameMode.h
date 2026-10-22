// 血战文明 - 服务器权威游戏模式
// 只在服务器（单机/监听服务器主机）上存在：持有规则核心实例，按固定步长推进，
// 校验并执行所有玩家指令，把结果写入 GameState / 复制器。
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "Net/CWNetTypes.h"
#include "Sim/SimAI.h"
#include "Sim/Simulation.h"
#include "CWGameMode.generated.h"

class ACWBattleReplicator;
class ACWGameState;
class ACWPlayerController;

UCLASS()
class CIVWAR_API ACWGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ACWGameMode();

	static constexpr float FixedStep = 0.05f; // 20 Hz，与独立测试程序一致
	static constexpr float CountdownSeconds = 3.f;

	virtual void InitGame(const FString& MapName, const FString& Options, FString& ErrorMessage) override;
	virtual void PreLogin(const FString& Options, const FString& Address, const FUniqueNetIdRepl& UniqueId, FString& ErrorMessage) override;
	virtual void PostLogin(APlayerController* NewPlayer) override;
	virtual void Logout(AController* Exiting) override;
	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;
	virtual bool PlayerCanRestart_Implementation(APlayerController* Player) override;

	// 由玩家控制器的 Server RPC 调用；阵营一律取自服务器分配的 PlayerState
	void HandleCommand(ACWPlayerController* PC, uint8 Type, int32 A, int32 B, float X);
	void HandleReady(ACWPlayerController* PC, bool bReady);
	void HandleReturnToLobby(ACWPlayerController* PC);
	void HandleRestartSingle(ACWPlayerController* PC);

	ECWSessionMode GetSessionMode() const { return SessionMode; }

private:
	ACWGameState* GetCWGameState() const;
	void EnsureSessionState();
	void EnsureReplicator();
	void StartCountdown();
	void StartMatch();
#if WITH_EDITOR
	bool PrepareEraArtFixture(int32 Age);
#endif
	void StepMatch(float DeltaSeconds);
	void ProcessSimEvents();
	void EndMatch(int32 Winner, ECWEndReason Reason);
	void ReturnToLobby();
	void UpdateLobbySlots(const AController* Leaving = nullptr);
	int32 FindFreeTeam(const AController* Ignore = nullptr) const;
	FString DescribeHostAddress() const;

	ECWSessionMode SessionMode = ECWSessionMode::Menu;
	bool bSessionInitialized = false;
	cw::AiDifficulty Difficulty = cw::AiDifficulty::Normal;
	TUniquePtr<cw::Simulation> Sim;
	TUniquePtr<cw::AiPlayer> Ai;
	// 展示模式（-cwshowcase，仅用于自动截图）：阵营 0 也由同规则 AI 操控，并定时补足升级时代所需的经验与金币
	TUniquePtr<cw::AiPlayer> ShowcaseAi;
	float ShowcaseNextGrant = 0.f;
	float Accumulator = 0.f;
	TMap<int32, TPair<int32, float>> CastInfo; // 施放 Id → (技能下标, 半径)

	UPROPERTY(Transient)
	TObjectPtr<ACWBattleReplicator> Replicator;
};
