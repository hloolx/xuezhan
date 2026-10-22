#include "Game/CWGameInstance.h"

#include "CivWar.h"
#include "Engine/Engine.h"
#include "Engine/NetDriver.h"
#include "GameFramework/PlayerController.h"
#include "Containers/Ticker.h"
#include "HAL/PlatformProcess.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "UObject/UObjectGlobals.h"

#define LOCTEXT_NAMESPACE "CivWar"

void UCWGameInstance::Init()
{
	Super::Init();
	PlayerName = FPlatformProcess::ComputerName();
	if (GEngine)
	{
		NetworkFailureHandle = GEngine->OnNetworkFailure().AddUObject(this, &UCWGameInstance::HandleNetworkFailure);
		TravelFailureHandle = GEngine->OnTravelFailure().AddUObject(this, &UCWGameInstance::HandleTravelFailure);
	}
	PostLoadMapHandle = FCoreUObjectDelegates::PostLoadMapWithWorld.AddUObject(this, &UCWGameInstance::HandlePostLoadMap);

	// 自动化测试：多实例联机冒烟测试与无人值守对局
	const TCHAR* Cmd = FCommandLine::Get();
	FString Value;
	bAutoReady = FParse::Param(Cmd, TEXT("cwautoready"));
	bAutoPlay = FParse::Param(Cmd, TEXT("cwautoplay"));
	bExitOnEnd = FParse::Param(Cmd, TEXT("cwexitonend"));
	if (FParse::Value(Cmd, TEXT("cwname="), Value))
	{
		PlayerName = Value;
	}
	if (FParse::Param(Cmd, TEXT("cwhost")))
	{
		StartupAction = TEXT("host");
	}
	else if (FParse::Value(Cmd, TEXT("cwjoin="), Value))
	{
		StartupAction = TEXT("join");
		StartupArgument = Value;
	}
	else if (FParse::Value(Cmd, TEXT("cwsingle="), Value))
	{
		StartupAction = TEXT("single");
		StartupArgument = Value;
	}
	if (!StartupAction.IsEmpty())
	{
		UE_LOG(LogCivWar, Log, TEXT("自动化启动动作：%s %s"), *StartupAction, *StartupArgument);
		// 等主菜单地图加载完成后执行（加入房间时给主机留出启动时间）
		const float Delay = StartupAction == TEXT("join") ? 6.f : 1.f;
		FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateWeakLambda(this, [this](float) { return RunStartupAction(); }), Delay);
	}
}

bool UCWGameInstance::RunStartupAction()
{
	if (bStartupActionDone || !GetWorld() || !GetFirstLocalPlayerController())
	{
		return !bStartupActionDone; // 尚未就绪则继续等待
	}
	bStartupActionDone = true;
	if (StartupAction == TEXT("host"))
	{
		HostRoom();
	}
	else if (StartupAction == TEXT("join"))
	{
		FText Error;
		if (!JoinRoom(StartupArgument, Error))
		{
			UE_LOG(LogCivWar, Error, TEXT("自动加入失败：%s"), *Error.ToString());
		}
	}
	else if (StartupAction == TEXT("single"))
	{
		StartSinglePlayer(FCString::Atoi(*StartupArgument));
	}
	return false;
}

void UCWGameInstance::Shutdown()
{
	if (GEngine)
	{
		GEngine->OnNetworkFailure().Remove(NetworkFailureHandle);
		GEngine->OnTravelFailure().Remove(TravelFailureHandle);
	}
	FCoreUObjectDelegates::PostLoadMapWithWorld.Remove(PostLoadMapHandle);
	Super::Shutdown();
}

FString UCWGameInstance::SanitizedName() const
{
	FString Name = PlayerName.Left(16);
	// URL 参数中不能出现分隔符
	for (const TCHAR Bad : { TEXT('?'), TEXT('='), TEXT('#'), TEXT(' '), TEXT(':'), TEXT('/') })
	{
		Name.ReplaceCharInline(Bad, TEXT('_'));
	}
	return Name.IsEmpty() ? FString(TEXT("玩家")) : Name;
}

void UCWGameInstance::StartSinglePlayer(int32 Difficulty)
{
	if (IsTransitionPending()) return;
	bLocalTravelPending = true;
	const FString Options = FString::Printf(TEXT("mode=single?difficulty=%d?Name=%s"), FMath::Clamp(Difficulty, 0, 2), *SanitizedName());
	UGameplayStatics::OpenLevel(this, FName(*GetBattleMapPath()), true, Options);
}

void UCWGameInstance::HostRoom()
{
	if (IsTransitionPending()) return;
	bLocalTravelPending = true;
	const FString Options = FString::Printf(TEXT("listen?mode=lobby?Name=%s"), *SanitizedName());
	UGameplayStatics::OpenLevel(this, FName(*GetBattleMapPath()), true, Options);
}

bool UCWGameInstance::JoinRoom(const FString& Address, FText& OutError)
{
	if (IsTransitionPending())
	{
		OutError = LOCTEXT("JoinAlreadyPending", "正在进入房间，请等待；如需更换地址，请先取消连接");
		return false;
	}
	FString Host = Address.TrimStartAndEnd();
	if (Host.IsEmpty())
	{
		OutError = LOCTEXT("JoinEmpty", "请输入主机地址");
		return false;
	}
	if (!Host.Contains(TEXT(":")))
	{
		Host += FString::Printf(TEXT(":%d"), DefaultPort);
	}
	APlayerController* PC = GetFirstLocalPlayerController();
	if (!PC)
	{
		OutError = LOCTEXT("JoinNoPlayer", "本地玩家未就绪");
		return false;
	}
	JoinAddress = Host;
	bConnecting = true;
	ConnectStartTime = FPlatformTime::Seconds();
	PendingError = FText::GetEmpty();
	UE_LOG(LogCivWar, Log, TEXT("正在连接 %s"), *Host);
	PC->ClientTravel(FString::Printf(TEXT("%s?Name=%s"), *Host, *SanitizedName()), TRAVEL_Absolute);
	return true;
}

void UCWGameInstance::CancelJoin()
{
	if (!bConnecting)
	{
		return;
	}
	bConnecting = false;
	if (GEngine)
	{
		if (UWorld* World = GetWorld())
		{
			GEngine->CancelPending(World);
		}
	}
}

void UCWGameInstance::OpenMainMenu()
{
	bConnecting = false;
	bLocalTravelPending = true;
	UGameplayStatics::OpenLevel(this, FName(*GetBattleMapPath()), true, TEXT("mode=menu"));
}

void UCWGameInstance::ReturnToMainMenuWithError(const FText& Message)
{
	PendingError = Message;
	OpenMainMenu();
}

FText UCWGameInstance::ConsumePendingError()
{
	FText Result = PendingError;
	PendingError = FText::GetEmpty();
	return Result;
}

void UCWGameInstance::HandlePostLoadMap(UWorld* World)
{
	// 成功进入主机地图或返回菜单后，连接流程结束
	bConnecting = false;
	bLocalTravelPending = false;
}

void UCWGameInstance::HandleNetworkFailure(UWorld* World, UNetDriver* NetDriver, ENetworkFailure::Type FailureType, const FString& ErrorString)
{
	UE_LOG(LogCivWar, Warning, TEXT("网络错误 %s：%s"), ENetworkFailure::ToString(FailureType), *ErrorString);
	const bool bWasConnecting = bConnecting;
	bConnecting = false;
	bLocalTravelPending = false;
	switch (FailureType)
	{
	case ENetworkFailure::FailureReceived:
		// 服务器拒绝（房间已满、对局进行中）或主机主动关闭
		PendingError = ErrorString.IsEmpty() || ErrorString.Contains(TEXT("closed"))
			? LOCTEXT("HostClosed", "主机已关闭房间")
			: FText::Format(LOCTEXT("JoinRejected", "加入失败：{0}"), FText::FromString(ErrorString));
		break;
	case ENetworkFailure::ConnectionTimeout:
		PendingError = bWasConnecting ? LOCTEXT("ConnectTimeout", "加入失败：连接主机超时，请检查地址与防火墙")
		                              : LOCTEXT("Timeout", "连接中断：长时间未收到主机数据");
		break;
	case ENetworkFailure::PendingConnectionFailure:
		PendingError = LOCTEXT("PendingFailed", "加入失败：无法连接到主机");
		break;
	case ENetworkFailure::ConnectionLost:
		PendingError = LOCTEXT("ConnectionLost", "连接中断：与主机的连接已断开");
		break;
	case ENetworkFailure::OutdatedClient:
	case ENetworkFailure::OutdatedServer:
		PendingError = LOCTEXT("Outdated", "加入失败：双方游戏版本不一致");
		break;
	default:
		PendingError = FText::Format(LOCTEXT("NetError", "网络错误：{0}"), FText::FromString(ErrorString));
		break;
	}
	// 引擎会把客户端送回默认地图（主菜单），主菜单显示 PendingError
	ScheduleJoinRetry();
}

void UCWGameInstance::ScheduleJoinRetry()
{
	// 仅自动化测试（-cwjoin）：主机可能尚未开始监听，最多重试 3 次
	if (StartupAction != TEXT("join") || !bStartupActionDone || JoinAttempts >= 3)
	{
		return;
	}
	++JoinAttempts;
	bStartupActionDone = false;
	UE_LOG(LogCivWar, Warning, TEXT("自动加入失败，5 秒后第 %d 次重试"), JoinAttempts);
	FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateWeakLambda(this, [this](float) { return RunStartupAction(); }), 5.f);
}

void UCWGameInstance::HandleTravelFailure(UWorld* World, ETravelFailure::Type FailureType, const FString& ErrorString)
{
	UE_LOG(LogCivWar, Warning, TEXT("切换地图失败 %s：%s"), ETravelFailure::ToString(FailureType), *ErrorString);
	bConnecting = false;
	bLocalTravelPending = false;
	PendingError = FText::Format(LOCTEXT("TravelFailed", "加入失败：{0}"),
		FText::FromString(ErrorString.IsEmpty() ? FString(ETravelFailure::ToString(FailureType)) : ErrorString));
	ScheduleJoinRetry();
}

#undef LOCTEXT_NAMESPACE
