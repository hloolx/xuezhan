#include "View/CWBattlefield.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Dom/JsonObject.h"
#include "Math/RandomStream.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "View/CWVisuals.h"

UInstancedStaticMeshComponent* ACWBattlefield::MakeInstanced(int32 ShapeIndex, const FLinearColor& Color, float Roughness, bool bShadow)
{
	UInstancedStaticMeshComponent* ISM = NewObject<UInstancedStaticMeshComponent>(this);
	ISM->SetupAttachment(Root);
	ISM->SetStaticMesh(CWVisual::GetShape(static_cast<CWVisual::EShape>(ShapeIndex)));
	ISM->SetMaterial(0, CWVisual::MakeMaterial(ISM, Color, Roughness, 0.f));
	ISM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	ISM->SetCastShadow(bShadow);
	ISM->RegisterComponent();
	return ISM;
}

void ACWBattlefield::LoadEnvironmentArt()
{
	EnvironmentMeshes.Reset();
	EnvironmentPreserveShape.Reset();
	bPartialArtReview = false;
	FString Text;
	const bool bLegacyArt = FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"));
	FString Path = FPaths::ProjectContentDir() / (bLegacyArt ? TEXT("Data/EnvironmentArtLegacy.json") : TEXT("Data/EnvironmentArt.json"));
	FString ReviewPath;
	const bool bInteractivePreview = FParse::Param(FCommandLine::Get(), TEXT("cwartpreview"));
	const bool bReviewOverride = !bLegacyArt && (bInteractivePreview || FParse::Param(FCommandLine::Get(), TEXT("cwartreview"))) &&
		FParse::Value(FCommandLine::Get(), TEXT("cwartenvironment="), ReviewPath);
	if (bReviewOverride)
	{
		FPaths::NormalizeFilename(ReviewPath);
		if (!ReviewPath.StartsWith(TEXT("RawAssets/Art/Tripo_v01/reviews/")) || ReviewPath.Contains(TEXT("..")))
		{
			UE_LOG(LogTemp, Error, TEXT("CIVWAR_PARTIAL_ENV_REVIEW invalid_review_path"));
			return;
		}
		Path = FPaths::ProjectDir() / ReviewPath;
	}
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		UE_LOG(LogTemp, Display, TEXT("[EnvironmentArt] No imported manifest; using primitive environment"));
		return;
	}
	TSharedPtr<FJsonObject> Document;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Document) || !Document.IsValid())
	{
		UE_LOG(LogTemp, Warning, TEXT("[EnvironmentArt] Invalid JSON; using primitive environment"));
		return;
	}
	const TSharedPtr<FJsonObject>* Assets = nullptr;
	if (!Document->TryGetObjectField(TEXT("assets"), Assets)) return;
	if (bReviewOverride)
	{
		if (!Document->TryGetBoolField(TEXT("partial_review_only"), bPartialArtReview) || !bPartialArtReview ||
			(*Assets)->Values.Num() != 6 || (*Assets)->HasField(TEXT("Env_GrassClump")))
		{
			bPartialArtReview = false;
			UE_LOG(LogTemp, Error, TEXT("CIVWAR_PARTIAL_ENV_REVIEW invalid_six_asset_review_manifest"));
			return;
		}
	}
	const TCHAR* KnownIds[] = { TEXT("Env_BoulderA"), TEXT("Env_BoulderB"), TEXT("Env_RockSlab"), TEXT("Env_Shrub"),
		TEXT("Env_Pine"), TEXT("Env_Broadleaf"), TEXT("Env_GrassClump") };
	for (const TCHAR* Id : KnownIds)
	{
		const TSharedPtr<FJsonObject>* Entry = nullptr;
		FString ObjectPath;
		if (!(*Assets)->TryGetObjectField(Id, Entry) || !(*Entry)->TryGetStringField(TEXT("object_path"), ObjectPath)) continue;
		// The generated map is limited to the isolated art directory, never arbitrary packages.
		if (!ObjectPath.StartsWith(TEXT("/Game/ArtPilot/"))) continue;
		UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *ObjectPath);
		if (!Mesh) continue;
		const FVector Extent = Mesh->GetBounds().BoxExtent;
		if (Extent.ContainsNaN() || Extent.GetMin() <= KINDA_SMALL_NUMBER) continue;
		EnvironmentMeshes.Add(FName(Id), Mesh);
		FString Source;
		if ((*Entry)->TryGetStringField(TEXT("source"), Source))
		{
			FPaths::NormalizeFilename(Source);
			if (Source.Contains(TEXT("/tripo_processed/"))) EnvironmentPreserveShape.Add(FName(Id));
		}
	}
	UE_LOG(LogTemp, Display, TEXT("[EnvironmentArt] Loaded %d/7 mother meshes; missing entries retain primitives"), EnvironmentMeshes.Num());
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ENVIRONMENT_ART mode=%s loaded=%d tripo=%d grass=%s manifest=%s production_approved=false"),
		bLegacyArt ? TEXT("legacy") : (bReviewOverride ? TEXT("explicit_review") : TEXT("default")),
		EnvironmentMeshes.Num(), EnvironmentPreserveShape.Num(),
		bLegacyArt && !bPartialArtReview ? TEXT("explicit_legacy") : TEXT("hidden_deferred"), *Path);
	if (bPartialArtReview) UE_LOG(LogTemp, Display, TEXT("CIVWAR_PARTIAL_ENV_REVIEW loaded=%d omitted=Env_GrassClump permanent_mapping_unchanged=true"), EnvironmentMeshes.Num());
	if (bInteractivePreview && bPartialArtReview)
	{
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_PREVIEW environment_meshes=%d camera=player scope=partial_preview"), EnvironmentMeshes.Num());
	}
}

UInstancedStaticMeshComponent* ACWBattlefield::MakeEnvironmentInstanced(FName AssetId, bool bShadow)
{
	const TObjectPtr<UStaticMesh>* Mesh = EnvironmentMeshes.Find(AssetId);
	if (!Mesh || !Mesh->Get()) return nullptr;
	UInstancedStaticMeshComponent* ISM = NewObject<UInstancedStaticMeshComponent>(this);
	ISM->SetupAttachment(Root);
	ISM->SetStaticMesh(Mesh->Get());
	ISM->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	ISM->SetCastShadow(bShadow);
	ISM->RegisterComponent();
	return ISM;
}

void ACWBattlefield::BuildProps()
{
	LoadEnvironmentArt();
	FRandomStream Rand(20261019);
	const int32 Cube = static_cast<int32>(CWVisual::EShape::Cube);
	const int32 Sphere = static_cast<int32>(CWVisual::EShape::Sphere);
	const int32 Cylinder = static_cast<int32>(CWVisual::EShape::Cylinder);
	const int32 Cone = static_cast<int32>(CWVisual::EShape::Cone);

	TSet<UInstancedStaticMeshComponent*> AuthoredInstances;
	TSet<UInstancedStaticMeshComponent*> UniformInstances;
	auto Mother = [this, &AuthoredInstances, &UniformInstances](const TCHAR* Id, bool bShadow)
	{
		UInstancedStaticMeshComponent* ISM = MakeEnvironmentInstanced(FName(Id), bShadow);
		if (ISM) AuthoredInstances.Add(ISM);
		if (ISM && EnvironmentPreserveShape.Contains(FName(Id))) UniformInstances.Add(ISM);
		return ISM;
	};
	UInstancedStaticMeshComponent* Rocks = Mother(TEXT("Env_BoulderA"), true);
	if (!Rocks) Rocks = MakeInstanced(Sphere, FLinearColor(0.36f, 0.35f, 0.33f), 0.9f, true);
	UInstancedStaticMeshComponent* WedgeRocks = Mother(TEXT("Env_BoulderB"), true);
	UInstancedStaticMeshComponent* RockBlocks = Mother(TEXT("Env_RockSlab"), true);
	if (!RockBlocks) RockBlocks = MakeInstanced(Cube, FLinearColor(0.30f, 0.29f, 0.28f), 0.9f, true);
	UInstancedStaticMeshComponent* Bushes = Mother(TEXT("Env_Shrub"), true);
	if (!Bushes) Bushes = MakeInstanced(Sphere, FLinearColor(0.10f, 0.24f, 0.06f), 0.9f, true);
	UInstancedStaticMeshComponent* Trunks = MakeInstanced(Cylinder, FLinearColor(0.25f, 0.16f, 0.09f), 0.9f, true);
	UInstancedStaticMeshComponent* Pines = MakeInstanced(Cone, FLinearColor(0.05f, 0.16f, 0.07f), 0.85f, true);
	UInstancedStaticMeshComponent* Canopies = MakeInstanced(Sphere, FLinearColor(0.14f, 0.30f, 0.07f), 0.85f, true);
	UInstancedStaticMeshComponent* Mountains = MakeInstanced(Cone, FLinearColor(0.22f, 0.26f, 0.32f), 0.95f, false);
	UInstancedStaticMeshComponent* Snow = MakeInstanced(Cone, FLinearColor(0.85f, 0.88f, 0.92f), 0.6f, false);
	UInstancedStaticMeshComponent* WholePines = Mother(TEXT("Env_Pine"), true);
	UInstancedStaticMeshComponent* WholeBroadleaf = Mother(TEXT("Env_Broadleaf"), true);
	UInstancedStaticMeshComponent* FarPines = Mother(TEXT("Env_Pine"), false);
	UInstancedStaticMeshComponent* FarBroadleaf = Mother(TEXT("Env_Broadleaf"), false);
	const bool bLegacyArt = FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"));
	// The rejected grass remains available to the explicit legacy comparison,
	// but its narrow prototype spikes are not scattered into the normal game.
	UInstancedStaticMeshComponent* Tufts = nullptr;
	if (bLegacyArt && !bPartialArtReview)
	{
		Tufts = Mother(TEXT("Env_GrassClump"), false);
		if (!Tufts) Tufts = MakeInstanced(Cone, FLinearColor(0.20f, 0.34f, 0.08f), 0.9f, false);
	}

	auto Place = [this, &AuthoredInstances, &UniformInstances](UInstancedStaticMeshComponent* ISM, float X, float Y, float ZOffset, const FVector& Size, float Yaw)
	{
		if (!ISM || !ISM->GetStaticMesh()) return false;
		const FBoxSphereBounds Bounds = ISM->GetStaticMesh()->GetBounds();
		const FVector RequestedScale = Size / (Bounds.BoxExtent * 2.0);
		const bool bUniform = UniformInstances.Contains(ISM);
		const FVector Scale = bUniform ? FVector(RequestedScale.GetMin()) : RequestedScale;
		const FVector Dimensions = Bounds.BoxExtent * 2.0 * Scale.GetAbs();
		// Check the whole rotated footprint, not only its pivot. Nothing new can
		// penetrate the source tile's raised rim or the clear gameplay corridor.
		const float Radius = FVector2D(Dimensions.X, Dimensions.Y).Size() * 0.5f;
		if (FMath::Abs(Y) < 650.f + Radius) return false;
		if (bHasTripoTerrain && X + Radius >= TripoTerrainMinX && X - Radius <= TripoTerrainMaxX &&
			FMath::Abs(Y) - Radius < TripoTerrainHalfWidth + 40.f) return false;
		const float GroundZ = SurfaceGroundHeight(X, Y);
		const float Z = GroundZ + ZOffset;
		if (AuthoredInstances.Contains(ISM))
		{
			// Size is a desired world-space bounding box in cm, not a primitive multiplier.
			// Recenter the actual mesh bounds so ground-pivot exports and centered primitives
			// share the same placement, without accidentally multiplying cm meshes by 100.
			const float AppliedZOffset = bUniform ? ZOffset * (Bounds.BoxExtent.Z * 2.0 * Scale.Z / Size.Z) : ZOffset;
			const FRotator Rotation(0.f, Yaw, 0.f);
			const FVector Position = FVector(X, Y, GroundZ + AppliedZOffset) - Rotation.RotateVector(Bounds.Origin * Scale);
			ISM->AddInstance(FTransform(Rotation, Position, Scale));
			return true;
		}
		ISM->AddInstance(FTransform(FRotator(0.f, Yaw, 0.f), FVector(X, Y, Z), Size / 100.f));
		return true;
	};
	auto PlaceNatural = [&Place](UInstancedStaticMeshComponent* ISM, float X, float Y, float Height, float Yaw, float EmbedFraction)
	{
		if (!ISM || !ISM->GetStaticMesh()) return false;
		const FVector Dimensions = ISM->GetStaticMesh()->GetBounds().BoxExtent * 2.0;
		return Place(ISM, X, Y, Height * (0.5f - EmbedFraction), Dimensions * (Height / Dimensions.Z), Yaw);
	};

	struct FTreeFootprint
	{
		FVector2D Position;
		float Radius;
	};
	TArray<FTreeFootprint> TreeFootprints;
	int32 MidTrees = 0;
	int32 DistantTrees = 0;
	auto PlaceTree = [this, &Place, &PlaceNatural, &TreeFootprints, &MidTrees, &DistantTrees,
		WholePines, WholeBroadleaf, FarPines, FarBroadleaf, Trunks, Pines, Canopies]
		(bool bPine, bool bDistant, float X, float Y, float RequestedHeight, float Yaw)
	{
		UInstancedStaticMeshComponent* ISM = bPine ? (bDistant ? FarPines : WholePines) : (bDistant ? FarBroadleaf : WholeBroadleaf);
		const FVector Dimensions = ISM ? ISM->GetStaticMesh()->GetBounds().BoxExtent * 2.0 : FVector(0.6f, 0.6f, 1.f);
		const float RadiusPerHeight = FVector2D(Dimensions.X, Dimensions.Y).Size() * 0.5f / Dimensions.Z;
		float Height = RequestedHeight;
		if (FMath::Abs(Y) < 4000.f)
		{
			// At the widest 20-degree player camera the same grove may be in the
			// foreground for the other team. Keep its entire crown below the ray
			// to the lane, including ground rise and a 150 cm readability margin.
			const float ClearHeight = (FMath::Abs(Y) * 0.32f - SurfaceGroundHeight(X, Y) - 150.f) / (1.f + RadiusPerHeight * 0.32f);
			Height = FMath::Min(Height, ClearHeight);
		}
		if (Height < 290.f) return false;
		const float Radius = RadiusPerHeight * Height;
		const FVector2D Position(X, Y);
		for (const FTreeFootprint& Existing : TreeFootprints)
		{
			const float Separation = FMath::Max(230.f, (Radius + Existing.Radius) * 0.58f);
			if (FVector2D::DistSquared(Position, Existing.Position) < Separation * Separation) return false;
		}
		bool bPlaced = false;
		if (ISM)
		{
			bPlaced = PlaceNatural(ISM, X, Y, Height, Yaw, 0.015f);
		}
		else
		{
			bPlaced = Place(Trunks, X, Y, Height * 0.12f, FVector(30.f, 30.f, Height * 0.25f), Yaw);
			if (bPine)
			{
				Place(Pines, X, Y, Height * 0.45f, FVector(Height * 0.42f, Height * 0.42f, Height * 0.6f), Yaw);
				Place(Pines, X, Y, Height * 0.75f, FVector(Height * 0.30f, Height * 0.30f, Height * 0.45f), Yaw);
			}
			else Place(Canopies, X, Y, Height * 0.55f, FVector(Height * 0.6f, Height * 0.6f, Height * 0.5f), Yaw);
		}
		if (!bPlaced) return false;
		TreeFootprints.Add({ Position, Radius });
		if (bDistant) ++DistantTrees;
		else ++MidTrees;
		return true;
	};

	const float EdgeY = bHasTripoTerrain ? TripoTerrainHalfWidth : 850.f;
	const float NearSpan = LaneLength + 3200.f;
	// Low rocky clearings alternate with shrub-rich patches. Small companion
	// stones share each patch rather than making an even salt-and-pepper scatter.
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		for (int32 I = 0; I < 12; ++I)
		{
			const float CX = -1600.f + (I + 0.5f + Rand.FRandRange(-0.28f, 0.28f)) * NearSpan / 12.f;
			const float CY = Side * (EdgeY + Rand.FRandRange(300.f, 750.f) + 90.f * FMath::Sin(I * 1.7f + Side));
			const float PatchRadius = Rand.FRandRange(150.f, 290.f);
			const bool bRocky = Rand.FRand() > 0.24f;
			const int32 RockCount = bRocky ? Rand.RandRange(2, 4) : 1;
			for (int32 J = 0; J < RockCount; ++J)
			{
				const float Angle = Rand.FRandRange(0.f, 2.f * PI);
				const float Radius = J == 0 ? 0.f : Rand.FRandRange(60.f, PatchRadius);
				UInstancedStaticMeshComponent* Rock = WedgeRocks && Rand.FRand() < 0.4f ? WedgeRocks : Rocks;
				PlaceNatural(Rock, CX + FMath::Cos(Angle) * Radius, CY + FMath::Sin(Angle) * Radius,
					Rand.FRandRange(J == 0 ? 90.f : 45.f, J == 0 ? 160.f : 90.f), Rand.FRandRange(0.f, 360.f), 0.12f);
			}
			if (bRocky && Rand.FRand() < 0.55f)
				PlaceNatural(RockBlocks, CX + Rand.FRandRange(-180.f, 180.f), CY + Rand.FRandRange(-120.f, 120.f),
					Rand.FRandRange(14.f, 28.f), Rand.FRandRange(0.f, 360.f), 0.12f);
			const int32 ShrubCount = Rand.RandRange(bRocky ? 3 : 5, bRocky ? 5 : 7);
			// A loose crescent leaves exposed stone and a low, broken leading
			// edge. Equal-height rings read as planted flower beds in the player
			// camera. Derive orientation without changing the tree-line RNG.
			const float PatchOrientation = I * 1.73f + Side * 0.91f;
			for (int32 J = 0; J < ShrubCount; ++J)
			{
				const float Angle = PatchOrientation + J * 0.64f + Rand.FRandRange(-0.4f, 0.4f);
				const float Radius = Rand.FRandRange(PatchRadius * 0.55f, PatchRadius * 1.4f);
				const float HeightFactor = J == 0 ? 1.f : (J % 3 == 0 ? 0.52f : 0.76f);
				PlaceNatural(Bushes, CX + FMath::Cos(Angle) * Radius, CY + FMath::Sin(Angle) * Radius,
					Rand.FRandRange(90.f, 155.f) * HeightFactor, Rand.FRandRange(0.f, 360.f), 0.10f);
			}
		}
	}

	// Irregular small groves make the middle distance legible. Younger edge
	// trees grade up into taller trees, leaving broad open breaks between groves.
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		for (int32 I = 0; I < 8; ++I)
		{
			const float CX = -1800.f + (I + 0.5f + Rand.FRandRange(-0.3f, 0.3f)) * (LaneLength + 3600.f) / 8.f;
			const float CY = Side * (2450.f + 300.f * FMath::Sin(I * 1.9f + Side * 0.7f) + Rand.FRandRange(-170.f, 230.f));
			const bool bPineGrove = Rand.FRand() < 0.45f;
			for (int32 J = 0; J < 5; ++J)
			{
				const float X = CX + Rand.FRandRange(-480.f, 480.f);
				const float Y = Side * FMath::Max(1900.f, FMath::Abs(CY) + Rand.FRandRange(-320.f, 420.f));
				PlaceTree(Rand.FRand() < 0.78f ? bPineGrove : !bPineGrove, false, X, Y,
					Rand.FRandRange(390.f, 720.f), Rand.FRandRange(0.f, 360.f));
			}
			for (int32 J = 0; J < 4; ++J)
				PlaceNatural(Bushes, CX + Rand.FRandRange(-430.f, 430.f), CY + Rand.FRandRange(-300.f, 300.f),
					Rand.FRandRange(100.f, 175.f), Rand.FRandRange(0.f, 360.f), 0.10f);
			PlaceNatural(Rand.FRand() < 0.5f && WedgeRocks ? WedgeRocks : Rocks,
				CX + Rand.FRandRange(-250.f, 250.f), CY + Rand.FRandRange(-230.f, 230.f),
				Rand.FRandRange(85.f, 160.f), Rand.FRandRange(0.f, 360.f), 0.12f);
		}
	}

	// A broken, deeper tree line closes the view without a uniform wall. Distant
	// trees retain their PBR materials but do not spend the dynamic shadow budget.
	for (int32 Side = -1; Side <= 1; Side += 2)
	{
		for (int32 I = 0; I < 11; ++I)
		{
			const float CX = -3000.f + (I + 0.5f + Rand.FRandRange(-0.35f, 0.35f)) * (LaneLength + 6000.f) / 11.f;
			const float CY = Side * (4550.f + 650.f * FMath::Sin(I * 1.55f + Side) + Rand.FRandRange(-180.f, 320.f));
			const bool bPineGrove = Rand.FRand() < 0.68f;
			for (int32 J = 0; J < 7; ++J)
			{
				PlaceTree(Rand.FRand() < 0.82f ? bPineGrove : !bPineGrove, true,
					CX + Rand.FRandRange(-600.f, 600.f), CY + Rand.FRandRange(-380.f, 750.f),
					Rand.FRandRange(620.f, 980.f), Rand.FRandRange(0.f, 360.f));
			}
		}
	}
	if (Tufts)
	{
		for (int32 I = 0; I < 500; ++I)
		{
			const float X = Rand.FRandRange(-2000.f, LaneLength + 2000.f);
			const float Y = (Rand.FRand() < 0.5f ? -1.f : 1.f) * Rand.FRandRange(700.f, 2600.f);
			const float S = Rand.FRandRange(10.f, 22.f);
			Place(Tufts, X, Y, S * 0.5f, FVector(S, S, S * 1.8f), 0.f);
		}
	}
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_ENVIRONMENT_LAYOUT policy=clustered_biomes_v2 edge_patches=24 edge_shrubs=graded_crescents mid_groves=16 distant_groves=22 mid_trees=%d distant_trees=%d legacy_grass=%s grounding=shared_surface whole_footprint_tile_exclusion=true"),
		MidTrees, DistantTrees, Tufts ? TEXT("explicit_legacy") : TEXT("hidden_deferred"));

	// 远山（两侧对称，带雪顶）
	for (int32 I = 0; I < 22; ++I)
	{
		const float X = -6000.f + I * (LaneLength + 12000.f) / 21.f + Rand.FRandRange(-600.f, 600.f);
		for (int32 Side = -1; Side <= 1; Side += 2)
		{
			const float Y = Side * Rand.FRandRange(10500.f, 13000.f);
			const float W = Rand.FRandRange(3500.f, 6500.f);
			const float H = Rand.FRandRange(2600.f, 4600.f);
			Mountains->AddInstance(FTransform(FRotator::ZeroRotator, FVector(X, Y, H * 0.5f - 200.f), FVector(W, W * 0.8f, H) / 100.f));
			Snow->AddInstance(FTransform(FRotator::ZeroRotator, FVector(X, Y, H * 0.85f - 200.f), FVector(W * 0.32f, W * 0.26f, H * 0.32f) / 100.f));
		}
	}
	if (FParse::Param(FCommandLine::Get(), TEXT("cwartreview")))
	{
		for (UInstancedStaticMeshComponent* InstanceGroup : AuthoredInstances)
		{
			const UStaticMesh* Mesh = InstanceGroup->GetStaticMesh();
			const int32 Instances = InstanceGroup->GetInstanceCount();
			const int32 Triangles = Mesh->GetNumTriangles(0);
			double MaxScaleSkew = 1.0;
			double MinHeight = TNumericLimits<double>::Max();
			double MaxHeight = 0.0;
			for (int32 InstanceIndex = 0; InstanceIndex < Instances; ++InstanceIndex)
			{
				FTransform Transform;
				InstanceGroup->GetInstanceTransform(InstanceIndex, Transform, true);
				const FVector Scale = Transform.GetScale3D().GetAbs();
				MaxScaleSkew = FMath::Max(MaxScaleSkew, Scale.GetMax() / FMath::Max(Scale.GetMin(), UE_DOUBLE_SMALL_NUMBER));
				const double Height = Mesh->GetBounds().BoxExtent.Z * 2.0 * Scale.Z;
				MinHeight = FMath::Min(MinHeight, Height);
				MaxHeight = FMath::Max(MaxHeight, Height);
			}
			UE_LOG(LogTemp, Display, TEXT("CIVWAR_ART_INSTANCES mesh=%s instances=%d lod0_triangles=%d all_instance_lod0_budget=%lld dimensions_cm=%s materials=%d uniform_shape=%d max_scale_skew=%.6f instance_height_cm_min=%.3f max=%.3f"),
				*Mesh->GetPathName(), Instances, Triangles, static_cast<long long>(Triangles) * Instances,
				*(Mesh->GetBounds().BoxExtent * 2.0).ToString(), Mesh->GetStaticMaterials().Num(), UniformInstances.Contains(InstanceGroup), MaxScaleSkew,
				Instances ? MinHeight : 0.0, MaxHeight);
		}
	}
	(void)Cube;
}

