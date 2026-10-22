// 血战文明 - 游戏实例：菜单流程（单人/创建房间/加入房间）与网络异常处理
#pragma once

#include "CoreMinimal.h"
#include "Engine/EngineBaseTypes.h"
#include "Engine/GameInstance.h"
#include "CWGameInstance.generated.h"

class UNetDriver;

UCLASS()
class CIVWAR_API UCWGameInstance : public UGameInstance
{
	GENERATED_BODY()

public:
	virtual void Init() override;
	virtual void Shutdown() override;

	static constexpr int32 DefaultPort = 7777;

	void StartSinglePlayer(int32 Difficulty);
	void HostRoom();
	// Address 支持 “IP” 或 “IP:端口”
	bool JoinRoom(const FString& Address, FText& OutError);
	void CancelJoin();
	void OpenMainMenu();
	void ReturnToMainMenuWithError(const FText& Message);

	bool IsConnecting() const { return bConnecting; }
	bool IsTransitionPending() const { return bConnecting || bLocalTravelPending; }
	const FString& GetJoinAddress() const { return JoinAddress; }
	double GetConnectStartTime() const { return ConnectStartTime; }
	// 主菜单读取并清除上一条错误
	FText ConsumePendingError();
	bool HasPendingError() const { return !PendingError.IsEmpty(); }
	void SetPendingError(const FText& Message) { PendingError = Message; }

	FString PlayerName;
	// Shared read-only URL-safe nickname for travel and the local player's login.
	FString SanitizedName() const;

	static FString GetBattleMapPath() { return TEXT("/Game/Maps/Battlefield"); }

	// 自动化测试参数（命令行）：-cwhost / -cwjoin=IP / -cwsingle=难度 / -cwautoready / -cwautoplay / -cwexitonend
	bool bAutoReady = false;
	bool bAutoPlay = false;
	bool bExitOnEnd = false;

private:
	void HandleNetworkFailure(UWorld* World, UNetDriver* NetDriver, ENetworkFailure::Type FailureType, const FString& ErrorString);
	void HandleTravelFailure(UWorld* World, ETravelFailure::Type FailureType, const FString& ErrorString);
	void HandlePostLoadMap(UWorld* World);
	bool RunStartupAction();
	void ScheduleJoinRetry();
	int32 JoinAttempts = 0;

	FText PendingError;
	bool bConnecting = false;
	bool bLocalTravelPending = false;
	FString StartupAction;   // host / join / single
	FString StartupArgument;
	bool bStartupActionDone = false;
	FString JoinAddress;
	double ConnectStartTime = 0.0;
	FDelegateHandle NetworkFailureHandle;
	FDelegateHandle TravelFailureHandle;
	FDelegateHandle PostLoadMapHandle;
};
