#include "View/CWSkeletalUnitPresentation.h"

#include "Animation/AnimSequence.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SkeletalMeshSocket.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/Actor.h"
#include "HAL/PlatformProcess.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Net/CWNetTypes.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Sim/SimState.h"
#include "View/CWVisuals.h"
#include "View/CWSmoothUnitAnimInstance.h"

static void TraceUnitArtTiming(FName VisualKey, const TCHAR* Event, int32 UnitId, uint8 Sequence, float StartServer, float ServerNow, float Phase, const TCHAR* Reason, bool bReleasePending, uint8 Outcome, float EndServer)
{
	static const bool bEnabled = FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"));
	if (!bEnabled || StartServer < 0.f) return;
	static const FString Run = [] { FString Value = TEXT("unspecified"); FParse::Value(FCommandLine::Get(), TEXT("cwarttimingrun="), Value); return Value; }();
	const TCHAR* Prefix = VisualKey == FName(TEXT("Unit_StoneAxe")) ? TEXT("CIVWAR_ART_TIMING") : TEXT("CIVWAR_STONE_ERA_TIMING");
	UE_LOG(LogTemp, Display, TEXT("%s run=%s asset=%s role=client event=%s pid=%u id=%d seq=%u start_server=%.6f server_now=%.6f phase=%.6f reason=%s release_pending=%d outcome=%u end_server=%.6f notify_damage=false"),
		Prefix, *Run, *VisualKey.ToString(), Event, FPlatformProcess::GetCurrentProcessId(), UnitId, static_cast<uint32>(Sequence), StartServer, ServerNow, Phase, Reason, bReleasePending ? 1 : 0, static_cast<uint32>(Outcome), EndServer);
}

UCWSkeletalUnitPresentation* UCWSkeletalUnitPresentation::TryCreate(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team)
{
	if (VisualKey != FName(TEXT("Unit_StoneAxe"))) return TryCreateConfigured(Owner, Parent, VisualKey, Team);
	if (VisualKey != FName(TEXT("Unit_StoneAxe")) || FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return nullptr;
	const bool bExplicitPilot = FParse::Param(FCommandLine::Get(), TEXT("cwstoneaxepilot"));
	FString Text;
	TSharedPtr<FJsonObject> Config;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/UnitArtPilot.json"))) ||
		!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Config) || !Config.IsValid()) return nullptr;
	bool bDefaultRuntimeEnabled = false;
	Config->TryGetBoolField(TEXT("default_runtime_enabled"), bDefaultRuntimeEnabled);
	if (!bDefaultRuntimeEnabled && !bExplicitPilot) return nullptr;
	bool bEnabled = false;
	bool bImported = false;
	bool bSocketApproved = false;
	FString AssetId;
	FString BodyPath;
	FString WeaponPath;
	FString SocketName;
	const TSharedPtr<FJsonObject>* AnimationConfig = nullptr;
	if (!Config->TryGetBoolField(TEXT("enabled"), bEnabled) || !bEnabled ||
		!Config->TryGetBoolField(TEXT("ue_structural_approved"), bImported) || !bImported ||
		!Config->TryGetBoolField(TEXT("socket_alignment_approved"), bSocketApproved) || !bSocketApproved ||
		!Config->TryGetStringField(TEXT("asset_id"), AssetId) || AssetId != TEXT("Unit_StoneAxe") ||
		!Config->TryGetStringField(TEXT("skeletal_mesh"), BodyPath) ||
		!Config->TryGetStringField(TEXT("weapon_mesh"), WeaponPath) ||
		!Config->TryGetStringField(TEXT("socket_name"), SocketName) ||
		!Config->TryGetObjectField(TEXT("animations"), AnimationConfig)) return nullptr;
	auto* Mesh = LoadObject<USkeletalMesh>(nullptr, *BodyPath);
	auto* Axe = LoadObject<UStaticMesh>(nullptr, *WeaponPath);
	const USkeletalMeshSocket* Socket = Mesh ? Mesh->FindSocket(FName(*SocketName)) : nullptr;
	if (!Mesh || !Axe || !Socket || Socket->BoneName != FName(TEXT("hand_r"))) return nullptr;
	FString TeamMaterialPath;
	UMaterialInterface* TeamMaterial = nullptr;
	if (Config->TryGetStringField(TEXT("team_material"), TeamMaterialPath))
	{
		if (!TeamMaterialPath.StartsWith(TEXT("/Game/ArtPilot/StoneAxeTeam/")) || Mesh->GetMaterials().Num() != 1) return nullptr;
		TeamMaterial = LoadObject<UMaterialInterface>(nullptr, *TeamMaterialPath);
		if (!TeamMaterial) return nullptr;
	}
	TMap<FName, TObjectPtr<UAnimSequence>> LoadedClips;
	for (const TCHAR* Name : { TEXT("Idle"), TEXT("Move"), TEXT("Attack"), TEXT("Hit"), TEXT("Death") })
	{
		FString Path;
		if (!(*AnimationConfig)->TryGetStringField(Name, Path)) return nullptr;
		auto* Clip = LoadObject<UAnimSequence>(nullptr, *Path);
		if (!Clip || Clip->GetSkeleton() != Mesh->GetSkeleton() || Clip->GetPlayLength() <= 0.f || Clip->bEnableRootMotion) return nullptr;
		LoadedClips.Add(FName(Name), Clip);
	}
	auto* Presentation = NewObject<UCWSkeletalUnitPresentation>(Owner);
	Presentation->Clips = MoveTemp(LoadedClips);
	Presentation->Body = NewObject<USkeletalMeshComponent>(Owner);
	Owner->AddInstanceComponent(Presentation->Body);
	Presentation->Body->SetupAttachment(Parent);
	Presentation->Body->SetSkeletalMesh(Mesh);
	Presentation->Body->SetAnimInstanceClass(UCWSmoothUnitAnimInstance::StaticClass());
	Presentation->Body->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	Presentation->Body->bEnableUpdateRateOptimizations = false;
	Presentation->Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Presentation->Body->SetGenerateOverlapEvents(false);
	Presentation->Body->bSuppressNotifyEventDispatch = true;
	Presentation->Body->RegisterComponent();
	Presentation->Body->SetComponentTickEnabled(false);
	if (TeamMaterial)
	{
		if (UMaterialInstanceDynamic* TeamInstance = Presentation->Body->CreateDynamicMaterialInstance(0, TeamMaterial))
		{
			TeamInstance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
			TeamInstance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
			UE_LOG(LogTemp, Display, TEXT("CIVWAR_STONEAXE_TEAM_MATERIAL team=%d material=%s cloth_mask_only=true"), Team, *TeamMaterialPath);
		}
	}
	Presentation->Weapon = NewObject<UStaticMeshComponent>(Owner);
	Owner->AddInstanceComponent(Presentation->Weapon);
	Presentation->Weapon->SetStaticMesh(Axe);
	Presentation->Weapon->SetupAttachment(Presentation->Body, FName(*SocketName));
	Presentation->Weapon->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Presentation->Weapon->SetGenerateOverlapEvents(false);
	Presentation->Weapon->RegisterComponent();
	Presentation->Sample(TEXT("Idle"), 0.f);
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_STONEAXE_PILOT mesh=%s weapon=%s socket=%s damage_authority=server_only activation=%s"), *BodyPath, *WeaponPath, *SocketName, bExplicitPilot ? TEXT("explicit_pilot") : TEXT("default_config"));
	return Presentation;
}

void UCWSkeletalUnitPresentation::ApplyState(const FCWUnitNetItem& Item, float ServerNow)
{
	UnitId = Item.Id;
	const bool bNewAttack = !bInitialized || Item.AttackSeq != LastAttackSeq || Item.AttackStartServerTime != AttackStartTime;
	const uint8 PreviousOutcome = AttackOutcome;
	AttackOutcome = Item.AttackOutcome;
	AttackEndTime = Item.AttackEndServerTime;
	if (bNewAttack)
	{
		bRestartAttackBlend = bInitialized;
		HitClock = -1.f;
		AttackStartTime = Item.AttackStartServerTime;
		LastAttackSeq = Item.AttackSeq;
		const float Age = GetAttackElapsed(ServerNow);
		bContactConsumed = !bInitialized || Age < 0.f || Age >= ContactTime;
		bReleaseEvidenceConsumed = bContactConsumed;
		bReleasePending = false;
		TraceUnitArtTiming(AssetKey, TEXT("observe"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, Age,
			!bInitialized ? TEXT("initial_snapshot") : (Age < 0.f ? TEXT("expired") : (Age >= ContactTime ? TEXT("late") : TEXT("on_time"))), false, AttackOutcome, AttackEndTime);
	}
	if (AttackOutcome == static_cast<uint8>(cw::AttackOutcome::Cancelled))
	{
		if (bNewAttack || PreviousOutcome != AttackOutcome)
		{
			TraceUnitArtTiming(AssetKey, TEXT("cancel_observed"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, FMath::Max(0.f, ServerNow - AttackStartTime), TEXT("authoritative_cancel"), false, AttackOutcome, AttackEndTime);
		}
		bContactConsumed = true;
		bReleaseEvidenceConsumed = true;
		bReleasePending = false;
	}
	else if (AttackOutcome == static_cast<uint8>(cw::AttackOutcome::Released) && (bNewAttack || PreviousOutcome != AttackOutcome))
	{
		TraceUnitArtTiming(AssetKey, TEXT("release_evidence"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, FMath::Max(0.f, ServerNow - AttackStartTime), TEXT("authoritative_release"), false, AttackOutcome, AttackEndTime);
	}
	if (bInitialized && Item.HitSeq != LastHitSeq)
	{
		HitClock = GetAttackElapsed(ServerNow) < 0.f ? 0.f : -1.f;
		bRestartHitBlend = HitClock >= 0.f;
	}
	LastHitSeq = Item.HitSeq;
	if (!bDying && Item.State == static_cast<uint8>(cw::UnitState::Dying))
	{
		TraceUnitArtTiming(AssetKey, TEXT("suppress"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, GetAttackElapsed(ServerNow), TEXT("death"), false, AttackOutcome, AttackEndTime);
		bDying = true;
		DeathClock = 0.f;
		bReleasePending = false;
		bContactConsumed = true;
		bReleaseEvidenceConsumed = true;
	}
	bInitialized = true;
}

float UCWSkeletalUnitPresentation::GetAttackElapsed(float ServerNow) const
{
	if (bDying || AttackStartTime < 0.f || AttackOutcome == static_cast<uint8>(cw::AttackOutcome::Cancelled)) return -1.f;
	const float Age = FMath::Max(0.f, ServerNow - AttackStartTime);
	return Age < Clips.FindChecked(TEXT("Attack"))->GetPlayLength() ? Age : -1.f;
}

void UCWSkeletalUnitPresentation::Update(float Dt, float Speed, float ServerNow)
{
	if (bDying)
	{
		DeathClock += Dt;
		Sample(TEXT("Death"), DeathClock, Dt);
		return;
	}
	if (HitClock >= 0.f) HitClock += Dt;
	const float AttackAge = GetAttackElapsed(ServerNow);
	if (AttackAge < 0.f && CurrentClip == FName(TEXT("Attack")))
	{
		TraceUnitArtTiming(AssetKey, TEXT("finished"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, FMath::Max(0.f, ServerNow - AttackStartTime), TEXT("attack_pose_ended"), false, AttackOutcome, AttackEndTime);
	}
	if (AttackAge >= 0.f)
	{
		if (CurrentClip != FName(TEXT("Attack")) || (AttackAge >= ContactTime - 0.1f && AttackAge <= ContactTime + 0.15f))
		{
			TraceUnitArtTiming(AssetKey, TEXT("sample"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, AttackAge, TEXT("attack_pose"), bReleasePending, AttackOutcome, AttackEndTime);
		}
		Sample(TEXT("Attack"), AttackAge, Dt);
		if (!bContactConsumed && AttackAge >= ContactTime)
		{
			bContactConsumed = true;
			TraceUnitArtTiming(AssetKey, TEXT("contact_pose"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, AttackAge, TEXT("pose_only_no_hit_claim"), false, AttackOutcome, AttackEndTime);
		}
		if (!bReleaseEvidenceConsumed && AttackOutcome == static_cast<uint8>(cw::AttackOutcome::Released) && AttackEndTime >= AttackStartTime && ServerNow >= AttackEndTime && AttackAge >= ContactTime)
		{
			bReleaseEvidenceConsumed = true;
			bReleasePending = AttackAge - ContactTime <= 0.1f && ServerNow - AttackEndTime <= 0.1f;
			TraceUnitArtTiming(AssetKey, bReleasePending ? TEXT("contact") : TEXT("release_skipped"), UnitId, LastAttackSeq, AttackStartTime, ServerNow, AttackAge, TEXT("authoritative_release"), bReleasePending, AttackOutcome, AttackEndTime);
		}
	}
	else if (HitClock >= 0.f && HitClock < Clips.FindChecked(TEXT("Hit"))->GetPlayLength()) Sample(TEXT("Hit"), HitClock, Dt);
	else
	{
		// Separate start/stop thresholds prevent quantized snapshots toggling poses.
		bMoving = bMoving ? Speed > 3.f : Speed > 8.f;
		if (bMoving)
		{
			MoveClock = FMath::Fmod(MoveClock + Dt * Speed / ReferenceMoveSpeed, Clips.FindChecked(TEXT("Move"))->GetPlayLength());
			Sample(TEXT("Move"), MoveClock, Dt);
		}
		else
		{
			IdleClock = FMath::Fmod(IdleClock + Dt, Clips.FindChecked(TEXT("Idle"))->GetPlayLength());
			Sample(TEXT("Idle"), IdleClock, Dt);
		}
	}
}

void UCWSkeletalUnitPresentation::Sample(FName ClipName, float Time, float Dt)
{
	UAnimSequence* Clip = Clips.FindChecked(ClipName);
	const bool bChanged = CurrentClip != ClipName;
	const bool bAttack = ClipName == FName(TEXT("Attack"));
	const bool bHit = ClipName == FName(TEXT("Hit"));
	const bool bRestart = (bAttack && bRestartAttackBlend) || (bHit && bRestartHitBlend);
	float BlendDuration = ClipName == FName(TEXT("Death")) ? 0.1f : (bHit ? 0.06f : 0.14f);
	// Late snapshots must still present the unblended release pose. A transition
	// cannot postpone the weapon/muzzle or the server's existing contact event.
	if (bAttack) BlendDuration = FMath::Min(0.1f, FMath::Max(0.f, ContactTime - Time - 0.03f));
	if (CurrentClip.IsNone()) BlendDuration = 0.f;
	if ((bChanged || bRestart) && UnitId != 0 && FParse::Param(FCommandLine::Get(), TEXT("cwarttiming")))
	{
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_UNIT_POSE id=%d asset=%s from=%s to=%s phase=%.4f blend=%.4f restart=%d"),
			UnitId, *AssetKey.ToString(), *CurrentClip.ToString(), *ClipName.ToString(), Time, BlendDuration, bRestart ? 1 : 0);
	}
	auto SamplePart = [&](USkeletalMeshComponent* Component, UAnimSequence* PartClip, float PartTime)
	{
		UCWSmoothUnitAnimInstance* Instance = CastChecked<UCWSmoothUnitAnimInstance>(Component->GetSingleNodeInstance());
		Instance->PrepareBlend(bChanged || bRestart, BlendDuration, Dt);
		if (bChanged) Component->SetAnimation(PartClip);
		Component->SetPosition(FMath::Clamp(PartTime, 0.f, PartClip->GetPlayLength()), false);
		Component->TickAnimation(0.f, false);
		Component->RefreshBoneTransforms();
		Component->UpdateComponentToWorld();
	};
	SamplePart(Body, Clip, Time);
	// Parent parts are listed first, so a rider samples its saddle's current pose.
	const float Phase = FMath::Clamp(Time / Clip->GetPlayLength(), 0.f, 1.f);
	for (FCWSkeletalArtPart& Part : AdditionalParts)
	{
		UAnimSequence* PartClip = Part.Clips.FindChecked(ClipName);
		SamplePart(Part.Component, PartClip, Phase * PartClip->GetPlayLength());
	}
	CurrentClip = ClipName;
	if (bAttack) bRestartAttackBlend = false;
	if (bHit) bRestartHitBlend = false;
}

float UCWSkeletalUnitPresentation::GetDeathDuration() const
{
	return Clips.FindChecked(TEXT("Death"))->GetPlayLength();
}

void UCWSkeletalUnitPresentation::DescribeRig(FCWUnitRig& Rig) const
{
	Rig.Height = VisualHeight;
	Rig.Style = AttackStyle;
	Rig.StrideLength = StrideLength;
	Rig.bQuadruped = bQuadruped || AssetKey == FName(TEXT("Unit_BeastRider"));
	Rig.bVehicle = bVehicle;
	Rig.Muzzle = MuzzleAnchor;
}

FVector UCWSkeletalUnitPresentation::GetMuzzleLocation() const
{
	return MuzzlePart->GetSocketLocation(MuzzleSocket);
}

bool UCWSkeletalUnitPresentation::ConsumeReleaseEvent()
{
	const bool bResult = bReleasePending;
	bReleasePending = false;
	return bResult;
}
