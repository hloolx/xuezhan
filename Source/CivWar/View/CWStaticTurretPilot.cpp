#include "View/CWStaticTurretPilot.h"

#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "View/CWModels.h"
#include "View/CWVisuals.h"

namespace
{
	float Transition(float Start, float End, float Alpha)
	{
		const float Clamped = FMath::Clamp(Alpha, 0.f, 1.f);
		return FMath::Lerp(Start, End, Clamped * Clamped * (3.f - 2.f * Clamped));
	}

	UStaticMeshComponent* AddMesh(AActor* Owner, USceneComponent* Parent, UStaticMesh* Mesh, const FVector& Location)
	{
		UStaticMeshComponent* Component = NewObject<UStaticMeshComponent>(Owner);
		Owner->AddInstanceComponent(Component);
		Component->SetMobility(EComponentMobility::Movable);
		Component->SetupAttachment(Parent);
		Component->SetStaticMesh(Mesh);
		Component->SetRelativeLocation(Location);
		Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Component->SetGenerateOverlapEvents(false);
		Component->SetComponentTickEnabled(false);
		Component->RegisterComponent();
		return Component;
	}

	UStaticMesh* LoadMesh(const TSharedPtr<FJsonObject>& Meshes, const FString& Name)
	{
		FString Path;
		if (!Meshes->TryGetStringField(Name, Path) || !Path.StartsWith(TEXT("/Game/ArtPilot/RockTower/"))) return nullptr;
		UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *Path);
		if (!Mesh || Mesh->GetStaticMaterials().IsEmpty()) return nullptr;
		for (int32 Slot = 0; Slot < Mesh->GetStaticMaterials().Num(); ++Slot)
		{
			if (!Mesh->GetMaterial(Slot)) return nullptr;
		}
		return Mesh;
	}

	void ApplyPose(FCWTurretRig& Rig, const CWStaticTurretPilot::FRockTowerPose& Pose)
	{
		Rig.Aim->SetRelativeRotation(FRotator(Pose.Pitch, 0.f, 0.f));
		Rig.LoadedStone->SetVisibility(Pose.bStoneVisible);
	}
}

CWStaticTurretPilot::FRockTowerPose CWStaticTurretPilot::SamplePose(float Elapsed)
{
	FRockTowerPose Pose;
	if (!FMath::IsFinite(Elapsed) || Elapsed < 0.f) return Pose;
	Pose.bStoneVisible = Elapsed >= 1.20f;
	if (Elapsed < 0.16f) Pose.Pitch = Transition(35.f, -40.f, Elapsed / 0.16f);
	else if (Elapsed < 0.30f) Pose.Pitch = -40.f;
	else if (Elapsed < 0.95f) Pose.Pitch = Transition(-40.f, 65.f, (Elapsed - 0.30f) / 0.65f);
	else if (Elapsed < 1.30f) Pose.Pitch = 65.f;
	else if (Elapsed < 2.10f) Pose.Pitch = Transition(65.f, 35.f, (Elapsed - 1.30f) / 0.80f);
	return Pose;
}

bool CWStaticTurretPilot::TryBuild(AActor* Owner, USceneComponent* Mount, FName VisualKey, int32 Team, int32 Slot, bool bBasePilot, FCWTurretRig& Rig)
{
	if (!Owner || !Mount || !bBasePilot || VisualKey != FName(TEXT("Turret_RockTower")) || Slot < 0 || Slot >= 3 ||
		FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return false;
	FString Text;
	TSharedPtr<FJsonObject> Config;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/TurretArtPilot.json"))) ||
		!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Config) || !Config.IsValid()) return false;
	bool DefaultRuntimeEnabled = false;
	Config->TryGetBoolField(TEXT("default_runtime_enabled"), DefaultRuntimeEnabled);
	const bool bExplicitPilot = FParse::Param(FCommandLine::Get(), TEXT("cwbasestonepilot")) &&
		FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerpilot"));
	if (!DefaultRuntimeEnabled && !bExplicitPilot) return false;
	for (const TCHAR* Gate : {TEXT("enabled"), TEXT("ue_structural_approved"), TEXT("assembly_approved_for_pilot")})
	{
		bool Approved = false;
		if (!Config->TryGetBoolField(Gate, Approved) || !Approved) return false;
	}
	FString AssetId;
	const TSharedPtr<FJsonObject>* Meshes = nullptr;
	if (!Config->TryGetStringField(TEXT("asset_id"), AssetId) || AssetId != TEXT("Turret_RockTower") ||
		!Config->TryGetObjectField(TEXT("meshes"), Meshes)) return false;
	UStaticMesh* Frame = LoadMesh(*Meshes, TEXT("Frame"));
	UStaticMesh* Arm = LoadMesh(*Meshes, TEXT("Arm"));
	UStaticMesh* Stone = LoadMesh(*Meshes, TEXT("Stone"));
	UStaticMesh* Cloth = LoadMesh(*Meshes, TEXT("Cloth"));
	const TCHAR* AdapterNames[] = {TEXT("Adapter_front_negative_y"), TEXT("Adapter_front_positive_y"), TEXT("Adapter_rear")};
	UStaticMesh* Adapter = LoadMesh(*Meshes, AdapterNames[Slot]);
	if (!Frame || !Arm || !Stone || !Cloth || !Adapter || Cloth->GetStaticMaterials().Num() != 1 || !CWVisual::HasStylizedMaterial()) return false;
	UMaterialInstanceDynamic* TeamCloth = CWVisual::MakeMaterial(Owner, CWVisual::TeamColor(Team), 0.66f, 0.f);
	if (!TeamCloth) return false;
	const float UpperLiftCm[] = {1.5f, 0.8f, 1.f};
	AddMesh(Owner, Mount, Adapter, FVector::ZeroVector);
	Rig.Root = CWVisual::AddPivot(Owner, Mount, FVector(0.f, 0.f, UpperLiftCm[Slot]));
	AddMesh(Owner, Rig.Root, Frame, FVector::ZeroVector);
	UStaticMeshComponent* ClothComponent = AddMesh(Owner, Rig.Root, Cloth, FVector::ZeroVector);
	ClothComponent->SetMaterial(0, TeamCloth);
	Rig.Aim = CWVisual::AddPivot(Owner, Rig.Root, FVector(-4.f, 0.f, 51.f), FRotator(35.f, 0.f, 0.f));
	AddMesh(Owner, Rig.Aim, Arm, FVector::ZeroVector);
	Rig.LoadedStone = AddMesh(Owner, Rig.Aim, Stone, FVector(3.5f, 0.f, 57.f));
	Rig.Muzzle = CWVisual::AddPivot(Owner, Rig.Aim, FVector(3.5f, 0.f, 57.f));
	Rig.bRockTowerPilot = true;
	Rig.PilotFireElapsed = -1.f;
	ApplyPose(Rig, SamplePose(-1.f));
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ROCK_TOWER_PILOT team=%d slot=%d components=5 lift_cm=%.3f scale=positive_one approval=controlled_pilot activation=%s production_approved=false"), Team, Slot, UpperLiftCm[Slot], bExplicitPilot ? TEXT("explicit_pilot") : TEXT("default_runtime"));
	return true;
}

void CWStaticTurretPilot::BeginFire(FCWTurretRig& Rig)
{
	if (!Rig.bRockTowerPilot || !Rig.Aim || !Rig.LoadedStone) return;
	Rig.PilotFireElapsed = 0.f;
	ApplyPose(Rig, SamplePose(0.f));
}

bool CWStaticTurretPilot::Update(FCWTurretRig& Rig, float DeltaSeconds)
{
	if (!Rig.bRockTowerPilot || !Rig.Aim || !Rig.LoadedStone) return false;
	if (Rig.PilotFireElapsed >= 0.f && FMath::IsFinite(DeltaSeconds) && DeltaSeconds > 0.f)
	{
		Rig.PilotFireElapsed = FMath::Min(2.10f, Rig.PilotFireElapsed + DeltaSeconds);
		ApplyPose(Rig, SamplePose(Rig.PilotFireElapsed));
	}
	return true;
}
