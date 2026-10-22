#include "View/CWBaseVisual.h"

#include "Components/StaticMeshComponent.h"
#include "View/CWStaticBasePilot.h"
#include "View/CWStaticTurretPilot.h"
#include "View/CWEraArt.h"
#include "Data/CWGameDataSubsystem.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWNetTypes.h"
#if WITH_EDITOR
#include "EngineUtils.h"
#include "View/CWCameraRig.h"
#endif

ACWBaseVisual::ACWBaseVisual()
{
	PrimaryActorTick.bCanEverTick = false; // 由 ACWBattleView 驱动
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	SetReplicates(false);
}

void ACWBaseVisual::Init(int32 InTeam, float InX, float InHalfWidth)
{
	Team = InTeam;
	HalfWidth = InHalfWidth;
	// 阵营 1 的基地朝向 -X（城门面向敌方）
	SetActorLocationAndRotation(FVector(InX, 0.f, 0.f), FRotator(0.f, Team == 0 ? 0.f : 180.f, 0.f));
	RebuildStructure(0);

	// A solid emissive cylinder washed the new PBR foundations into a white
	// plinth. Keep the upgrade cue at the perimeter so terrain remains visible.
	UpgradeRing = CWVisual::AddPivot(this, Root, FVector(0.f, 0.f, 7.f));
	CWVisual::FMaterialParams Gold = CWVisual::Paint(FLinearColor(0.65f, 0.39f, 0.09f), 0.75f, 0.15f);
	Gold.Emissive = 0.35f;
	constexpr int32 SegmentCount = 24;
	for (int32 I = 0; I < SegmentCount; ++I)
	{
		const float Angle = 2.f * PI * I / SegmentCount;
		CWVisual::AddPart(this, UpgradeRing, CWVisual::EShape::Cube,
			FVector(FMath::Cos(Angle) * 385.f, FMath::Sin(Angle) * 385.f, 0.f), FVector(55.f, 5.f, 2.f),
			FRotator(0.f, FMath::RadiansToDegrees(Angle) + 90.f, 0.f), Gold, false);
	}
	UpgradeRing->SetVisibility(false, true);
}

void ACWBaseVisual::ResetForMatch()
{
	RebuildStructure(0);
	if (Structure)
	{
		Structure->SetRelativeScale3D(FVector::OneVector);
	}
	for (FDebris& D : Debris)
	{
		D.Mesh->DestroyComponent();
	}
	Debris.Reset();
	bHitSeqInit = false;
	bSlotsInitialized = false;
	bUpgrading = false;
	bAgeUpEvent = false;
	bHitEvent = false;
	bBuildEvent = false;
	RiseClock = -1.f;
	if (UpgradeRing) UpgradeRing->SetVisibility(false, true);
	HitFlash = 0.f;
	Shake = 0.f;
}

FVector ACWBaseVisual::GetGateLocation() const
{
	if (Rig.bHasMeasuredGate && Structure) return Structure->GetComponentTransform().TransformPosition(Rig.MeasuredGate);
	return GetActorTransform().TransformPosition(FVector(HalfWidth, 0.f, 120.f));
}

FVector ACWBaseVisual::GetTurretMuzzle(int32 Slot) const
{
	if (TurretRigs.IsValidIndex(Slot) && TurretRigs[Slot].Muzzle)
	{
		return TurretRigs[Slot].Muzzle->GetComponentLocation();
	}
	if (Rig.TurretMounts.IsValidIndex(Slot))
	{
		return GetActorTransform().TransformPosition(Rig.TurretMounts[Slot] + FVector(0.f, 0.f, 40.f));
	}
	return GetGateLocation();
}

bool ACWBaseVisual::ConsumeAgeUpEvent()
{
	const bool bResult = bAgeUpEvent;
	bAgeUpEvent = false;
	return bResult;
}

bool ACWBaseVisual::ConsumeHitEvent()
{
	const bool bResult = bHitEvent;
	bHitEvent = false;
	return bResult;
}

bool ACWBaseVisual::ConsumeBuildEvent()
{
	const bool bResult = bBuildEvent;
	bBuildEvent = false;
	return bResult;
}

void ACWBaseVisual::ClearComponentTree(USceneComponent* Parent)
{
	if (!Parent)
	{
		return;
	}
	TArray<USceneComponent*> ChildComponents; // 不能命名为 Children：会遮蔽 AActor::Children
	Parent->GetChildrenComponents(true, ChildComponents);
	for (USceneComponent* Child : ChildComponents)
	{
		if (Child)
		{
			Child->DestroyComponent();
		}
	}
	Parent->DestroyComponent();
}

void ACWBaseVisual::RebuildStructure(int32 Age)
{
	ClearComponentTree(Structure);
	for (USceneComponent* SlotRoot : SlotRoots)
	{
		ClearComponentTree(SlotRoot);
	}
	SlotRoots.Reset();
	Rig = FCWBaseRig();
	Structure = CWVisual::AddPivot(this, Root, FVector::ZeroVector);
	if (!CWStaticBasePilot::TryBuild(this, Structure, Age, Team, Rig) &&
		!CWEraArt::TryBuildBase(this, Structure, Age, Team, Rig))
	{
		CWModels::BuildBase(this, Structure, Age, Team, Rig);
	}

	const int32 Slots = Rig.TurretMounts.Num();
	TurretRigs.SetNum(Slots);
	TurretDefs.Init(-1, Slots);
	TurretFireSeqs.Init(0, Slots);
	TurretRecoil.Init(0.f, Slots);
	AimBase.Init(FVector::ZeroVector, Slots);
	SlotUnlocked.Init(false, Slots);
	for (int32 I = 0; I < Slots; ++I)
	{
		SlotRoots.Add(CWVisual::AddPivot(this, Structure, Rig.TurretMounts[I]));
		TurretRigs[I] = FCWTurretRig();
	}
	CurrentAge = Age;
}

void ACWBaseVisual::RebuildTurret(int32 Slot, int32 Def, FName VisualKey)
{
	if (!SlotRoots.IsValidIndex(Slot))
	{
		return;
	}
	// 清空槽位上的旧模型
	TArray<USceneComponent*> ChildComponents;
	SlotRoots[Slot]->GetChildrenComponents(true, ChildComponents);
	for (USceneComponent* Child : ChildComponents)
	{
		Child->DestroyComponent();
	}
	TurretRigs[Slot] = FCWTurretRig();
	TurretDefs[Slot] = Def;
	if (Def >= 0)
	{
		if (!CWStaticTurretPilot::TryBuild(this, SlotRoots[Slot], VisualKey, Team, Slot, Rig.bTripoBasePilot, TurretRigs[Slot]) &&
			!CWEraArt::TryBuildTurret(this, SlotRoots[Slot], VisualKey, Team, TurretRigs[Slot]))
		{
			CWModels::BuildTurret(this, SlotRoots[Slot], VisualKey, Team, TurretRigs[Slot]);
		}
		AimBase[Slot] = TurretRigs[Slot].Aim ? TurretRigs[Slot].Aim->GetRelativeLocation() : FVector::ZeroVector;
	}
	else if (SlotUnlocked[Slot])
	{
		// 已解锁的空槽：显示平台标记
		CWVisual::AddPart(this, SlotRoots[Slot], CWVisual::EShape::Cylinder, FVector(0.f, 0.f, 4.f), FVector(70.f, 70.f, 8.f),
			FRotator::ZeroRotator, CWVisual::Paint(CWVisual::TeamColorDark(Team), 0.6f), false);
	}
}

void ACWBaseVisual::SyncState(const FCWTeamNetState& State, const UCWGameDataSubsystem* Data)
{
	const bool bRebuilt = State.Age != CurrentAge;
	if (bRebuilt)
	{
		const bool bWasBuilt = CurrentAge >= 0;
		RebuildStructure(State.Age);
		if (bWasBuilt)
		{
			RiseClock = 0.f;
			bAgeUpEvent = true;
			SpawnDebris();
		}
	}
	bUpgrading = State.bUpgrading;

	if (!bHitSeqInit)
	{
		LastHitSeq = State.BaseHitSeq;
		bHitSeqInit = true;
	}
	else if (State.BaseHitSeq != LastHitSeq)
	{
		LastHitSeq = State.BaseHitSeq;
		HitFlash = 0.12f;
		Shake = 0.15f;
		bHitEvent = true;
	}

	for (int32 I = 0; I < State.Turrets.Num() && I < SlotRoots.Num(); ++I)
	{
		const FCWTurretNetSlot& Slot = State.Turrets[I];
		const bool bUnlockChanged = SlotUnlocked[I] != Slot.bUnlocked;
		SlotUnlocked[I] = Slot.bUnlocked;
		if (Slot.Def != TurretDefs[I] || bUnlockChanged)
		{
			// 首次同步与时代升级后的重建不算“建造”
			if (bSlotsInitialized && !bRebuilt && ((Slot.Def >= 0 && TurretDefs[I] < 0) || (bUnlockChanged && Slot.bUnlocked)))
			{
				bBuildEvent = true;
			}
			const FName Key = Data && Slot.Def >= 0 ? Data->GetTurretVisualKey(Slot.Def) : NAME_None;
			RebuildTurret(I, Slot.Def, Key);
			TurretFireSeqs[I] = Slot.FireSeq;
		}
		else if (Slot.FireSeq != TurretFireSeqs[I])
		{
			TurretFireSeqs[I] = Slot.FireSeq;
			TurretRecoil[I] = 1.f;
			CWStaticTurretPilot::BeginFire(TurretRigs[I]);
			CWEraArt::BeginFire(TurretRigs[I]);
			OnTurretFired.Broadcast(Team, I, TurretDefs[I], GetTurretMuzzle(I));
			if (TurretRigs[I].bRockTowerPilot)
			{
				UE_LOG(LogTemp, Display, TEXT("CIVWAR_ROCK_TOWER_RELEASE team=%d slot=%d seq=%u pitch=%.5f stone_visible=%d muzzle=%s"), Team, I, static_cast<uint32>(Slot.FireSeq),
					TurretRigs[I].Aim->GetRelativeRotation().Pitch, TurretRigs[I].LoadedStone->IsVisible() ? 1 : 0, *GetTurretMuzzle(I).ToString());
			}
		}
	}
	bSlotsInitialized = true;
}

void ACWBaseVisual::SpawnDebris()
{
	// Short, low chips at the foundation; the old 34cm spheres/cubes read as
	// floating prototype geometry during rapid era changes.
	for (int32 I = 0; I < 10; ++I)
	{
		const float Angle = FMath::FRandRange(0.f, 2.f * PI);
		const float Radius = FMath::FRandRange(80.f, 320.f);
		const FVector Local(FMath::Cos(Angle) * Radius, FMath::Sin(Angle) * Radius, 10.f);
		FDebris D;
		const float Size = FMath::FRandRange(7.f, 14.f);
		D.Mesh = CWVisual::AddPart(this, Root, CWVisual::EShape::Sphere, Local,
			FVector(Size, Size * 0.72f, Size * 0.42f), FRotator(FMath::FRandRange(0.f, 90.f), FMath::FRandRange(0.f, 90.f), 0.f),
			CWVisual::Paint(FLinearColor(0.26f, 0.22f, 0.16f), 1.f), false);
		D.InitialScale = D.Mesh->GetRelativeScale3D();
		D.Velocity = FVector(FMath::Cos(Angle) * 125.f, FMath::Sin(Angle) * 125.f, FMath::FRandRange(105.f, 190.f));
		D.Life = FMath::FRandRange(0.65f, 0.9f);
		Debris.Add(D);
	}
}

void ACWBaseVisual::UpdateVisual(float Dt)
{
	Clock += Dt;

	// 升级完成：建筑从地面升起并回弹
	if (RiseClock >= 0.f && Structure)
	{
		RiseClock += Dt;
		const float T = FMath::Clamp(RiseClock / 1.2f, 0.f, 1.f);
		const float Back = 1.f + 2.70158f * FMath::Pow(T - 1.f, 3.f) + 1.70158f * FMath::Pow(T - 1.f, 2.f); // EaseOutBack
		Structure->SetRelativeScale3D(FVector(1.f, 1.f, FMath::Max(0.05f, Back)));
		if (T >= 1.f)
		{
			RiseClock = -1.f;
			Structure->SetRelativeScale3D(FVector::OneVector);
		}
	}

	// 升级进行中：金色光环脉动
	if (UpgradeRing)
	{
		UpgradeRing->SetVisibility(bUpgrading || RiseClock >= 0.f, true);
		const float Pulse = 1.f + 0.025f * FMath::Sin(Clock * 6.f);
		UpgradeRing->SetRelativeScale3D(FVector(Pulse, Pulse, 1.f));
	}

	// 受击：轻微抖动与闪白
	if (Structure)
	{
		Shake = FMath::Max(0.f, Shake - Dt);
		const FVector Offset = Shake > 0.f ? FVector(FMath::FRandRange(-4.f, 4.f), FMath::FRandRange(-4.f, 4.f), 0.f) : FVector::ZeroVector;
		Structure->SetRelativeLocation(Offset);
	}
	if (HitFlash > 0.f || Rig.Materials.Num() > 0)
	{
		const float Prev = HitFlash;
		HitFlash = FMath::Max(0.f, HitFlash - Dt);
		if (Prev > 0.f)
		{
			const float Flash = HitFlash / 0.12f * 0.35f;
			for (int32 I = 0; I < Rig.Materials.Num(); ++I)
			{
				CWVisual::SetMaterialColor(Rig.Materials[I], FMath::Lerp(Rig.BaseColors[I], FLinearColor(1.f, 0.85f, 0.7f), Flash));
			}
		}
	}

	// 炮塔后坐
	for (int32 I = 0; I < TurretRigs.Num(); ++I)
	{
		if (CWEraArt::UpdateTurret(TurretRigs[I], Dt)) continue;
		const float PreviousPilotElapsed = TurretRigs[I].PilotFireElapsed;
		if (CWStaticTurretPilot::Update(TurretRigs[I], Dt))
		{
			if (PreviousPilotElapsed >= 0.f && PreviousPilotElapsed < 2.10f && FParse::Param(FCommandLine::Get(), TEXT("cwrocktowerfixture")))
			{
				UE_LOG(LogTemp, Display, TEXT("CIVWAR_ROCK_TOWER_POSE team=%d slot=%d seq=%u elapsed=%.6f pitch=%.5f stone_visible=%d muzzle=%s scale=%s"),
					Team, I, static_cast<uint32>(TurretFireSeqs[I]), TurretRigs[I].PilotFireElapsed, TurretRigs[I].Aim->GetRelativeRotation().Pitch,
					TurretRigs[I].LoadedStone->IsVisible() ? 1 : 0, *GetTurretMuzzle(I).ToString(), *TurretRigs[I].Aim->GetComponentScale().ToString());
#if WITH_EDITOR
				if (I == 0 && FParse::Param(FCommandLine::Get(), TEXT("cwrocktowercyclecapture")))
				{
					for (TActorIterator<ACWCameraRig> ReviewCamera(GetWorld()); ReviewCamera; ++ReviewCamera)
					{
						ReviewCamera->CaptureRockTowerReview(Team, I, TurretFireSeqs[I], TurretRigs[I].PilotFireElapsed,
							TurretRigs[I].Aim->GetRelativeRotation().Pitch, TurretRigs[I].LoadedStone->IsVisible());
					}
				}
#endif
			}
			continue;
		}
		if (!TurretRigs[I].Aim)
		{
			continue;
		}
		TurretRecoil[I] = FMath::Max(0.f, TurretRecoil[I] - Dt * 5.f);
		TurretRigs[I].Aim->SetRelativeLocation(AimBase[I] - FVector(TurretRecoil[I] * 8.f, 0.f, 0.f));
	}

	// 碎石
	for (int32 I = Debris.Num() - 1; I >= 0; --I)
	{
		FDebris& D = Debris[I];
		D.Life -= Dt;
		D.Velocity.Z -= 980.f * Dt;
		FVector Loc = D.Mesh->GetRelativeLocation() + D.Velocity * Dt;
		if (Loc.Z < 0.f)
		{
			Loc.Z = 0.f;
			D.Velocity *= 0.3f;
		}
		D.Mesh->SetRelativeLocation(Loc);
		D.Mesh->SetRelativeScale3D(D.InitialScale * FMath::Clamp(D.Life / 0.3f, 0.f, 1.f));
		if (D.Life <= 0.f)
		{
			D.Mesh->DestroyComponent();
			Debris.RemoveAtSwap(I);
		}
	}
}
