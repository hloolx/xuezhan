#include "View/CWCameraRig.h"

#include "Camera/CameraComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Game/CWGameState.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "UnrealClient.h"
#include "View/CWUnitVisual.h"
#include "View/CWMenuShowcase.h"

ACWCameraRig::ACWCameraRig()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Camera = CreateDefaultSubobject<UCameraComponent>(TEXT("Camera"));
	Camera->SetupAttachment(Root);
	Camera->SetFieldOfView(45.f);
	// 关闭镜头自带的运动模糊与景深，保证战术阅读
	Camera->PostProcessSettings.bOverride_MotionBlurAmount = true;
	Camera->PostProcessSettings.MotionBlurAmount = 0.f;
	Camera->PostProcessSettings.bOverride_DepthOfFieldFocalDistance = true;
	Camera->PostProcessSettings.DepthOfFieldFocalDistance = 0.f;
	SetReplicates(false);
	bArtReview = FParse::Param(FCommandLine::Get(), TEXT("cwartreview"));
	FParse::Value(FCommandLine::Get(), TEXT("cwshotprefix="), ArtReviewPrefix);
}

void ACWCameraRig::SetViewTeam(int32 Team)
{
	if (bArtReview && ArtReviewElapsed > 0.f) return;
	ViewTeam = Team == 1 ? 1 : 0;
	if (!bTeamInitialized)
	{
		bTeamInitialized = true;
		SideBlend = static_cast<float>(ViewTeam);
	}
}

void ACWCameraRig::AddPanInput(float ScreenAxis)
{
	PendingPan += ScreenAxis;
	bAttract = false;
}

void ACWCameraRig::AddZoomInput(float Axis)
{
	TargetDistance = FMath::Clamp(TargetDistance - Axis * 220.f, MinDistance, MaxDistance);
}

void ACWCameraRig::FocusX(float X, bool bInstant)
{
	TargetX = FMath::Clamp(X, -300.f, LaneLength + 300.f);
	if (bInstant)
	{
		CurrentX = TargetX;
	}
}

void ACWCameraRig::StopManualMovement()
{
	PendingPan = 0.f;
	TargetX = CurrentX;
	TargetDistance = CurrentDistance;
}

void ACWCameraRig::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
#if WITH_EDITOR
	if (UpdateMotionCapture()) return;
#endif
	if (UpdateArtReview(DeltaSeconds)) return;
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	if (State && State->GetPhase() == ECWMatchPhase::Menu)
	{
		if (!IsValid(MenuShowcase))
		{
			MenuShowcase = ACWMenuShowcase::Get(GetWorld());
			if (!MenuShowcase) MenuShowcase = GetWorld()->SpawnActor<ACWMenuShowcase>();
		}
		if (MenuShowcase)
		{
			PendingPan = 0.f;
			bMenuPresentation = true;
			Camera->PostProcessSettings.bOverride_AutoExposureBias = true;
			Camera->PostProcessSettings.AutoExposureBias = -0.35f;
			const FVector Focus = MenuShowcase->GetCameraFocus();
			const FVector Offset(0.f, 2300.f, 720.f);
			SetActorLocation(Focus + Offset);
			SetActorRotation((-Offset).Rotation());
			return;
		}
	}
	else if (bMenuPresentation)
	{
		if (IsValid(MenuShowcase)) MenuShowcase->Destroy();
		MenuShowcase = nullptr;
		Camera->PostProcessSettings.bOverride_AutoExposureBias = false;
		bMenuPresentation = false;
	}
	if (bAttract)
	{
		AttractTime += DeltaSeconds;
		TargetX = LaneLength * 0.5f + FMath::Sin(AttractTime * 0.08f) * LaneLength * 0.35f;
	}
	if (PendingPan != 0.f)
	{
		const float Zoom = CurrentDistance / 2300.f;
		TargetX = FMath::Clamp(TargetX + FMath::Clamp(PendingPan, -1.f, 1.f) * ScreenRightSign() * PanSpeed * Zoom * DeltaSeconds,
			-300.f, LaneLength + 300.f);
		PendingPan = 0.f;
	}
	CurrentX = FMath::FInterpTo(CurrentX, TargetX, DeltaSeconds, 8.f);
	CurrentDistance = FMath::FInterpTo(CurrentDistance, TargetDistance, DeltaSeconds, 8.f);
	SideBlend = FMath::FInterpTo(SideBlend, static_cast<float>(ViewTeam), DeltaSeconds, 4.f);
	ApplyTransform();
}

bool ACWCameraRig::UpdateArtReview(float DeltaSeconds)
{
	if (!bArtReview) return false;
#if WITH_EDITOR
	if (RockTowerReviewTeam >= 0)
	{
		ViewTeam = RockTowerReviewTeam;
		SideBlend = static_cast<float>(ViewTeam);
		CurrentDistance = TargetDistance = 1700.f;
		CurrentX = TargetX = ViewTeam == 0 ? 0.f : LaneLength;
		PendingPan = 0.f;
		ApplyTransform();
		return true;
	}
#endif
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	float ReviewStart = 12.f;
	FParse::Value(FCommandLine::Get(), TEXT("cwartreviewstart="), ReviewStart);
	ReviewStart = FMath::IsFinite(ReviewStart) ? FMath::Clamp(ReviewStart, 12.f, 120.f) : 12.f;
	if (!State || State->GetPhase() != ECWMatchPhase::InMatch || State->GetMatchTime() < ReviewStart) return false;
	ArtReviewElapsed += DeltaSeconds;
	const bool bReviewEnds = FParse::Param(FCommandLine::Get(), TEXT("cwartreviewends"));
	const bool bReviewBase = !bReviewEnds && FParse::Param(FCommandLine::Get(), TEXT("cwbaseartreview"));
	const bool bReviewUnit = !bReviewEnds && !bReviewBase && FParse::Param(FCommandLine::Get(), TEXT("cwunitartreview"));
	const int32 Stage = FMath::Min(FMath::FloorToInt(ArtReviewElapsed / 8.f), bReviewEnds ? 3 : 5);
	const float Distances[] = { 1300.f, 2300.f, 3400.f };
	ViewTeam = bReviewEnds ? Stage / 2 : Stage / 3;
	SideBlend = static_cast<float>(ViewTeam);
	CurrentDistance = TargetDistance = bReviewEnds ? 3400.f : Distances[Stage % 3];
	CurrentX = TargetX = bReviewEnds ? (Stage % 2 == 0 ? -300.f : LaneLength + 300.f) : LaneLength * 0.5f;
	if (bReviewBase) CurrentX = TargetX = ViewTeam == 0 ? 0.f : LaneLength;
	ACWUnitVisual* ReviewUnit = nullptr;
	if (bReviewUnit)
	{
		for (TActorIterator<ACWUnitVisual> Candidate(GetWorld()); Candidate; ++Candidate)
		{
			if (!Candidate->HasSkeletalArtPilot() || Candidate->IsDying() || Candidate->GetTeam() != ViewTeam) continue;
			if (!ReviewUnit || Candidate->GetUnitId() < ReviewUnit->GetUnitId()) ReviewUnit = *Candidate;
		}
		if (!ReviewUnit)
		{
			ArtReviewElapsed -= DeltaSeconds;
			return true;
		}
		CurrentX = TargetX = FMath::Clamp(ReviewUnit->GetVisualX(), -300.f, LaneLength + 300.f);
	}
	PendingPan = 0.f;
	ApplyTransform();
	if (Stage != ArtReviewShot && ArtReviewElapsed >= Stage * 8.f + 3.f)
	{
		ArtReviewShot = Stage;
		const FString Name = bReviewEnds ? FString::Printf(TEXT("%s_team%d_distance%d_focus%d.png"), *ArtReviewPrefix, ViewTeam, FMath::RoundToInt(CurrentDistance), FMath::RoundToInt(CurrentX)) :
			FString::Printf(TEXT("%s_team%d_distance%d.png"), *ArtReviewPrefix, ViewTeam, FMath::RoundToInt(CurrentDistance));
		const bool bShowReviewUI = !bReviewBase || !FParse::Param(FCommandLine::Get(), TEXT("cwbasearthideui"));
		FScreenshotRequest::RequestScreenshot(Name, bShowReviewUI, false);
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_REVIEW shot=%s team=%d distance=%.0f focus=%.0f location=%s rotation=%s"),
			*Name, ViewTeam, CurrentDistance, CurrentX, *GetActorLocation().ToString(), *GetActorRotation().ToString());
		if (ReviewUnit)
		{
			UE_LOG(LogTemp, Display, TEXT("CIVWAR_UNIT_ART_REVIEW shot=%s id=%d unit_team=%d visual_x=%.3f actor_scale=%s actor_rotation=%s"),
				*Name, ReviewUnit->GetUnitId(), ReviewUnit->GetTeam(), ReviewUnit->GetVisualX(), *ReviewUnit->GetActorScale3D().ToString(), *ReviewUnit->GetActorRotation().ToString());
		}
	}
	return true;
}

#if WITH_EDITOR
void ACWCameraRig::CaptureRockTowerReview(int32 Team, int32 Slot, uint8 Sequence, float Elapsed, float Pitch, bool bStoneVisible)
{
	int32 Defender = -1;
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	if (!bArtReview || Slot != 0 || GetNetMode() != NM_Standalone || !State || State->GetMatchTime() < 60.f ||
		!FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerfixture")) ||
		!FParse::Param(FCommandLine::Get(), TEXT("cwrocktowercyclecapture")) ||
		!FParse::Value(FCommandLine::Get(), TEXT("cwrocktowerdefender="), Defender) || Defender != Team ||
		!FMath::IsFinite(Elapsed) || Elapsed < 0.f) return;
	if (RockTowerReviewSequence < 0)
	{
		if (Elapsed > 0.10f) return;
		RockTowerReviewSequence = Sequence;
		RockTowerReviewTeam = Team;
	}
	if (Sequence != RockTowerReviewSequence) return;
	const int32 Phase = Elapsed >= 2.10f ? 5 : Elapsed >= 1.20f ? 4 : Elapsed >= 0.95f ? 3 : Elapsed >= 0.30f ? 2 : Elapsed >= 0.16f ? 1 : 0;
	if ((RockTowerReviewMask & (1 << Phase)) != 0) return;
	RockTowerReviewMask |= 1 << Phase;
	UpdateArtReview(0.f);
	const FString Name = FString::Printf(TEXT("%s_cycle_team%d_phase%d.png"), *ArtReviewPrefix, Team, Phase);
	FScreenshotRequest::RequestScreenshot(Name, false, false);
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ROCK_TOWER_IMAGE shot=%s team=%d slot=%d seq=%u phase=%d elapsed=%.6f pitch=%.5f stone_visible=%d camera=%s rotation=%s distance=1700"),
		*Name, Team, Slot, static_cast<uint32>(Sequence), Phase, Elapsed, Pitch, bStoneVisible ? 1 : 0,
		*GetActorLocation().ToString(), *GetActorRotation().ToString());
}
#endif

void ACWCameraRig::ApplyTransform()
{
	// 观察点略高于地面，镜头位于战线一侧并向下俯视
	const FVector Focus(CurrentX, 0.f, 110.f);
	const float Pitch = FMath::DegreesToRadians(PitchDegrees);
	// UE 是左手坐标系：朝 -Y 看时屏幕右侧是 +X。阵营 0 的镜头放在 +Y 侧朝 -Y 看，己方基地（X=0）显示在左侧、向右推进；
	// 阵营 1 的镜头放在 -Y 侧朝 +Y 看，屏幕右侧是 -X，同样看到己方基地在左侧。
	const float Yaw = PI * SideBlend; // 0：从 +Y 看向 -Y；π：从 -Y 看向 +Y
	const FVector Back(-FMath::Sin(Yaw), FMath::Cos(Yaw), 0.f); // (0,1,0) 绕 Z 轴旋转 Yaw
	const FVector Offset = Back * (FMath::Cos(Pitch) * CurrentDistance) + FVector(0.f, 0.f, FMath::Sin(Pitch) * CurrentDistance);
	const FVector Location = Focus + Offset;
	SetActorLocation(Location);
	SetActorRotation((Focus - Location).Rotation());
}
