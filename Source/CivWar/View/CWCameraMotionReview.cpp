#include "View/CWCameraRig.h"

#if WITH_EDITOR
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Game/CWGameState.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWBattleReplicator.h"
#include "Sim/SimState.h"
#include "UnrealClient.h"
#include "View/CWUnitVisual.h"

// Explicit standalone inspection only. Observe the real replicated state and
// rendered actor without issuing commands or altering any animation clocks.
bool ACWCameraRig::UpdateMotionCapture()
{
	if (!FParse::Param(FCommandLine::Get(), TEXT("cwmotioncapture")) ||
		GetNetMode() != NM_Standalone) return false;
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	int32 RequestedDef = -1;
	FParse::Value(FCommandLine::Get(), TEXT("cwmotioncapturedef="), RequestedDef);
	if (!State || State->GetPhase() != ECWMatchPhase::InMatch ||
		State->GetMatchTime() < (RequestedDef >= 0 ? 2.f : 25.f) || !State->GetReplicator()) return false;

	ACWUnitVisual* Unit = nullptr;
	for (TActorIterator<ACWUnitVisual> It(GetWorld()); It; ++It)
	{
		if (MotionCaptureId >= 0 ? It->GetUnitId() == MotionCaptureId :
			(RequestedDef >= 0 ? It->GetDef() == RequestedDef : It->IsChampion()) &&
			It->GetTeam() == 0 && !It->IsDying())
		{
			Unit = *It;
			break;
		}
	}
	if (!Unit) return MotionCaptureId >= 0;
	MotionCaptureId = Unit->GetUnitId();
	const FCWUnitNetItem* Net = nullptr;
	for (const FCWUnitNetItem& Item : State->GetReplicator()->GetUnits().Items)
		if (Item.Id == MotionCaptureId) { Net = &Item; break; }

	ViewTeam = 0;
	SideBlend = 0.f;
	CurrentDistance = TargetDistance = 1700.f;
	CurrentX = TargetX = Unit->GetVisualX();
	PendingPan = 0.f;
	ApplyTransform();
	const float Now = GetWorld()->GetTimeSeconds();
	const bool Moving = bMotionCaptureHasPrevious &&
		FMath::Abs(Unit->GetVisualX() - MotionCapturePreviousX) > 0.2f;
	MotionCapturePreviousX = Unit->GetVisualX();
	bMotionCaptureHasPrevious = true;
	const bool Active[3] = {
		Net && Net->State == static_cast<uint8>(cw::UnitState::Walking) && Moving,
		Net && Net->State == static_cast<uint8>(cw::UnitState::Attacking) && !Unit->IsDying(),
		Unit->IsDying()
	};
	const TCHAR* Names[3] = { TEXT("move"), TEXT("attack"), TEXT("death") };
	const float Intervals[3] = { 0.20f, 0.12f, 0.20f };
	const int32 Counts[3] = { 8, 8, 9 };
	for (int32 Phase = 0; Phase < 3; ++Phase)
	{
		if (MotionCaptureFrames[Phase] >= Counts[Phase]) continue;
		if (MotionCaptureStart[Phase] < 0.f && Active[Phase]) MotionCaptureStart[Phase] = Now;
		if (MotionCaptureStart[Phase] < 0.f) continue;
		// Do not label a transition into another state as continued walking
		// or attack; leave incomplete coverage visible in the receipt.
		if (Phase < 2 && !Active[Phase]) continue;
		const float Elapsed = Now - MotionCaptureStart[Phase];
		if (Elapsed + KINDA_SMALL_NUMBER < MotionCaptureFrames[Phase] * Intervals[Phase]) continue;
		const FString Name = FString::Printf(TEXT("%s_motion_%s_%02d.png"),
			*ArtReviewPrefix, Names[Phase], MotionCaptureFrames[Phase]);
		FScreenshotRequest::RequestScreenshot(Name, false, false);
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_MOTION_IMAGE shot=%s id=%d def=%d phase=%s frame=%d elapsed=%.4f x=%.3f state=%d dying=%d"),
			*Name, MotionCaptureId, Unit->GetDef(), Names[Phase], MotionCaptureFrames[Phase],
			Elapsed, Unit->GetVisualX(), Net ? Net->State : -1, Unit->IsDying());
		++MotionCaptureFrames[Phase];
		break; // One screenshot request per rendered frame.
	}
	return true;
}
#endif
