#include "View/CWUnitVisual.h"

#include "Components/StaticMeshComponent.h"
#include "ProceduralMeshComponent.h"
#include "View/CWSkeletalUnitPresentation.h"
#include "Engine/World.h"
#include "GameFramework/GameStateBase.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWNetTypes.h"
#include "Sim/SimState.h"

namespace
{
	float CWEaseOut(float X)
	{
		const float C = FMath::Clamp(X, 0.f, 1.f);
		return 1.f - (1.f - C) * (1.f - C);
	}
}

ACWUnitVisual::ACWUnitVisual()
{
	PrimaryActorTick.bCanEverTick = false; // 由 ACWBattleView 统一驱动，避免每个单位独立 Tick
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	Model = CreateDefaultSubobject<USceneComponent>(TEXT("Model"));
	Model->SetupAttachment(Root);
	SetReplicates(false);
}

void ACWUnitVisual::Init(int32 InId, int32 InTeam, int32 InDef, FName VisualKey, float InMaxHp, float InMoveSpeed, float InWindup, float InX, float InLaneY)
{
	UnitId = InId;
	Team = InTeam;
	Def = InDef;
	MaxHp = FMath::Max(InMaxHp, 1.f);
	Hp = MaxHp;
	MoveSpeed = InMoveSpeed;
	Windup = FMath::Max(InWindup, 0.08f);
	TargetX = InX;
	VisualX = InX;
	Motion.Reset(InX);
	LaneY = InLaneY;
	CurrentYaw = Team == 0 ? 0.f : 180.f;
	SetActorLocationAndRotation(FVector(VisualX, LaneY, 0.f), FRotator(0.f, CurrentYaw, 0.f));

	SkeletalPresentation = UCWSkeletalUnitPresentation::TryCreate(this, Model, VisualKey, Team);
	if (SkeletalPresentation)
	{
		SkeletalPresentation->DescribeRig(Rig);
	}
	else
	{
		CWModels::BuildUnit(this, Model, VisualKey, Team, Rig);
	}
	if (Rig.ArmR)
	{
		Rig.ArmR->SetRelativeRotation(FRotator(Rig.ArmRestPitch, 0.f, 0.f));
	}
	if (Rig.ArmL && Rig.Style == ECWAttackStyle::Shoot)
	{
		Rig.ArmL->SetRelativeRotation(FRotator(80.f, 0.f, 0.f)); // 双手持弩/枪
	}
	if ((Rig.Style == ECWAttackStyle::Shoot || Rig.Style == ECWAttackStyle::Burst || Rig.Style == ECWAttackStyle::Cannon) && Rig.Muzzle)
	{
		CWVisual::FMaterialParams Flash = CWVisual::Paint(FLinearColor(1.f, 0.75f, 0.25f), 0.5f);
		Flash.Emissive = 30.f;
		const float FlashSize = Rig.Style == ECWAttackStyle::Cannon ? 46.f : 16.f;
		MuzzleFlash = CWVisual::AddPart(this, Rig.Muzzle, CWVisual::EShape::Sphere, FVector::ZeroVector, FVector(FlashSize), FRotator::ZeroRotator, Flash, false);
		MuzzleFlash->SetVisibility(false);
	}
	Model->SetRelativeScale3D(FVector(SkeletalPresentation ? 1.f : 0.6f));
	SpawnClock = 0.f;
}

void ACWUnitVisual::SetupChampion(float AuraRadius)
{
	bChampion = true;
	if (!AuraRing)
	{
		// A genuinely hollow perimeter keeps the aura readable without
		// bleaching the terrain beneath the champion.
		AuraRing = NewObject<UProceduralMeshComponent>(this);
		AddInstanceComponent(AuraRing);
		AuraRing->SetupAttachment(Root);
		AuraRing->SetRelativeLocation(FVector(0.f, 0.f, 2.f));
		AuraRing->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		AuraRing->SetGenerateOverlapEvents(false);
		AuraRing->SetCastShadow(false);
		AuraRing->RegisterComponent();
		AuraRing->SetMaterial(0, CWVisual::MakeWarningMaterial(AuraRing, CWVisual::TeamColor(Team), 0.22f));
	}
	const float OuterRadius = FMath::Max(AuraRadius, 50.f);
	const float InnerRadius = OuterRadius - FMath::Clamp(OuterRadius * 0.006f, 2.f, 4.f);
	constexpr int32 Segments = 128;
	TArray<FVector> Vertices, Normals;
	TArray<FVector2D> UVs;
	TArray<FLinearColor> Colors;
	TArray<int32> Triangles;
	for (int32 I = 0; I <= Segments; ++I)
	{
		const float Angle = 2.f * PI * I / Segments;
		const FVector Direction(FMath::Cos(Angle), FMath::Sin(Angle), 0.f);
		Vertices.Add(Direction * OuterRadius);
		Vertices.Add(Direction * InnerRadius);
		for (int32 Edge = 0; Edge < 2; ++Edge)
		{
			Normals.Add(FVector::UpVector);
			UVs.Add(FVector2D(static_cast<float>(I) / Segments, static_cast<float>(Edge)));
			Colors.Add(FLinearColor::White);
		}
		if (I < Segments)
		{
			const int32 V = I * 2;
			Triangles.Append({V, V + 1, V + 2, V + 2, V + 1, V + 3});
		}
	}
	const TArray<FProcMeshTangent> Tangents;
	AuraRing->CreateMeshSection_LinearColor(0, Vertices, Triangles, Normals, UVs, Colors, Tangents, false);
}

void ACWUnitVisual::ApplyNetState(const FCWUnitNetItem& Item)
{
	if (SkeletalPresentation)
	{
		SkeletalPresentation->ApplyState(Item, GetPresentationServerTime());
		AttackClock = SkeletalPresentation->GetAttackElapsed(GetPresentationServerTime());
	}
	TargetX = Item.X;
	Motion.Observe(TargetX);
	Hp = Item.Hp;
	MaxHp = FMath::Max(static_cast<float>(Item.MaxHp), 1.f);
	NetState = Item.State;
	if (!bRankInitialized)
	{
		Rank = Item.Rank;
		bRankInitialized = true;
	}
	else if (Item.Rank > Rank)
	{
		Rank = Item.Rank;
		bPromotedEvent = true;
	}
	const bool bNowRallied = (Item.Flags & CWUnitFlags::Rallied) != 0 && Item.State != static_cast<uint8>(cw::UnitState::Dying);
	if (bNowRallied != bRallied)
	{
		bRallied = bNowRallied;
		if (bRallied && !RallyRing)
		{
			// 战吼增益：脚下的金色光圈
			RallyRing = CWVisual::AddPart(this, Root, CWVisual::EShape::Cylinder, FVector(0.f, 0.f, 2.f), FVector(100.f, 100.f, 2.f),
				FRotator::ZeroRotator, CWVisual::Paint(FLinearColor::White), false);
			RallyRing->SetMaterial(0, CWVisual::MakeWarningMaterial(RallyRing, FLinearColor(1.f, 0.78f, 0.2f), 0.55f));
			const float D = FMath::Max(Rig.Height * 0.55f, 60.f) / 100.f;
			RallyRing->SetRelativeScale3D(FVector(D, D, 0.012f));
		}
		if (RallyRing)
		{
			RallyRing->SetVisibility(bRallied);
		}
	}
	if (!bSeqInitialized)
	{
		LastAttackSeq = Item.AttackSeq;
		LastHitSeq = Item.HitSeq;
		bSeqInitialized = true;
	}
	else
	{
		if (Item.AttackSeq != LastAttackSeq)
		{
			LastAttackSeq = Item.AttackSeq;
			if (!SkeletalPresentation) StartAttack();
		}
		if (Item.HitSeq != LastHitSeq)
		{
			LastHitSeq = Item.HitSeq;
			HitFlash = 0.15f;
			TimeSinceHit = 0.f;
			bHitEvent = true;
		}
	}
	if (Item.State == static_cast<uint8>(cw::UnitState::Dying) && !bDying)
	{
		bDying = true;
		bDeathEvent = true;
		DeathClock = 0.f;
		AttackClock = -1.f;
	}
}

bool ACWUnitVisual::ConsumeHitEvent()
{
	const bool bResult = bHitEvent;
	bHitEvent = false;
	return bResult;
}

bool ACWUnitVisual::ConsumeDeathEvent()
{
	const bool bResult = bDeathEvent;
	bDeathEvent = false;
	return bResult;
}

bool ACWUnitVisual::ConsumePromotionEvent()
{
	const bool bResult = bPromotedEvent;
	bPromotedEvent = false;
	return bResult;
}

void ACWUnitVisual::StartAttack()
{
	if (bDying)
	{
		return;
	}
	AttackClock = 0.f;
	bReleasePending = false;
	bReleasedThisAttack = false;
}

bool ACWUnitVisual::ConsumeReleaseEvent()
{
	const bool bResult = bReleasePending;
	bReleasePending = false;
	return bResult;
}

FVector ACWUnitVisual::GetMuzzleLocation() const
{
	if (SkeletalPresentation && SkeletalPresentation->HasMuzzleSocket()) return SkeletalPresentation->GetMuzzleLocation();
	return Rig.Muzzle ? Rig.Muzzle->GetComponentLocation() : GetActorLocation() + FVector(0.f, 0.f, Rig.Height * 0.6f);
}

FVector ACWUnitVisual::GetHitLocation() const
{
	return GetActorLocation() + FVector(0.f, 0.f, Rig.Height * 0.55f);
}

void ACWUnitVisual::UpdateVisual(float Dt)
{
	SpawnClock += Dt;
	TimeSinceHit += Dt;
	Model->SetRelativeScale3D(FVector(SkeletalPresentation ? 1.f : FMath::Min(1.f, 0.6f + SpawnClock / 0.25f * 0.4f)));

	if (bDying)
	{
		if (SkeletalPresentation)
		{
			DeathClock += Dt;
			if (AuraRing) AuraRing->SetVisibility(false);
			if (RallyRing) RallyRing->SetVisibility(false);
			if (MuzzleFlash) MuzzleFlash->SetVisibility(false);
			SkeletalPresentation->Update(Dt, 0.f, GetPresentationServerTime());
			// Finish the fall, briefly hold the corpse, then settle it out of view.
			// A late death packet must not be cut off by authoritative removal.
			const float Sink = FMath::Clamp((DeathClock - SkeletalPresentation->GetDeathDuration() - 0.25f) / 0.5f, 0.f, 1.f);
			Model->SetRelativeLocation(FVector(0.f, 0.f, -Rig.Height * Sink * Sink * (3.f - 2.f * Sink)));
			return;
		}
		AnimateDeath(Dt);
		ApplyFlash();
		return;
	}

	Motion.Advance(Dt);
	TraceMotion(Dt);
	VisualX = Motion.Position;
	SetActorLocation(FVector(VisualX, LaneY, 0.f));
	const float Speed = Motion.Speed;
	// 驻守后撤时转身面朝撤退方向；重新前进或开始攻击时转回
	const float Forward = Team == 0 ? 1.f : -1.f;
	const float Velocity = Motion.Velocity;
	if (Velocity * Forward < -20.f)
	{
		bFacingBack = true;
	}
	else if (Velocity * Forward > 20.f || AttackClock >= 0.f)
	{
		bFacingBack = false;
	}
	const float TargetYaw = (Team == 0 ? 0.f : 180.f) + (bFacingBack ? 180.f : 0.f);
	CurrentYaw = FMath::FixedTurn(CurrentYaw, TargetYaw, 540.f * Dt);
	SetActorRotation(FRotator(0.f, CurrentYaw, 0.f));
	if (SkeletalPresentation)
	{
		SkeletalPresentation->Update(Dt, Speed, GetPresentationServerTime());
		const bool bReleased = SkeletalPresentation->ConsumeReleaseEvent();
		bReleasePending |= bReleased;
		FlashClock = bReleased ? (Rig.Style == ECWAttackStyle::Cannon ? 0.09f : 0.06f) : FMath::Max(0.f, FlashClock - Dt);
		if (MuzzleFlash) MuzzleFlash->SetVisibility(FlashClock > 0.f);
		return;
	}
	AnimateWalk(Dt, Speed);

	if (AttackClock >= 0.f)
	{
		AttackClock += Dt;
		AnimateAttack();
		if (AttackClock > Windup + 0.5f)
		{
			AttackClock = -1.f;
			if (Rig.ArmR)
			{
				Rig.ArmR->SetRelativeRotation(FRotator(Rig.ArmRestPitch, 0.f, 0.f));
			}
		}
	}

	HitFlash = FMath::Max(0.f, HitFlash - Dt);
	ApplyFlash();
	FlashClock -= Dt;
	if (MuzzleFlash)
	{
		MuzzleFlash->SetVisibility(FlashClock > 0.f);
	}
}

bool ACWUnitVisual::KeepDeathVisual() const
{
	return bDying && SkeletalPresentation && DeathClock < SkeletalPresentation->GetDeathDuration() + 0.75f;
}

void ACWUnitVisual::TraceMotion(float Dt)
{
	static const bool bEnabled = FParse::Param(FCommandLine::Get(), TEXT("cwartmotion"));
	if (!bEnabled || bMotionTraceComplete || SpawnClock < 0.5f) return;
	const bool bWalking = NetState == static_cast<uint8>(cw::UnitState::Walking) && AttackClock < 0.f;
	if (MotionTrace.Advance(bWalking, Dt, FMath::Abs(Motion.Velocity)))
	{
		const bool bStartupFailed = MotionTrace.Status == FCWVisualMotionTrace::EStatus::StartupFailed;
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_UNIT_MOTION id=%d team=%d def=%d duration=%.3f frames=%d raw_speed_min=%.3f raw_speed_max=%.3f stopped_frames=%d buffer_seconds=0.100 status=%s startup_seconds=%.6f startup_frame_seconds=%.6f startup_limit_seconds=%.6f startup_frames=%d sample_policy=bounded_start_v1"),
			UnitId, Team, Def, MotionTrace.DurationSeconds, MotionTrace.Frames,
			MotionTrace.Frames ? MotionTrace.MinimumSpeed : 0.f, MotionTrace.MaximumSpeed, MotionTrace.StoppedFrames,
			bStartupFailed ? TEXT("startup_failed") : TEXT("complete"),
			MotionTrace.StartupSeconds, MotionTrace.StartupFrameSeconds, MotionTrace.StartupLimitSeconds, MotionTrace.StartupFrames);
		bMotionTraceComplete = true;
	}
}

float ACWUnitVisual::GetPresentationServerTime() const
{
	const AGameStateBase* State = GetWorld()->GetGameState();
	return State ? static_cast<float>(State->GetServerWorldTimeSeconds()) : GetWorld()->GetTimeSeconds();
}

void ACWUnitVisual::AnimateWalk(float Dt, float Speed)
{
	const bool bMoving = Speed > 5.f;
	if (bMoving)
	{
		WalkPhase += Dt * Speed / FMath::Max(Rig.StrideLength, 10.f) * PI;
	}
	const float Blend = bMoving ? 1.f : 0.f;
	const float S = FMath::Sin(WalkPhase) * Blend;

	if (Rig.LegL)
	{
		Rig.LegL->SetRelativeRotation(FRotator(S * 30.f, 0.f, 0.f));
	}
	if (Rig.LegR)
	{
		Rig.LegR->SetRelativeRotation(FRotator(-S * 30.f, 0.f, 0.f));
	}
	if (Rig.MountLegs.Num() == 4)
	{
		Rig.MountLegs[0]->SetRelativeRotation(FRotator(S * 26.f, 0.f, 0.f));
		Rig.MountLegs[1]->SetRelativeRotation(FRotator(-S * 26.f, 0.f, 0.f));
		Rig.MountLegs[2]->SetRelativeRotation(FRotator(-S * 26.f, 0.f, 0.f));
		Rig.MountLegs[3]->SetRelativeRotation(FRotator(S * 26.f, 0.f, 0.f));
	}
	if (Rig.Wheels.Num() > 0)
	{
		WheelAngle += Speed * Dt / 32.f * (180.f / PI);
		for (USceneComponent* Wheel : Rig.Wheels)
		{
			Wheel->SetRelativeRotation(FRotator(-WheelAngle, 0.f, 0.f));
		}
	}
	// 行走起伏；静止时轻微呼吸（整体上下移动，不改变部件布局）
	const float Bob = bMoving ? FMath::Abs(FMath::Sin(WalkPhase)) * (Rig.bVehicle ? 1.5f : 4.f) : FMath::Sin(SpawnClock * 2.2f) * 0.8f;
	Model->SetRelativeLocation(FVector(0.f, 0.f, Bob));
	if (AttackClock < 0.f)
	{
		if (Rig.ArmL && Rig.Style != ECWAttackStyle::Shoot)
		{
			Rig.ArmL->SetRelativeRotation(FRotator(-S * 22.f, 0.f, 0.f));
		}
		if (Rig.ArmR && (Rig.Style == ECWAttackStyle::Chop || Rig.Style == ECWAttackStyle::Throw))
		{
			Rig.ArmR->SetRelativeRotation(FRotator(Rig.ArmRestPitch + S * 14.f, 0.f, 0.f));
		}
	}
}

void ACWUnitVisual::AnimateAttack()
{
	const float T = AttackClock;
	const float W = Windup;
	const float Rest = Rig.ArmRestPitch;
	float Lean = 0.f;
	switch (Rig.Style)
	{
	case ECWAttackStyle::Chop:
	{
		float Pitch = Rest;
		if (T < W)
		{
			Pitch = FMath::Lerp(Rest, 165.f, CWEaseOut(T / W));
		}
		else if (T < W + 0.12f)
		{
			Pitch = FMath::Lerp(165.f, 25.f, (T - W) / 0.12f);
			Lean = -8.f;
		}
		else
		{
			Pitch = FMath::Lerp(25.f, Rest, FMath::Min(1.f, (T - W - 0.12f) / 0.3f));
		}
		if (Rig.ArmR)
		{
			Rig.ArmR->SetRelativeRotation(FRotator(Pitch, 0.f, 0.f));
		}
		break;
	}
	case ECWAttackStyle::Thrust:
	{
		float Offset = 0.f;
		if (T < W)
		{
			Offset = FMath::Lerp(0.f, -18.f, T / W);
			Lean = 4.f * (T / W);
		}
		else if (T < W + 0.1f)
		{
			Offset = FMath::Lerp(-18.f, 36.f, (T - W) / 0.1f);
			Lean = -7.f;
		}
		else
		{
			Offset = FMath::Lerp(36.f, 0.f, FMath::Min(1.f, (T - W - 0.1f) / 0.3f));
		}
		if (Rig.ArmR)
		{
			Rig.ArmR->SetRelativeRotation(FRotator(Rest, 0.f, 0.f));
			Rig.ArmR->SetRelativeLocation(FVector(Offset, 22.f, 46.f));
		}
		break;
	}
	case ECWAttackStyle::Throw:
	{
		float Pitch = Rest;
		if (T < W)
		{
			Pitch = FMath::Lerp(Rest, 215.f, T / W);
		}
		else if (T < W + 0.1f)
		{
			Pitch = FMath::Lerp(215.f, 50.f, (T - W) / 0.1f);
			Lean = -6.f;
		}
		else
		{
			Pitch = FMath::Lerp(50.f, Rest, FMath::Min(1.f, (T - W - 0.1f) / 0.3f));
		}
		if (Rig.ArmR)
		{
			Rig.ArmR->SetRelativeRotation(FRotator(Pitch, 0.f, 0.f));
		}
		break;
	}
	case ECWAttackStyle::Shoot:
	{
		const float Recoil = T >= W ? 12.f * FMath::Max(0.f, 1.f - (T - W) / 0.2f) : 0.f;
		if (Rig.ArmR)
		{
			Rig.ArmR->SetRelativeRotation(FRotator(Rest + Recoil, 0.f, 0.f));
		}
		if (Rig.ArmL)
		{
			Rig.ArmL->SetRelativeRotation(FRotator(80.f + Recoil, 0.f, 0.f));
		}
		Lean = Recoil * 0.3f;
		break;
	}
	case ECWAttackStyle::Burst:
	{
		if (Rig.Turret)
		{
			const float Kick = T >= W ? 4.f * FMath::Max(0.f, 1.f - (T - W) / 0.1f) : 0.f;
			Rig.Turret->SetRelativeLocation(Rig.TurretRest - FVector(Kick, 0.f, 0.f));
		}
		break;
	}
	case ECWAttackStyle::Cannon:
	{
		// 炮击：开火瞬间炮塔猛然后坐，随后缓慢复位；机甲身体随之后仰
		const float Kick = T >= W ? 14.f * FMath::Square(FMath::Max(0.f, 1.f - (T - W) / 0.35f)) : 0.f;
		if (Rig.Turret)
		{
			Rig.Turret->SetRelativeLocation(Rig.TurretRest - FVector(Kick, 0.f, 0.f));
		}
		Lean = Kick * 0.25f;
		break;
	}
	default:
		break;
	}
	if (Rig.Body && !Rig.bVehicle)
	{
		Rig.Body->SetRelativeRotation(FRotator(Lean, 0.f, 0.f));
	}
	if (T >= W && !bReleasedThisAttack)
	{
		bReleasedThisAttack = true;
		// 出手时刻：枪口火光，与服务器发射投射物的时间一致
		bReleasePending = true;
		FlashClock = Rig.Style == ECWAttackStyle::Cannon ? 0.09f : 0.06f;
	}
}

void ACWUnitVisual::AnimateDeath(float Dt)
{
	DeathClock += Dt;
	if (Rig.bVehicle)
	{
		Model->SetRelativeRotation(FRotator(FMath::Min(DeathClock / 0.6f, 1.f) * 6.f, 0.f, FMath::Min(DeathClock / 0.6f, 1.f) * 4.f));
	}
	else
	{
		Model->SetRelativeRotation(FRotator(CWEaseOut(DeathClock / 0.45f) * 82.f, 0.f, 0.f));
	}
	const float Sink = DeathClock > 0.8f ? (DeathClock - 0.8f) * 70.f : 0.f;
	Model->SetRelativeLocation(FVector(0.f, 0.f, -Sink));
	if (AuraRing)
	{
		AuraRing->SetVisibility(false);
	}
	if (RallyRing)
	{
		RallyRing->SetVisibility(false);
	}
	if (MuzzleFlash)
	{
		MuzzleFlash->SetVisibility(false);
	}
}

void ACWUnitVisual::ApplyFlash()
{
	const bool bNeedUpdate = HitFlash > 0.f || bDying || TimeSinceHit < 0.3f;
	if (!bNeedUpdate)
	{
		return;
	}
	const float Flash = HitFlash > 0.f ? (HitFlash / 0.15f) * 0.75f : 0.f;
	const float Dark = bDying ? FMath::Lerp(1.f, 0.3f, FMath::Min(1.f, DeathClock / 0.8f)) : 1.f;
	for (int32 I = 0; I < Rig.Materials.Num(); ++I)
	{
		const FLinearColor Base = Rig.BaseColors[I] * Dark;
		CWVisual::SetMaterialColor(Rig.Materials[I], FMath::Lerp(Base, FLinearColor::White, Flash));
	}
}
