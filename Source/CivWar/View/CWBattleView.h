// 血战文明 - 战场表现管理器（每台有本地玩家的机器各一个，不参与同步）
// 读取 GameState 与复制器中的权威状态，生成/回收单位表现、投射物、技能预警与特效。
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "View/CWVisuals.h"
#include "View/CWPresentationDelayProbe.h"
#include "CWBattleView.generated.h"

class ACWBaseVisual;
class ACWBattleReplicator;
class ACWGameState;
class ACWUnitVisual;
class UCWGameDataSubsystem;
class UPointLightComponent;
class UStaticMeshComponent;
struct FCWUnitNetItem;

UCLASS(NotPlaceable)
class CIVWAR_API ACWBattleView : public AActor
{
	GENERATED_BODY()

public:
	ACWBattleView();

	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

	ACWUnitVisual* FindUnit(int32 Id) const;
	const TMap<int32, TObjectPtr<ACWUnitVisual>>& GetUnitVisuals() const { return Units; }
	ACWBaseVisual* GetBase(int32 Team) const;
	void SetTargetingPreview(bool bVisible, float X, float Radius, bool bValid);
	int32 GetActiveProjectileCount() const { return Projectiles.Num(); }

private:
	struct FProjectileVisual
	{
		int32 Id = 0;
		UStaticMeshComponent* Mesh = nullptr;
		CWVisual::EShape Shape = CWVisual::EShape::Sphere;
		FVector Start = FVector::ZeroVector;
		FVector Target = FVector::ZeroVector;
		FVector PrevPos = FVector::ZeroVector;
		int32 TargetId = -1;
		uint8 Team = 0;
		float Duration = 0.1f;
		float Elapsed = 0.f;
		float Arc = 0.f;
		float Splash = 0.f;
		bool bAlign = false;
		bool bCosmetic = false; // 技能落下物：只做表现
		bool bImpactFx = true;  // 到达终点时是否播放命中特效（飞过战场的战机不需要）
	};

	struct FWarning
	{
		int32 Id = 0;
		uint8 Skill = 0;
		UStaticMeshComponent* Disk = nullptr;
		UStaticMeshComponent* Edge = nullptr;
		float X = 0.f;
		float Radius = 0.f;
		float ImpactTime = 0.f;
		bool bIncomingSpawned = false;
	};

	struct FEffect
	{
		UStaticMeshComponent* Mesh = nullptr;
		CWVisual::EShape Shape = CWVisual::EShape::Sphere;
		UPointLightComponent* Light = nullptr;
		FVector Velocity = FVector::ZeroVector;
		float Age = 0.f;
		float Duration = 0.3f;
		float StartSize = 10.f;
		float EndSize = 100.f;
		float LightIntensity = 0.f;
		float FixedHeight = 0.f; // >0：圆柱光束，高度固定、只缩放粗细
		bool bGravity = false;
	};

	bool EnsureInitialized();
	void SyncUnits(float Dt);
	void SyncProjectiles(float Dt);
	void UpdateProjectiles(float Dt);
	void SyncSkills(float Dt);
	void UpdateEffects(float Dt);
	void HandleSkillImpact(uint8 Team, uint8 Skill, float X, float Radius, int32 Hits);
	void HandleTurretFired(int32 Team, int32 Slot, int32 TurretDef, FVector Muzzle);
	void PlayUnitSounds(ACWUnitVisual* Visual, const FCWUnitNetItem& Item);
	void SpawnBurst(const FVector& Location, float Size, const FLinearColor& Color, float Duration, float LightIntensity, float Emissive = 4.f);
	void SpawnDebris(const FVector& Location, int32 Count, const FLinearColor& Color, float Speed);
	void SpawnFalling(const FVector& From, const FVector& To, float Duration, CWVisual::EShape Shape, const FVector& Size, const FLinearColor& Color, float Splash,
		float Emissive = 0.f, bool bImpactFx = true);
	// 竖直光束（轨道光束技能）：底部位于 Ground，先变粗再收细
	void SpawnBeam(const FVector& Ground, float Height, float Width, const FLinearColor& Color, float Duration, float Emissive);
	// 贴地扩散的圆环（统帅战吼）
	void SpawnGroundPulse(const FVector& Center, float Diameter, const FLinearColor& Color, float Duration, float Emissive);
	void SyncChampionMarkers(const ACWGameState& State);
	FString SkillVisualKey(int32 Skill) const;
	UStaticMeshComponent* AcquireMesh(CWVisual::EShape Shape, const FLinearColor& Color, float Emissive, bool bShadow);
	void ReleaseMesh(UStaticMeshComponent* Mesh, CWVisual::EShape Shape);
	float LaneYForRow(int32 Row, int32 Id) const;

	UPROPERTY(Transient)
	TMap<int32, TObjectPtr<ACWUnitVisual>> Units;

	UPROPERTY(Transient)
	TObjectPtr<ACWBaseVisual> Bases[2];

	UPROPERTY(Transient)
	TObjectPtr<UStaticMeshComponent> TargetDisk;

	// 统帅坚守位置的旗帜（每方一面）
	UPROPERTY(Transient)
	TObjectPtr<USceneComponent> HoldFlags[2];

	UPROPERTY(Transient)
	TArray<TObjectPtr<UStaticMeshComponent>> AllPooledMeshes;

	TArray<FProjectileVisual> Projectiles;
	TSet<int32> SeenProjectiles;
	TArray<FWarning> Warnings;
	TArray<FEffect> Effects;
	TArray<UStaticMeshComponent*> Pool[4];

	TWeakObjectPtr<ACWBattleReplicator> BoundReplicator;
	FCWPresentationDelayProbe PresentationDelayProbe;
	FDelegateHandle SkillImpactHandle;
	bool bInitialized = false;
	uint8 LastPhase = 255;
	uint8 SeenAbilitySeq[2] = { 0, 0 };
	int32 SeenChampionId[2] = { -1, -1 };
	bool SeenLastStand[2] = { false, false };
	bool bChampionTrackerReady = false;
	float LaneLength = 6000.f;
	int32 LaneRows = 3;
	float RowSpacing = 85.f;
};
