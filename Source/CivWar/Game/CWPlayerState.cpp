#include "Game/CWPlayerState.h"

#include "Net/UnrealNetwork.h"

void ACWPlayerState::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(ACWPlayerState, Team);
	DOREPLIFETIME(ACWPlayerState, bReady);
}
