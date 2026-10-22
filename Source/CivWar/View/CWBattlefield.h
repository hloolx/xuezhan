// 血战文明 - 战场环境：程序化地形、植被岩石、远景山脉、光照与后期
// 只在本地生成（纯表现，不参与同步）；双方镜头分别位于战线两侧，因此两侧都按“近处低矮、远处高耸”布置。
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CWBattlefield.generated.h"

class UProceduralMeshComponent;
class UInstancedStaticMeshComponent;
class UMaterialInterface;
class UStaticMesh;

UCLASS(NotPlaceable)
class CIVWAR_API ACWBattlefield : public AActor
{
	GENERATED_BODY()

public:
	ACWBattlefield();

	void Build(float InLaneLength, float InBaseHalfWidth);
	// 太阳始终从观察者一侧斜照（双方镜头位于战线两侧），避免看到的都是背光面
	void SetViewTeam(int32 Team);
	static float GroundHeight(float X, float Y, float LaneLength);

private:
	void BuildTerrain();
	void BuildTripoTerrain();
	bool IsInsideTripoTerrain(float X, float Y) const;
	float SurfaceGroundHeight(float X, float Y) const;
	void BuildProps();
	void SpawnLighting();
	void LoadEnvironmentArt();
	UInstancedStaticMeshComponent* MakeEnvironmentInstanced(FName AssetId, bool bShadow);
	UInstancedStaticMeshComponent* MakeInstanced(int32 ShapeIndex, const FLinearColor& Color, float Roughness, bool bShadow);

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere)
	TObjectPtr<UProceduralMeshComponent> Terrain;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> NaturalTerrainMaterial;

	UPROPERTY(Transient)
	TArray<TObjectPtr<AActor>> SpawnedActors;

	UPROPERTY(Transient)
	TObjectPtr<AActor> SunActor;

	// Imported mother meshes retain their own material slots; missing entries use primitives.
	UPROPERTY(Transient)
	TMap<FName, TObjectPtr<UStaticMesh>> EnvironmentMeshes;
	TSet<FName> EnvironmentPreserveShape;

	int32 ViewTeam = 0;
	bool bPartialArtReview = false;
	bool bHasTripoTerrain = false;
	float TripoTerrainMinX = 0.f;
	float TripoTerrainMaxX = 0.f;
	float TripoTerrainHalfWidth = 0.f;

	float LaneLength = 6000.f;
	float BaseHalfWidth = 300.f;
};
