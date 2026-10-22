#include "View/CWBattlefield.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/SkyAtmosphereComponent.h"
#include "Components/SkyLightComponent.h"
#include "Engine/DirectionalLight.h"
#include "Engine/ExponentialHeightFog.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Dom/JsonObject.h"
#include "Math/RandomStream.h"
#include "Materials/MaterialInterface.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "ProceduralMeshComponent.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "View/CWVisuals.h"

namespace
{
	float CWSmoothStep(float A, float B, float X)
	{
		const float T = FMath::Clamp((X - A) / (B - A), 0.f, 1.f);
		return T * T * (3.f - 2.f * T);
	}

	// 低成本的平滑噪声（若干正弦叠加），足以生成柔和起伏
	float CWTerrainNoise(float X, float Y)
	{
		return 0.5f * FMath::Sin(X * 0.0011f + Y * 0.0007f) + 0.3f * FMath::Sin(X * 0.0023f - Y * 0.0019f + 1.7f)
			+ 0.2f * FMath::Sin(X * 0.0051f + Y * 0.0043f + 4.1f);
	}

	const float CWLaneHalf = 420.f;    // 平整战线半宽
	const float CWNearZone = 3600.f;   // 近景区：低矮起伏，不遮挡镜头
	const float CWFarRise = 7000.f;    // 远景山丘最高点
}

ACWBattlefield::ACWBattlefield()
{
	PrimaryActorTick.bCanEverTick = false;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Terrain = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("Terrain"));
	Terrain->SetupAttachment(Root);
	Terrain->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SetReplicates(false);
}

float ACWBattlefield::GroundHeight(float X, float Y, float InLaneLength)
{
	const float AY = FMath::Abs(Y);
	if (AY < CWLaneHalf)
	{
		return 0.f;
	}
	const float NearBlend = CWSmoothStep(CWLaneHalf, 900.f, AY);
	float H = (CWTerrainNoise(X, Y) * 0.5f + 0.5f) * 55.f * NearBlend;
	const float Far = CWSmoothStep(CWNearZone, CWFarRise, AY);
	H += Far * (500.f + 700.f * (CWTerrainNoise(X * 0.6f, Y * 0.6f + 300.f) * 0.5f + 0.5f));
	// 战场两端外侧也逐渐抬高，收束视野
	const float EndDist = FMath::Max(-X - 1500.f, X - InLaneLength - 1500.f);
	if (EndDist > 0.f)
	{
		H += CWSmoothStep(0.f, 3000.f, EndDist) * 400.f * NearBlend;
	}
	return H;
}

void ACWBattlefield::Build(float InLaneLength, float InBaseHalfWidth)
{
	LaneLength = InLaneLength;
	BaseHalfWidth = InBaseHalfWidth;
	BuildTripoTerrain();
	BuildTerrain();
	BuildProps();
	SpawnLighting();
}

bool ACWBattlefield::IsInsideTripoTerrain(float X, float Y) const
{
	return bHasTripoTerrain && X >= TripoTerrainMinX && X <= TripoTerrainMaxX &&
		FMath::Abs(Y) <= TripoTerrainHalfWidth;
}

float ACWBattlefield::SurfaceGroundHeight(float X, float Y) const
{
	const float Height = GroundHeight(X, Y, LaneLength);
	if (!bHasTripoTerrain) return Height;
	const float OutsideX = FMath::Max(TripoTerrainMinX - X, X - TripoTerrainMaxX);
	const float OutsideY = FMath::Abs(Y) - TripoTerrainHalfWidth;
	const float Distance = FMath::Max(OutsideX, OutsideY);
	// The top outline is irregular: most source vertices stop at |Y|=1175,
	// although the bounds reach 1200. Finish the rise one grid row inward;
	// reaching +1 only at 1200 still interpolates BELOW zero at the real rim.
	// This shallow shelf buries the exposed side without raising the road.
	// Preserve the old clearance/ramp for the source-material fallback.
	const float EdgeHeight = NaturalTerrainMaterial ? 1.f : -2.f;
	if (Distance <= 0.f)
	{
		const float RiseStart = NaturalTerrainMaterial ? -200.f : -150.f;
		const float RiseEnd = NaturalTerrainMaterial ? -100.f : 0.f;
		return FMath::Lerp(-25.f, EdgeHeight, CWSmoothStep(RiseStart, RiseEnd, Distance));
	}
	return FMath::Lerp(EdgeHeight, Height, CWSmoothStep(0.f, 230.f, Distance));
}

void ACWBattlefield::BuildTripoTerrain()
{
	bHasTripoTerrain = false;
	NaturalTerrainMaterial = nullptr;
	if (FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return;
	FString Text;
	TSharedPtr<FJsonObject> Config;
	if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/TerrainArt.json"))) ||
		!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Config) || !Config.IsValid()) return;
	bool Enabled = false;
	FString MeshPath;
	double TileLength = 0, TileWidth = 0, RoadHalfWidth = 0;
	if (!Config->TryGetBoolField(TEXT("default_runtime_enabled"), Enabled) || !Enabled ||
		!Config->TryGetStringField(TEXT("static_mesh"), MeshPath) ||
		!MeshPath.StartsWith(TEXT("/Game/ArtPilot/EraAssets/Env_BattlefieldTile/")) || MeshPath.Contains(TEXT("..")) ||
		!Config->TryGetNumberField(TEXT("tile_length_cm"), TileLength) ||
		!Config->TryGetNumberField(TEXT("tile_width_cm"), TileWidth) ||
		!Config->TryGetNumberField(TEXT("road_half_width_cm"), RoadHalfWidth) ||
		!FMath::IsFinite(TileLength) || !FMath::IsFinite(TileWidth) || !FMath::IsFinite(RoadHalfWidth) ||
		TileLength < 1000 || TileLength > 10000 || TileWidth < 1000 || TileWidth > 10000 ||
		RoadHalfWidth < CWLaneHalf || RoadHalfWidth >= TileWidth / 2) return;
	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *MeshPath);
	if (!Mesh || Mesh->GetStaticMaterials().IsEmpty()) return;
	bool AlternateMirror = false;
	Config->TryGetBoolField(TEXT("alternate_x_mirror"), AlternateMirror);
	const FBoxSphereBounds Bounds = Mesh->GetBounds();
	if (Bounds.Origin.ContainsNaN() || Bounds.BoxExtent.ContainsNaN() ||
		FMath::Abs(Bounds.BoxExtent.X * 2 - TileLength) > 1 ||
		FMath::Abs(Bounds.BoxExtent.Y * 2 - TileWidth) > 1 ||
		FMath::Abs(Bounds.Origin.X) > 1 || FMath::Abs(Bounds.Origin.Y) > 1 ||
		Bounds.Origin.Z - Bounds.BoxExtent.Z < -100 ||
		Bounds.Origin.Z + Bounds.BoxExtent.Z > 200) return;
	for (int32 Slot = 0; Slot < Mesh->GetStaticMaterials().Num(); ++Slot)
		if (!Mesh->GetMaterial(Slot)) return;
	UMaterialInterface* NaturalTileMaterial = nullptr;
	FString TileMaterialPath, LandscapeMaterialPath;
	if (Config->TryGetStringField(TEXT("tile_surface_material"), TileMaterialPath) &&
		Config->TryGetStringField(TEXT("landscape_surface_material"), LandscapeMaterialPath) &&
		TileMaterialPath.StartsWith(TEXT("/Game/Art/TerrainNatural_v01/")) && !TileMaterialPath.Contains(TEXT("..")) &&
		LandscapeMaterialPath.StartsWith(TEXT("/Game/Art/TerrainNatural_v01/")) && !LandscapeMaterialPath.Contains(TEXT("..")))
	{
		NaturalTileMaterial = LoadObject<UMaterialInterface>(nullptr, *TileMaterialPath);
		NaturalTerrainMaterial = LoadObject<UMaterialInterface>(nullptr, *LandscapeMaterialPath);
		// Enable the pair together; the source Tripo materials remain a complete
		// fallback when the optional derived packages have not been generated.
		if (!NaturalTileMaterial || !NaturalTerrainMaterial)
		{
			NaturalTileMaterial = nullptr;
			NaturalTerrainMaterial = nullptr;
			UE_LOG(LogTemp, Warning, TEXT("CIVWAR_NATURAL_TERRAIN incomplete_material_pair using_source_materials"));
		}
	}
	const int32 Count = FMath::CeilToInt(LaneLength / TileLength) + 1;
	for (int32 I = 0; I < Count; ++I)
	{
		// The Tripo tile has different imagery on its left and right edges.
		// Reflect alternate instances so each boundary meets the same source
		// edge, preserving the original UVs, PBR and flat gameplay corridor.
		// Separate components let the renderer reverse culling for a mirrored
		// transform; mixing determinant signs inside one ISM inverts lighting.
		const float XScale = AlternateMirror && I % 2 ? -1.f : 1.f;
		auto* Tile = NewObject<UStaticMeshComponent>(this);
		AddInstanceComponent(Tile);
		Tile->SetupAttachment(Root);
		Tile->SetStaticMesh(Mesh);
		if (NaturalTileMaterial)
			for (int32 Slot = 0; Slot < Mesh->GetStaticMaterials().Num(); ++Slot)
				Tile->SetMaterial(Slot, NaturalTileMaterial);
		Tile->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Tile->SetCastShadow(false);
		Tile->SetRelativeTransform(FTransform(FQuat::Identity, FVector(I * TileLength, 0, 0), FVector(XScale, 1, 1)));
		Tile->RegisterComponent();
	}
	TripoTerrainMinX = -TileLength / 2;
	TripoTerrainMaxX = (Count - 1) * TileLength + TileLength / 2;
	TripoTerrainHalfWidth = TileWidth / 2;
	bHasTripoTerrain = true;
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_TRIPO_TERRAIN mesh=%s tiles=%d length=%.1f width=%.1f road_half=%.1f activation=default_runtime"),
		*MeshPath, Count, TileLength, TileWidth, RoadHalfWidth);
	if (NaturalTerrainMaterial)
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_NATURAL_TERRAIN tile_material=%s landscape_material=%s side_feather_cm=335 source_mesh_and_textures=preserved"),
			*TileMaterialPath, *LandscapeMaterialPath);
}

void ACWBattlefield::BuildTerrain()
{
	const float MinX = -4500.f;
	const float MaxX = LaneLength + 4500.f;
	const float MinY = -9500.f;
	const float MaxY = 9500.f;
	// A 100cm grid samples the 1200cm tile edge exactly and resolves its
	// shallow shoulder. The old 200cm rows straddled the edge by 100cm.
	const float Step = bHasTripoTerrain ? 100.f : 200.f;
	const int32 Cols = FMath::CeilToInt((MaxX - MinX) / Step) + 1;
	const int32 Rows = FMath::CeilToInt((MaxY - MinY) / Step) + 1;

	TArray<FVector> Verts;
	TArray<FVector> Normals;
	TArray<FVector2D> UVs;
	TArray<FLinearColor> Colors;
	Verts.Reserve(Cols * Rows);
	for (int32 R = 0; R < Rows; ++R)
	{
		for (int32 C = 0; C < Cols; ++C)
		{
			const float X = MinX + C * Step;
			const float Y = MinY + R * Step;
			Verts.Add(FVector(X, Y, SurfaceGroundHeight(X, Y)));
			// 法线：中心差分
			const float HX = SurfaceGroundHeight(X + 50.f, Y) - SurfaceGroundHeight(X - 50.f, Y);
			const float HY = SurfaceGroundHeight(X, Y + 50.f) - SurfaceGroundHeight(X, Y - 50.f);
			Normals.Add(FVector(-HX, -HY, 100.f).GetSafeNormal());
			UVs.Add(FVector2D(X / 1000.f, Y / 1000.f));
			const float Tint = 0.9f + 0.1f * CWTerrainNoise(X * 1.7f, Y * 1.3f);
			Colors.Add(FLinearColor(Tint, Tint, Tint));
		}
	}

	// 按区域分段：战线泥土、近景草地、远景山坡（每段一种材质颜色）
	TArray<int32> Tris[3];
	for (int32 R = 0; R < Rows - 1; ++R)
	{
		for (int32 C = 0; C < Cols - 1; ++C)
		{
			const int32 I0 = R * Cols + C;
			const int32 I1 = I0 + 1;
			const int32 I2 = I0 + Cols;
			const int32 I3 = I2 + 1;
			const float CY = FMath::Abs(MinY + (R + 0.5f) * Step);
			const float CX = MinX + (C + 0.5f) * Step;
			int32 Section = CY < CWLaneHalf && CX > -600.f && CX < LaneLength + 600.f ? 0 : (CY < CWNearZone ? 1 : 2);
			// One continuous world-space surface replaces the three hard material
			// bands only when both natural terrain materials are available.
			if (NaturalTerrainMaterial) Section = 0;
			TArray<int32>& T = Tris[Section];
			// The natural landscape is two-sided and needs only one surface per
			// cell. Duplicating reversed faces would render coplanar geometry.
			// Keep the old winding fallback solely for the legacy material path.
			T.Append({ I0, I2, I1, I1, I2, I3 });
			if (!NaturalTerrainMaterial)
				T.Append({ I0, I1, I2, I1, I3, I2 });
		}
	}

	const FLinearColor SectionColors[3] = {
		FLinearColor(0.32f, 0.22f, 0.13f), // 战线：夯实泥土
		FLinearColor(0.16f, 0.30f, 0.08f), // 草地
		FLinearColor(0.12f, 0.20f, 0.08f), // 远景山坡
	};
	const TArray<FProcMeshTangent> NoTangents;
	for (int32 S = 0; S < 3; ++S)
	{
		if (Tris[S].IsEmpty()) continue;
		Terrain->CreateMeshSection_LinearColor(S, Verts, Tris[S], Normals, UVs, Colors, NoTangents, false);
		Terrain->SetMaterial(S, NaturalTerrainMaterial ? NaturalTerrainMaterial.Get() : CWVisual::MakeMaterial(this, SectionColors[S], 0.95f, 0.f));
	}
	Terrain->SetCastShadow(false);
}

void ACWBattlefield::SetViewTeam(int32 Team)
{
	Team = Team == 1 ? 1 : 0;
	if (Team == ViewTeam)
	{
		return;
	}
	ViewTeam = Team;
	if (SunActor)
	{
		SunActor->SetActorRotation(FRotator(-42.f, ViewTeam == 1 ? 115.f : -65.f, 0.f));
	}
}

void ACWBattlefield::SpawnLighting()
{
	UWorld* World = GetWorld();
	FActorSpawnParameters Params;
	Params.Owner = this;

	// 太阳：从镜头一侧斜照，阴影落向画面右后方，不遮挡单位
	if (ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>(FVector(0.f, 0.f, 3000.f), FRotator(-42.f, ViewTeam == 1 ? 115.f : -65.f, 0.f), Params))
	{
		SunActor = Sun;
		Sun->GetRootComponent()->SetMobility(EComponentMobility::Movable);
		// 平行光组件自带 -46° 俯仰，生成时会与传入的旋转叠加（实测变成 -88°，几乎垂直），这里显式设回
		Sun->SetActorRotation(FRotator(-42.f, ViewTeam == 1 ? 115.f : -65.f, 0.f));
		if (UDirectionalLightComponent* Light = Cast<UDirectionalLightComponent>(Sun->GetLightComponent()))
		{
			Light->SetIntensity(8.f);
			Light->SetLightColor(FLinearColor(1.f, 0.95f, 0.86f));
			Light->SetAtmosphereSunLight(true);
			Light->SetDynamicShadowDistanceMovableLight(12000.f);
		}
		SpawnedActors.Add(Sun);
	}
	if (ASkyAtmosphere* Atmosphere = World->SpawnActor<ASkyAtmosphere>(FVector::ZeroVector, FRotator::ZeroRotator, Params))
	{
		SpawnedActors.Add(Atmosphere);
	}
	if (ASkyLight* Sky = World->SpawnActor<ASkyLight>(FVector(0.f, 0.f, 1000.f), FRotator::ZeroRotator, Params))
	{
		Sky->GetRootComponent()->SetMobility(EComponentMobility::Movable);
		if (USkyLightComponent* SkyComp = Sky->GetLightComponent())
		{
			SkyComp->bRealTimeCapture = true;
			SkyComp->SetIntensity(1.1f);
			SkyComp->MarkRenderStateDirty();
			SkyComp->RecaptureSky();
		}
		SpawnedActors.Add(Sky);
	}
	if (AExponentialHeightFog* Fog = World->SpawnActor<AExponentialHeightFog>(FVector(0.f, 0.f, -200.f), FRotator::ZeroRotator, Params))
	{
		if (UExponentialHeightFogComponent* FogComp = Fog->GetComponent())
		{
			FogComp->SetFogDensity(0.008f);
			FogComp->SetFogHeightFalloff(0.08f);
			FogComp->SetStartDistance(3500.f);
			FogComp->SetFogInscatteringColor(FLinearColor(0.45f, 0.55f, 0.70f));
		}
		SpawnedActors.Add(Fog);
	}
	if (APostProcessVolume* PP = World->SpawnActor<APostProcessVolume>(FVector::ZeroVector, FRotator::ZeroRotator, Params))
	{
		PP->bUnbound = true;
		FPostProcessSettings& S = PP->Settings;
		// 适度后期：轻微泛光、暗角与饱和度，不使用景深与运动模糊
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity = 0.35f;
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity = 0.25f;
		S.bOverride_ColorSaturation = true;
		S.ColorSaturation = FVector4(1.08f, 1.08f, 1.08f, 1.f);
		S.bOverride_ColorContrast = true;
		S.ColorContrast = FVector4(1.05f, 1.05f, 1.05f, 1.f);
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount = 0.f;
		S.bOverride_AutoExposureSpeedUp = true;
		S.AutoExposureSpeedUp = 1.f;
		S.bOverride_AutoExposureSpeedDown = true;
		S.AutoExposureSpeedDown = 1.f;
		SpawnedActors.Add(PP);
	}
}
