#include "View/CWStaticBasePilot.h"

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
	bool ReadVector(const TSharedPtr<FJsonValue>& Value, FVector& Vector)
	{
		const TArray<TSharedPtr<FJsonValue>>* Numbers = nullptr;
		if (!Value.IsValid() || !Value->TryGetArray(Numbers) || Numbers->Num() != 3) return false;
		for (int32 Axis = 0; Axis < 3; ++Axis)
		{
			double Number = 0.0;
			if (!(*Numbers)[Axis].IsValid() || !(*Numbers)[Axis]->TryGetNumber(Number) || !FMath::IsFinite(Number)) return false;
			Vector[Axis] = Number;
		}
		return true;
	}
}

bool CWStaticBasePilot::TryBuild(AActor* Owner, USceneComponent* Parent, int32 Age, int32 Team, FCWBaseRig& Rig)
{
	if (!Owner || !Parent || Age != 0 || FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return false;
	FString Text;
	TSharedPtr<FJsonObject> Config;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/BaseArtPilot.json"))) ||
		!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Config) || !Config.IsValid()) return false;
	bool DefaultRuntimeEnabled = false;
	Config->TryGetBoolField(TEXT("default_runtime_enabled"), DefaultRuntimeEnabled);
	const bool bExplicitPilot = FParse::Param(FCommandLine::Get(), TEXT("cwbasestonepilot"));
	if (!DefaultRuntimeEnabled && !bExplicitPilot) return false;
	bool Enabled = false;
	bool StructuralApproved = false;
	bool PlacementApproved = false;
	FString AssetId;
	FString MeshPath;
	if (!Config->TryGetBoolField(TEXT("enabled"), Enabled) || !Enabled ||
		!Config->TryGetBoolField(TEXT("ue_structural_approved"), StructuralApproved) || !StructuralApproved ||
		!Config->TryGetBoolField(TEXT("placement_approved_for_pilot"), PlacementApproved) || !PlacementApproved ||
		!Config->TryGetStringField(TEXT("asset_id"), AssetId) || AssetId != TEXT("Base_Stone") ||
		!Config->TryGetStringField(TEXT("static_mesh"), MeshPath) ||
		!MeshPath.StartsWith(TEXT("/Game/ArtPilot/tripo_base_stone_pbr_v01/Base_Stone/"))) return false;
	FVector ExpectedMinimum;
	FVector ExpectedMaximum;
	if (!ReadVector(Config->TryGetField(TEXT("expected_minimum_cm")), ExpectedMinimum) ||
		!ReadVector(Config->TryGetField(TEXT("expected_maximum_cm")), ExpectedMaximum)) return false;
	if (ExpectedMinimum.GetAbsMax() > 1000.0 || ExpectedMaximum.GetAbsMax() > 1000.0) return false;
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		if (ExpectedMinimum[Axis] >= ExpectedMaximum[Axis]) return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* MountValues = nullptr;
	if (!Config->TryGetArrayField(TEXT("turret_mounts_cm"), MountValues) || MountValues->Num() != 3) return false;
	TArray<FVector> Mounts;
	for (const TSharedPtr<FJsonValue>& Value : *MountValues)
	{
		FVector Mount;
		if (!ReadVector(Value, Mount) || Mount.X < ExpectedMinimum.X || Mount.X > ExpectedMaximum.X ||
			Mount.Y < ExpectedMinimum.Y || Mount.Y > ExpectedMaximum.Y || Mount.Z <= 0.0 || Mount.Z > ExpectedMaximum.Z) return false;
		Mounts.Add(Mount);
	}
	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *MeshPath);
	if (!Mesh || Mesh->GetStaticMaterials().Num() != 1 || !Mesh->GetMaterial(0)) return false;
	const FBoxSphereBounds Bounds = Mesh->GetBounds();
	if (!(Bounds.Origin - Bounds.BoxExtent).Equals(ExpectedMinimum, 0.05) ||
		!(Bounds.Origin + Bounds.BoxExtent).Equals(ExpectedMaximum, 0.05)) return false;
	FString TeamMaterialPath;
	UMaterialInterface* TeamMaterial = nullptr;
	if (Config->TryGetStringField(TEXT("team_material"), TeamMaterialPath))
	{
		bool TeamMaterialApproved = false;
		if (!Config->TryGetBoolField(TEXT("team_material_approved_for_pilot"), TeamMaterialApproved) || !TeamMaterialApproved ||
			!TeamMaterialPath.StartsWith(TEXT("/Game/ArtPilot/BaseStoneTeam/"))) return false;
		TeamMaterial = LoadObject<UMaterialInterface>(nullptr, *TeamMaterialPath);
		if (!TeamMaterial) return false;
	}
	UStaticMeshComponent* Body = NewObject<UStaticMeshComponent>(Owner);
	Owner->AddInstanceComponent(Body);
	Body->SetupAttachment(Parent);
	Body->SetStaticMesh(Mesh);
	Body->SetRelativeTransform(FTransform::Identity);
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->SetGenerateOverlapEvents(false);
	Body->SetComponentTickEnabled(false);
	if (TeamMaterial)
	{
		UMaterialInstanceDynamic* TeamInstance = Body->CreateDynamicMaterialInstance(0, TeamMaterial);
		if (!TeamInstance)
		{
			Owner->RemoveInstanceComponent(Body);
			Body->DestroyComponent();
			return false;
		}
		TeamInstance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
		TeamInstance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_BASE_TEAM_MATERIAL team=%d material=%s cloth_mask_only=true"), Team, *TeamMaterialPath);
	}
	Body->RegisterComponent();
	Rig.TurretMounts = MoveTemp(Mounts);
	Rig.bTripoBasePilot = true;
	Rig.Height = static_cast<float>(ExpectedMaximum.Z);
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_BASE_STONE_PILOT team=%d mesh=%s min=%s max=%s transform=identity scale=positive_one collision=false approval=controlled_pilot activation=%s production_approved=false"), Team, *MeshPath, *ExpectedMinimum.ToString(), *ExpectedMaximum.ToString(), bExplicitPilot ? TEXT("explicit_pilot") : TEXT("default_runtime"));
	return true;
}
