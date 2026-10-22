#include "Game/CWLocalPlayer.h"

#include "CivWar.h"
#include "Game/CWGameInstance.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

FString UCWLocalPlayer::GetGameLoginOptions() const
{
	FString Options = Super::GetGameLoginOptions();
	const UCWGameInstance* GI = Cast<UCWGameInstance>(GetGameInstance());
	if (!GI) return Options;

	const FString Name = GI->SanitizedName();
	// ULocalPlayer documents '&' between login options. Its UE 5.8 base
	// implementation returns an empty string, yielding the Name option directly.
	if (!Options.IsEmpty()) Options += TEXT("&");
	Options += FString::Printf(TEXT("Name=%s"), *Name);
#if WITH_EDITOR
	if (FParse::Param(FCommandLine::Get(), TEXT("cwshots")))
	{
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_LOGIN_OPTIONS player_class=CWLocalPlayer nickname=%s"), *Name);
	}
#endif
	return Options;
}
