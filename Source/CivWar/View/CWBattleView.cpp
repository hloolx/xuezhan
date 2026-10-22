#include "View/CWBattleView.h"

#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/World.h"
#include "HAL/PlatformTime.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "Sim/SimTypes.h"
#include "View/CWAudio.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Net/CWBattleReplicator.h"
#include "View/CWBaseVisual.h"
#include "View/CWModels.h"
#include "View/CWUnitVisual.h"

ACWBattleView::ACWBattleView()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	SetRootComponent(Root);
	SetReplicates(false);
}

void ACWBattleView::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	PresentationDelayProbe.Reset();
	if (ACWBattleReplicator* Rep = BoundReplicator.Get())
	{
		Rep->OnSkillImpact.Remove(SkillImpactHandle);
	}
	for (TPair<int32, TObjectPtr<ACWUnitVisual>>& Pair : Units)
	{
		if (Pair.Value)
		{
			Pair.Value->Destroy();
		}
	}
	Units.Reset();
	for (TObjectPtr<ACWBaseVisual>& Base : Bases)
	{
		if (Base)
		{
			Base->Destroy();
		}
	}
	Super::EndPlay(EndPlayReason);
}

ACWUnitVisual* ACWBattleView::FindUnit(int32 Id) const
{
	const TObjectPtr<ACWUnitVisual>* Found = Units.Find(Id);
	return Found ? Found->Get() : nullptr;
}

ACWBaseVisual* ACWBattleView::GetBase(int32 Team) const
{
	return Team >= 0 && Team < 2 ? Bases[Team].Get() : nullptr;
}

float ACWBattleView::LaneYForRow(int32 Row, int32 Id) const
{
	const float Center = (LaneRows - 1) * 0.5f;
	const float Jitter = static_cast<float>((Id * 37) % 21 - 10);
	return (Row - Center) * RowSpacing + Jitter;
}

bool ACWBattleView::EnsureInitialized()
{
	if (bInitialized)
	{
		return true;
	}
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!DataSys || !DataSys->IsLoaded())
	{
		return false;
	}
	const cw::RulesDef& Rules = DataSys->GetData().Rules;
	LaneLength = Rules.LaneLength;
	LaneRows = Rules.LaneRows;
	RowSpacing = Rules.RowSpacing;
	for (int32 T = 0; T < 2; ++T)
	{
		FActorSpawnParameters Params;
		Params.Owner = this;
		Bases[T] = GetWorld()->SpawnActor<ACWBaseVisual>(Params);
		Bases[T]->Init(T, T == 0 ? 0.f : LaneLength, Rules.BaseHalfWidth);
		Bases[T]->OnTurretFired.AddUObject(this, &ACWBattleView::HandleTurretFired);
	}
	CWVisual::FMaterialParams Preview = CWVisual::Paint(FLinearColor(0.2f, 1.f, 0.3f), 0.5f);
	Preview.Emissive = 2.f;
	TargetDisk = CWVisual::AddPart(this, GetRootComponent(), CWVisual::EShape::Cylinder, FVector(0.f, 0.f, 3.f), FVector(100.f, 100.f, 2.f),
		FRotator::ZeroRotator, Preview, false);
	TargetDisk->SetVisibility(false);
	for (int32 T = 0; T < 2; ++T)
	{
		// 旗杆 + 阵营色旗面：标记统帅的坚守位置
		HoldFlags[T] = CWVisual::AddPivot(this, GetRootComponent(), FVector::ZeroVector);
		CWVisual::AddPart(this, HoldFlags[T], CWVisual::EShape::Cylinder, FVector(0.f, 0.f, 90.f), FVector(5.f, 5.f, 180.f),
			FRotator::ZeroRotator, CWVisual::Metal(FLinearColor(0.3f, 0.3f, 0.32f)), false);
		CWVisual::FMaterialParams Cloth = CWVisual::Paint(CWVisual::TeamColor(T), 0.6f);
		Cloth.Emissive = 1.5f;
		CWVisual::AddPart(this, HoldFlags[T], CWVisual::EShape::Cube, FVector(T == 0 ? 26.f : -26.f, 0.f, 158.f), FVector(48.f, 3.f, 32.f),
			FRotator::ZeroRotator, Cloth, false);
		HoldFlags[T]->SetVisibility(false, true);
	}
	bInitialized = true;
	return true;
}

void ACWBattleView::SetTargetingPreview(bool bVisible, float X, float Radius, bool bValid)
{
	if (!TargetDisk)
	{
		return;
	}
	TargetDisk->SetVisibility(bVisible);
	if (bVisible)
	{
		TargetDisk->SetWorldLocation(FVector(X, 0.f, 4.f));
		TargetDisk->SetWorldScale3D(FVector(Radius * 2.f / 100.f, Radius * 2.f / 100.f, 0.02f));
		CWVisual::SetMaterialColor(Cast<UMaterialInstanceDynamic>(TargetDisk->GetMaterial(0)),
			bValid ? FLinearColor(0.2f, 1.f, 0.3f) : FLinearColor(1.f, 0.15f, 0.1f));
	}
}

void ACWBattleView::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	if (!EnsureInitialized())
	{
		return;
	}
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	if (!State)
	{
		return;
	}
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();

	// 绑定技能落地事件
	ACWBattleReplicator* Rep = State->GetReplicator();
	if (Rep && BoundReplicator.Get() != Rep)
	{
		PresentationDelayProbe.Reset();
		if (ACWBattleReplicator* Old = BoundReplicator.Get())
		{
			Old->OnSkillImpact.Remove(SkillImpactHandle);
		}
		SkillImpactHandle = Rep->OnSkillImpact.AddUObject(this, &ACWBattleView::HandleSkillImpact);
		BoundReplicator = Rep;
	}

	// 新对局开始：基地外观静默恢复到石器时代
	const uint8 Phase = static_cast<uint8>(State->GetPhase());
	if (Phase != LastPhase)
	{
		const bool bEnterCountdown = State->GetPhase() == ECWMatchPhase::Countdown;
		const bool bEnterMatchDirect = State->GetPhase() == ECWMatchPhase::InMatch && LastPhase != static_cast<uint8>(ECWMatchPhase::Countdown);
		if (bEnterCountdown || bEnterMatchDirect)
		{
			PresentationDelayProbe.Reset();
			for (TObjectPtr<ACWBaseVisual>& Base : Bases)
			{
				if (Base)
				{
					Base->ResetForMatch();
				}
			}
		}
		LastPhase = Phase;
	}

	// 基地（菜单/房间阶段也显示，作为背景）
	const bool bHasMatchState = State->GetPhase() == ECWMatchPhase::InMatch || State->GetPhase() == ECWMatchPhase::PostMatch;
	const ACWPlayerController* LocalPC = Cast<ACWPlayerController>(GetWorld()->GetFirstPlayerController());
	const int32 LocalTeam = LocalPC ? LocalPC->GetTeam() : 0;
	for (int32 T = 0; T < 2; ++T)
	{
		if (Bases[T])
		{
			if (bHasMatchState)
			{
				Bases[T]->SyncState(State->GetTeam(T), DataSys);
				if (Bases[T]->ConsumeHitEvent())
				{
					CWAudio::PlayAt(this, CWAudio::ESound::BaseHit, Bases[T]->GetGateLocation(), 0.8f);
				}
				if (Bases[T]->ConsumeBuildEvent())
				{
					CWAudio::PlayAt(this, CWAudio::ESound::TurretBuild, Bases[T]->GetGateLocation(), 0.9f);
				}
				if (Bases[T]->ConsumeAgeUpEvent())
				{
					// 己方升级：全屏号角；敌方升级：战场方位音效，提醒对手进入新时代
					if (T == LocalTeam)
					{
						CWAudio::Play2D(this, CWAudio::ESound::AgeUp, 0.9f);
					}
					else
					{
						CWAudio::PlayAt(this, CWAudio::ESound::AgeUp, Bases[T]->GetGateLocation(), 0.6f, 0.9f);
					}
				}
			}
			Bases[T]->UpdateVisual(DeltaSeconds);
		}
	}

	SyncUnits(DeltaSeconds);
	if (bHasMatchState)
	{
		SyncChampionMarkers(*State);
	}
	SyncProjectiles(DeltaSeconds);
	UpdateProjectiles(DeltaSeconds);
	SyncSkills(DeltaSeconds);
	UpdateEffects(DeltaSeconds);
}

void ACWBattleView::SyncUnits(float Dt)
{
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	const ACWBattleReplicator* Rep = State ? State->GetReplicator() : nullptr;
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!Rep || !DataSys)
	{
		return;
	}
	const cw::GameData& Data = DataSys->GetData();
	TSet<int32> Present;
	const TArray<FCWUnitNetItem>& PresentationItems = PresentationDelayProbe.Resolve(Rep->GetUnits().Items, Data,
		FPlatformTime::Seconds(), State->GetServerWorldTimeSeconds(), GetNetMode() == NM_Standalone);
	for (const FCWUnitNetItem& Item : PresentationItems)
	{
		if (Item.Def >= Data.Units.size())
		{
			continue; // 数据不一致时忽略（数据校验会提示玩家）
		}
		Present.Add(Item.Id);
		TObjectPtr<ACWUnitVisual>* Found = Units.Find(Item.Id);
		ACWUnitVisual* Visual = Found ? Found->Get() : nullptr;
		if (Visual && Visual->GetDef() != Item.Def)
		{
			// 统帅随时代进化：换成新时代的模型，并播放一次光柱
			const FVector At = Visual->GetActorLocation();
			Visual->Destroy();
			Units.Remove(Item.Id);
			Visual = nullptr;
			SpawnBeam(At, 1600.f, 140.f, FLinearColor(1.f, 0.8f, 0.3f), 0.9f, 12.f);
			SpawnBurst(At + FVector(0.f, 0.f, 80.f), 260.f, FLinearColor(1.f, 0.85f, 0.4f), 0.5f, 60000.f, 10.f);
		}
		if (!Visual)
		{
			const cw::UnitDef& Def = Data.Units[Item.Def];
			FActorSpawnParameters Params;
			Params.Owner = this;
			Visual = GetWorld()->SpawnActor<ACWUnitVisual>(Params);
			const bool bChampion = (Item.Flags & CWUnitFlags::Champion) != 0;
			// 统帅走在靠近镜头一侧，避免被部队挡住
			const float LaneY = bChampion ? (Item.Team == 0 ? 1.f : -1.f) * RowSpacing * (LaneRows * 0.5f + 0.4f) : LaneYForRow(Item.Row, Item.Id);
			Visual->Init(Item.Id, Item.Team, Item.Def, DataSys->GetUnitVisualKey(Item.Def), FMath::Max(static_cast<float>(Item.MaxHp), Def.MaxHp),
				Def.MoveSpeed, Def.AttackWindup, Item.X, LaneY);
			if (bChampion)
			{
				for (const cw::ChampionDef& C : Data.Champions)
				{
					if (C.UnitDefIndex == static_cast<int32>(Item.Def))
					{
						Visual->SetupChampion(C.AuraRadius);
					}
				}
			}
			Units.Add(Item.Id, Visual);
			CWAudio::PlayAt(this, CWAudio::ESound::Train, Visual->GetActorLocation(), 0.35f, Item.Team == 0 ? 1.f : 0.92f);
		}
		Visual->ApplyNetState(Item);
		Visual->UpdateVisual(Dt);
		PlayUnitSounds(Visual, Item);
		if (Visual->ConsumePromotionEvent())
		{
			// 晋升老兵：金色闪光 + 清脆提示音
			SpawnBurst(Visual->GetHitLocation() + FVector(0.f, 0.f, 40.f), 120.f, FLinearColor(1.f, 0.8f, 0.25f), 0.45f, 20000.f, 12.f);
			CWAudio::PlayAt(this, CWAudio::ESound::Train, Visual->GetActorLocation(), 0.55f, 1.7f);
		}
	}
	for (auto It = Units.CreateIterator(); It; ++It)
	{
		if (!Present.Contains(It.Key()))
		{
			if (It.Value() && It.Value()->KeepDeathVisual())
			{
				// Cosmetic only: the removed unit cannot block, attack or return to
				// the simulation. Finish a late-arriving fall before recycling it.
				It.Value()->UpdateVisual(Dt);
				continue;
			}
			if (It.Value())
			{
				It.Value()->Destroy();
			}
			It.RemoveCurrent();
		}
	}
}

void ACWBattleView::PlayUnitSounds(ACWUnitVisual* Visual, const FCWUnitNetItem& Item)
{
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!Visual || !DataSys)
	{
		return;
	}
	const cw::UnitDef& Def = DataSys->GetData().Units[Item.Def];
	const FVector Location = Visual->GetActorLocation();
	const float Pitch = FMath::FRandRange(0.92f, 1.08f);
	if (Visual->ConsumeReleaseEvent())
	{
		// 出手/命中时刻：与服务器结算伤害或发射投射物的时刻一致
		switch (Visual->GetAttackStyle())
		{
		case ECWAttackStyle::Chop:
		case ECWAttackStyle::Thrust:
			CWAudio::PlayAt(this, CWAudio::ESound::Swing, Location, 0.7f, Pitch);
			break;
		case ECWAttackStyle::Throw:
			CWAudio::PlayAt(this, CWAudio::ESound::Sling, Location, 0.7f, Pitch);
			break;
		case ECWAttackStyle::Shoot:
			if (Def.DmgType == cw::DamageType::Siege)
			{
				CWAudio::PlayAt(this, CWAudio::ESound::Rocket, Location, 0.65f, Pitch);
			}
			else if (Def.DmgType == cw::DamageType::Energy)
			{
				CWAudio::PlayAt(this, CWAudio::ESound::Laser, Location, 0.65f, Pitch);
			}
			else
			{
				CWAudio::PlayAt(this, Def.DmgType == cw::DamageType::Pierce && Def.ProjectileSpeed > 3000.f ? CWAudio::ESound::Gun : CWAudio::ESound::Bow,
					Location, 0.75f, Pitch);
			}
			break;
		case ECWAttackStyle::Burst:
			CWAudio::PlayAt(this, CWAudio::ESound::MachineGun, Location, 0.6f, Pitch);
			break;
		case ECWAttackStyle::Cannon:
			// 坦克炮声低沉；机甲等离子炮音调更高
			CWAudio::PlayAt(this, CWAudio::ESound::Cannon, Location, 0.8f, Visual->IsVehicle() ? 0.9f * Pitch : 1.35f * Pitch);
			break;
		default:
			break;
		}
	}
	if (Visual->ConsumeHitEvent())
	{
		const bool bMetal = Def.Armor == cw::ArmorType::Heavy || Def.Armor == cw::ArmorType::Shielded;
		CWAudio::PlayAt(this, bMetal ? CWAudio::ESound::HitMetal : CWAudio::ESound::HitFlesh, Location, 0.6f, Pitch);
	}
	if (Visual->ConsumeDeathEvent())
	{
		const bool bMachine = Visual->IsVehicle() || Visual->GetAttackStyle() == ECWAttackStyle::Cannon; // 载具与机甲：爆炸声
		CWAudio::PlayAt(this, bMachine ? CWAudio::ESound::Explosion : CWAudio::ESound::Death, Location, 0.7f,
			Def.Role == cw::UnitRole::Heavy ? 0.8f : Pitch);
	}
}

UStaticMeshComponent* ACWBattleView::AcquireMesh(CWVisual::EShape Shape, const FLinearColor& Color, float Emissive, bool bShadow)
{
	TArray<UStaticMeshComponent*>& Free = Pool[static_cast<int32>(Shape)];
	UStaticMeshComponent* Mesh = nullptr;
	if (Free.Num() > 0)
	{
		Mesh = Free.Pop(EAllowShrinking::No);
	}
	else
	{
		CWVisual::FMaterialParams Params = CWVisual::Paint(Color, 0.6f);
		Mesh = CWVisual::AddPart(this, GetRootComponent(), Shape, FVector::ZeroVector, FVector(10.f), FRotator::ZeroRotator, Params, false);
		AllPooledMeshes.Add(Mesh);
	}
	UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(Mesh->GetMaterial(0));
	CWVisual::SetMaterialColor(Mid, Color);
	CWVisual::SetMaterialEmissive(Mid, Emissive);
	Mesh->SetCastShadow(bShadow);
	Mesh->SetVisibility(true);
	return Mesh;
}

void ACWBattleView::ReleaseMesh(UStaticMeshComponent* Mesh, CWVisual::EShape Shape)
{
	if (Mesh)
	{
		Mesh->SetVisibility(false);
		Pool[static_cast<int32>(Shape)].Add(Mesh);
	}
}

void ACWBattleView::SyncProjectiles(float Dt)
{
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	const ACWBattleReplicator* Rep = State ? State->GetReplicator() : nullptr;
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!Rep || !DataSys)
	{
		return;
	}
	TSet<int32> Live;
	for (const FCWProjectileNetItem& Item : Rep->GetProjectiles().Items)
	{
		Live.Add(Item.Id);
		if (SeenProjectiles.Contains(Item.Id))
		{
			continue;
		}
		SeenProjectiles.Add(Item.Id);

		const bool bTurret = Item.SourceSlot >= 0;
		const FName Key = bTurret ? DataSys->GetTurretVisualKey(Item.VisualDef) : DataSys->GetUnitVisualKey(Item.VisualDef);
		const CWModels::FProjectileLook Look = CWModels::GetProjectileLook(Key);

		FProjectileVisual P;
		P.Id = Item.Id;
		P.Team = Item.Team;
		P.TargetId = Item.TargetId;
		P.Shape = Look.Shape;
		P.Arc = Look.ArcHeight;
		P.bAlign = Look.bAlignToVelocity;
		P.Splash = Item.Splash;
		if (bTurret && Bases[Item.Team])
		{
			P.Start = Bases[Item.Team]->GetTurretMuzzle(Item.SourceSlot);
		}
		else if (const ACWUnitVisual* Shooter = FindUnit(Item.SourceUnit))
		{
			P.Start = Shooter->GetMuzzleLocation();
		}
		else
		{
			P.Start = FVector(Item.StartX, 0.f, 120.f);
		}
		if (Item.TargetId == -2 && Bases[1 - Item.Team])
		{
			P.Target = Bases[1 - Item.Team]->GetGateLocation();
		}
		else if (const ACWUnitVisual* Target = FindUnit(Item.TargetId))
		{
			P.Target = Target->GetHitLocation();
		}
		else
		{
			P.Target = FVector(Item.TargetX, 0.f, 100.f);
		}
		P.Duration = FMath::Max(0.05f, FMath::Abs(Item.TargetX - Item.StartX) / FMath::Max(Item.Speed, 1.f));
		P.PrevPos = P.Start;
		P.Mesh = AcquireMesh(Look.Shape, Look.Color, Look.Emissive, false);
		P.Mesh->SetWorldLocation(P.Start);
		P.Mesh->SetWorldScale3D(Look.Size / 100.f);
		Projectiles.Add(P);
	}
	// 清理已不在列表中的编号记录
	for (auto It = SeenProjectiles.CreateIterator(); It; ++It)
	{
		if (!Live.Contains(*It))
		{
			bool bStillFlying = false;
			for (const FProjectileVisual& P : Projectiles)
			{
				bStillFlying |= P.Id == *It;
			}
			if (!bStillFlying)
			{
				It.RemoveCurrent();
			}
		}
	}
}

void ACWBattleView::UpdateProjectiles(float Dt)
{
	for (int32 I = Projectiles.Num() - 1; I >= 0; --I)
	{
		FProjectileVisual& P = Projectiles[I];
		P.Elapsed += Dt;
		if (!P.bCosmetic)
		{
			if (P.TargetId == -2 && Bases[1 - P.Team])
			{
				P.Target = Bases[1 - P.Team]->GetGateLocation();
			}
			else if (const ACWUnitVisual* Target = FindUnit(P.TargetId))
			{
				if (!Target->IsDying())
				{
					P.Target = Target->GetHitLocation(); // 追踪目标的表现位置
				}
			}
		}
		const float Alpha = FMath::Clamp(P.Elapsed / P.Duration, 0.f, 1.f);
		const FVector Pos = FMath::Lerp(P.Start, P.Target, Alpha) + FVector(0.f, 0.f, P.Arc * 4.f * Alpha * (1.f - Alpha));
		P.Mesh->SetWorldLocation(Pos);
		if (P.bAlign)
		{
			const FVector Dir = (Pos - P.PrevPos).GetSafeNormal();
			if (!Dir.IsNearlyZero())
			{
				P.Mesh->SetWorldRotation(FRotationMatrix::MakeFromZ(Dir).Rotator());
			}
		}
		P.PrevPos = Pos;
		if (Alpha >= 1.f)
		{
			if (!P.bImpactFx)
			{
				// 只是飞过战场
			}
			else if (P.Splash > 0.f)
			{
				SpawnBurst(P.Target, P.Splash * 1.6f, FLinearColor(1.f, 0.55f, 0.15f), 0.35f, 40000.f, 8.f);
				SpawnDebris(P.Target, 6, FLinearColor(0.35f, 0.28f, 0.2f), 500.f);
				CWAudio::PlayAt(this, CWAudio::ESound::Explosion, P.Target, FMath::Clamp(P.Splash / 140.f, 0.35f, 1.f), FMath::FRandRange(0.9f, 1.1f));
			}
			else
			{
				SpawnBurst(P.Target, 28.f, FLinearColor(0.8f, 0.75f, 0.6f), 0.18f, 0.f, 1.f);
			}
			ReleaseMesh(P.Mesh, P.Shape);
			Projectiles.RemoveAtSwap(I);
		}
	}
}

void ACWBattleView::SpawnFalling(const FVector& From, const FVector& To, float Duration, CWVisual::EShape Shape, const FVector& Size,
	const FLinearColor& Color, float Splash, float Emissive, bool bImpactFx)
{
	FProjectileVisual P;
	P.Id = -1;
	P.bCosmetic = true;
	P.Shape = Shape;
	P.Start = From;
	P.Target = To;
	P.PrevPos = From;
	P.Duration = FMath::Max(Duration, 0.05f);
	P.bAlign = Shape == CWVisual::EShape::Cylinder;
	P.Splash = Splash;
	P.bImpactFx = bImpactFx;
	P.Mesh = AcquireMesh(Shape, Color, Emissive, Emissive <= 0.f);
	P.Mesh->SetWorldLocation(From);
	P.Mesh->SetWorldScale3D(Size / 100.f);
	Projectiles.Add(P);
}

void ACWBattleView::SyncSkills(float Dt)
{
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!State || !DataSys)
	{
		return;
	}
	const float Now = static_cast<float>(State->GetServerWorldTimeSeconds());
	TSet<int32> Live;
	for (const FCWSkillCastNet& Cast : State->GetSkillCasts())
	{
		Live.Add(Cast.Id);
		FWarning* Existing = Warnings.FindByPredicate([&Cast](const FWarning& W) { return W.Id == Cast.Id; });
		if (!Existing)
		{
			FWarning W;
			W.Id = Cast.Id;
			W.Skill = Cast.Skill;
			W.X = Cast.X;
			W.Radius = Cast.Radius;
			W.ImpactTime = Cast.ImpactServerTime;
			// 预警圈：施放方颜色的半透明地面标记（逐渐填满）+ 红色外圈；独立创建，不放入对象池
			W.Disk = CWVisual::AddPart(this, GetRootComponent(), CWVisual::EShape::Cylinder, FVector::ZeroVector, FVector(100.f, 100.f, 2.f),
				FRotator::ZeroRotator, CWVisual::Paint(FLinearColor::White), false);
			W.Disk->SetMaterial(0, CWVisual::MakeWarningMaterial(W.Disk, CWVisual::TeamColor(Cast.Team), 0.35f));
			W.Edge = CWVisual::AddPart(this, GetRootComponent(), CWVisual::EShape::Cylinder, FVector::ZeroVector, FVector(100.f, 100.f, 2.f),
				FRotator::ZeroRotator, CWVisual::Paint(FLinearColor::White), false);
			W.Edge->SetMaterial(0, CWVisual::MakeWarningMaterial(W.Edge, FLinearColor(1.f, 0.12f, 0.05f), 0.5f));
			CWAudio::PlayAt(this, CWAudio::ESound::SkillWarning, FVector(Cast.X, 0.f, 50.f), 0.8f);
			Warnings.Add(W);
			Existing = &Warnings.Last();
		}
		FWarning& W = *Existing;
		const float TimeLeft = W.ImpactTime - Now;
		const float Pulse = 1.f + 0.05f * FMath::Sin(Now * 14.f);
		const float D = W.Radius * 2.f / 100.f;
		W.Edge->SetWorldLocation(FVector(W.X, 0.f, 2.f));
		W.Edge->SetWorldScale3D(FVector(D * Pulse, D * Pulse, 0.015f));
		W.Disk->SetWorldLocation(FVector(W.X, 0.f, 3.f));
		const float Fill = FMath::Clamp(1.f - TimeLeft / 1.8f, 0.05f, 1.f); // 内圈逐渐扩大：直观显示剩余时间
		W.Disk->SetWorldScale3D(FVector(D * 0.96f * Fill, D * 0.96f * Fill, 0.02f));

		// 落下物在结算时刻落地
		if (!W.bIncomingSpawned && TimeLeft < 0.45f)
		{
			W.bIncomingSpawned = true;
			const float Fall = FMath::Max(TimeLeft, 0.1f);
			const FString Key = SkillVisualKey(W.Skill);
			if (Key == TEXT("Skill_ArrowRain"))
			{
				for (int32 I = 0; I < 36; ++I)
				{
					const FVector To(W.X + FMath::FRandRange(-W.Radius, W.Radius), FMath::FRandRange(-160.f, 160.f), 0.f);
					SpawnFalling(To + FVector(-250.f, 0.f, 1400.f), To, Fall, CWVisual::EShape::Cylinder, FVector(3.f, 3.f, 55.f), FLinearColor(0.35f, 0.22f, 0.1f), 0.f);
				}
			}
			else if (Key == TEXT("Skill_Artillery"))
			{
				for (int32 I = 0; I < 6; ++I)
				{
					const FVector To(W.X + FMath::FRandRange(-W.Radius * 0.8f, W.Radius * 0.8f), FMath::FRandRange(-120.f, 120.f), 0.f);
					SpawnFalling(To + FVector(-400.f, 0.f, 2200.f), To, Fall * FMath::FRandRange(0.85f, 1.f), CWVisual::EShape::Sphere, FVector(20.f), FLinearColor(0.1f, 0.1f, 0.1f), 120.f);
				}
			}
			else if (Key == TEXT("Skill_Airstrike"))
			{
				// 两架战机低空掠过，沿预警范围投下一串炸弹
				const float Dir = FMath::RandBool() ? 1.f : -1.f;
				for (int32 Jet = 0; Jet < 2; ++Jet)
				{
					const FVector JetFrom(W.X - Dir * 3200.f, -60.f + Jet * 120.f, 1300.f + Jet * 120.f);
					const FVector JetTo(W.X + Dir * 3200.f, -60.f + Jet * 120.f, 1300.f + Jet * 120.f);
					SpawnFalling(JetFrom, JetTo, 1.4f, CWVisual::EShape::Cone, FVector(70.f, 70.f, 260.f), FLinearColor(0.3f, 0.32f, 0.35f), 0.f, 0.f, false);
				}
				for (int32 I = 0; I < 8; ++I)
				{
					const float T = (I + 0.5f) / 8.f;
					const FVector To(W.X + (T * 2.f - 1.f) * W.Radius * Dir * 0.9f, FMath::FRandRange(-120.f, 120.f), 0.f);
					SpawnFalling(To + FVector(-Dir * 500.f, 0.f, 1250.f), To, Fall * (0.75f + 0.25f * T), CWVisual::EShape::Cylinder, FVector(16.f, 16.f, 60.f),
						FLinearColor(0.12f, 0.13f, 0.12f), 80.f);
				}
			}
			else if (Key == TEXT("Skill_OrbitalBeam"))
			{
				// 瞄准光束：细光柱锁定目标，结算时刻换成粗光柱
				SpawnBeam(FVector(W.X, 0.f, 0.f), 5000.f, 26.f, FLinearColor(0.5f, 0.9f, 1.f), Fall + 0.1f, 18.f);
			}
			else
			{
				const FVector To(W.X, 0.f, 0.f);
				SpawnFalling(To + FVector(-700.f, 0.f, 2600.f), To, Fall, CWVisual::EShape::Sphere, FVector(130.f), FLinearColor(0.3f, 0.2f, 0.15f), 0.f);
				CWAudio::PlayAt(this, CWAudio::ESound::MeteorFall, To + FVector(0.f, 0.f, 300.f), 0.9f);
			}
		}
	}
	for (int32 I = Warnings.Num() - 1; I >= 0; --I)
	{
		if (!Live.Contains(Warnings[I].Id))
		{
			Warnings[I].Disk->DestroyComponent();
			Warnings[I].Edge->DestroyComponent();
			Warnings.RemoveAtSwap(I);
		}
	}
}

void ACWBattleView::HandleSkillImpact(uint8 Team, uint8 Skill, float X, float Radius, int32 Hits)
{
	if (SkillVisualKey(Skill) == TEXT("Skill_OrbitalBeam"))
	{
		// 轨道光束：粗光柱 + 青白色冲击
		SpawnBeam(FVector(X, 0.f, 0.f), 5000.f, Radius * 1.1f, FLinearColor(0.6f, 0.95f, 1.f), 0.9f, 40.f);
		SpawnBurst(FVector(X, 0.f, 20.f), Radius * 1.5f, FLinearColor(0.5f, 0.9f, 1.f), 0.6f, 150000.f, 20.f);
		SpawnDebris(FVector(X, 0.f, 20.f), 10, FLinearColor(0.25f, 0.25f, 0.28f), 900.f);
		CWAudio::PlayAt(this, CWAudio::ESound::Explosion, FVector(X, 0.f, 50.f), 1.f, 1.3f);
		CWAudio::PlayAt(this, CWAudio::ESound::MeteorFall, FVector(X, 0.f, 300.f), 0.7f, 1.6f);
		return;
	}
	// 结算时刻的爆炸表现
	SpawnBurst(FVector(X, 0.f, 20.f), Radius * 1.4f, FLinearColor(1.f, 0.5f, 0.12f), 0.5f, 120000.f, 10.f);
	for (int32 I = 0; I < 5; ++I)
	{
		const FVector P(X + FMath::FRandRange(-Radius, Radius), FMath::FRandRange(-150.f, 150.f), 10.f);
		SpawnBurst(P, Radius * 0.5f, FLinearColor(0.45f, 0.38f, 0.3f), 0.7f, 0.f, 0.f);
	}
	SpawnDebris(FVector(X, 0.f, 20.f), 14, FLinearColor(0.35f, 0.28f, 0.2f), 800.f);
	CWAudio::PlayAt(this, CWAudio::ESound::Explosion, FVector(X, 0.f, 50.f), 1.f, 0.85f);
	CWAudio::PlayAt(this, CWAudio::ESound::Cannon, FVector(X, 0.f, 50.f), 0.8f, 0.8f);
}

void ACWBattleView::HandleTurretFired(int32 Team, int32 Slot, int32 TurretDef, FVector Muzzle)
{
	SpawnBurst(Muzzle, 30.f, FLinearColor(1.f, 0.8f, 0.4f), 0.08f, 8000.f, 20.f);
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	const FString Key = DataSys && TurretDef >= 0 ? DataSys->GetTurretVisualKey(TurretDef).ToString() : FString();
	if (Key == TEXT("Turret_RockTower"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Sling, Muzzle, 0.8f, 0.6f);
	}
	else if (Key == TEXT("Turret_ArrowTower"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Bow, Muzzle, 0.7f, 1.05f);
	}
	else if (Key == TEXT("Turret_Ballista"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Bow, Muzzle, 0.9f, 0.7f);
	}
	else if (Key == TEXT("Turret_MachineGun"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::MachineGun, Muzzle, 0.6f, 1.1f);
	}
	else if (Key == TEXT("Turret_Autocannon"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::MachineGun, Muzzle, 0.75f, 0.75f);
	}
	else if (Key == TEXT("Turret_MissileBattery"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Rocket, Muzzle, 0.7f, 1.f);
	}
	else if (Key == TEXT("Turret_LaserTower"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Laser, Muzzle, 0.7f, 1.f);
	}
	else if (Key == TEXT("Turret_IonCannon"))
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Cannon, Muzzle, 0.9f, 1.4f);
	}
	else
	{
		CWAudio::PlayAt(this, CWAudio::ESound::Cannon, Muzzle, 0.9f);
	}
}

void ACWBattleView::SpawnBurst(const FVector& Location, float Size, const FLinearColor& Color, float Duration, float LightIntensity, float Emissive)
{
	FEffect E;
	E.Shape = CWVisual::EShape::Sphere;
	E.Mesh = AcquireMesh(E.Shape, Color, Emissive, false);
	E.Mesh->SetWorldLocation(Location);
	E.Mesh->SetWorldRotation(FRotator::ZeroRotator);
	E.StartSize = Size * 0.3f;
	E.EndSize = Size;
	E.Duration = Duration;
	if (LightIntensity > 0.f)
	{
		UPointLightComponent* Light = NewObject<UPointLightComponent>(this);
		Light->SetupAttachment(GetRootComponent());
		Light->SetWorldLocation(Location + FVector(0.f, 0.f, 60.f));
		Light->SetLightColor(Color);
		Light->SetIntensity(LightIntensity);
		Light->SetAttenuationRadius(Size * 3.f);
		Light->SetCastShadows(false);
		Light->RegisterComponent();
		E.Light = Light;
		E.LightIntensity = LightIntensity;
	}
	Effects.Add(E);
}

void ACWBattleView::SpawnBeam(const FVector& Ground, float Height, float Width, const FLinearColor& Color, float Duration, float Emissive)
{
	FEffect E;
	E.Shape = CWVisual::EShape::Cylinder;
	E.Mesh = AcquireMesh(E.Shape, Color, Emissive, false);
	E.Mesh->SetWorldLocation(Ground + FVector(0.f, 0.f, Height * 0.5f));
	E.Mesh->SetWorldRotation(FRotator::ZeroRotator);
	E.StartSize = Width * 0.2f;
	E.EndSize = Width;
	E.Duration = Duration;
	E.FixedHeight = Height;
	Effects.Add(E);
}

void ACWBattleView::SpawnGroundPulse(const FVector& Center, float Diameter, const FLinearColor& Color, float Duration, float Emissive)
{
	FEffect E;
	E.Shape = CWVisual::EShape::Cylinder;
	E.Mesh = AcquireMesh(E.Shape, Color, Emissive, false);
	E.Mesh->SetWorldLocation(Center + FVector(0.f, 0.f, 6.f));
	E.Mesh->SetWorldRotation(FRotator::ZeroRotator);
	E.StartSize = Diameter * 0.15f;
	E.EndSize = Diameter;
	E.Duration = Duration;
	E.FixedHeight = 4.f;
	Effects.Add(E);
}

void ACWBattleView::SyncChampionMarkers(const ACWGameState& State)
{
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!DataSys || DataSys->GetData().Champions.empty())
	{
		return;
	}
	const cw::GameData& Data = DataSys->GetData();
	for (int32 T = 0; T < 2; ++T)
	{
		const FCWTeamNetState& S = State.GetTeam(T);
		// 坚守旗帜
		if (HoldFlags[T])
		{
			const bool bShow = S.ChampionOrder == 1 && State.GetPhase() == ECWMatchPhase::InMatch;
			HoldFlags[T]->SetVisibility(bShow, true);
			if (bShow)
			{
				HoldFlags[T]->SetWorldLocation(FVector(S.ChampionHoldX, (T == 0 ? 1.f : -1.f) * RowSpacing * (LaneRows * 0.5f + 0.9f), 0.f));
			}
		}
		const ACWUnitVisual* Champion = S.ChampionId >= 0 ? FindUnit(S.ChampionId) : nullptr;
		const cw::ChampionDef* Def = S.ChampionDef >= 0 && S.ChampionDef < static_cast<int16>(Data.Champions.size()) ? &Data.Champions[S.ChampionDef] : nullptr;
		if (bChampionTrackerReady)
		{
			// 战吼：贴地扩散的金色冲击波 + 号角
			if (S.ChampionAbilitySeq != SeenAbilitySeq[T] && Champion && Def)
			{
				SpawnGroundPulse(Champion->GetActorLocation(), Def->AbilityRadius * 2.f, FLinearColor(1.f, 0.78f, 0.25f), 0.8f, 6.f);
				SpawnBurst(Champion->GetHitLocation(), 180.f, FLinearColor(1.f, 0.85f, 0.4f), 0.4f, 50000.f, 10.f);
				CWAudio::PlayAt(this, CWAudio::ESound::AgeUp, Champion->GetActorLocation(), 0.75f, 1.35f);
			}
			// 统帅出生/复活：光柱
			if (S.ChampionId >= 0 && S.ChampionId != SeenChampionId[T] && Champion)
			{
				SpawnBeam(Champion->GetActorLocation(), 1800.f, 120.f, CWVisual::TeamColor(T) * 0.6f + FLinearColor(0.4f, 0.4f, 0.4f, 0.f), 1.0f, 10.f);
				CWAudio::PlayAt(this, CWAudio::ESound::TurretBuild, Champion->GetActorLocation(), 0.7f, 0.8f);
			}
		}
		if (bChampionTrackerReady && S.bLastStandUsed && !SeenLastStand[T] && Bases[T])
		{
			// 背水一战：城门前三道光柱 + 扩散冲击波 + 低沉号角
			const FVector Gate = Bases[T]->GetGateLocation();
			for (int32 I = 0; I < 3; ++I)
			{
				const FVector At(Gate.X + (T == 0 ? 1.f : -1.f) * (60.f + I * 140.f), (I - 1) * 90.f, 0.f);
				SpawnBeam(At, 2200.f, 110.f, FLinearColor(1.f, 0.28f, 0.12f), 2.2f, 3.5f);
			}
			SpawnGroundPulse(FVector(Gate.X, 0.f, 0.f), 1600.f, FLinearColor(1.f, 0.4f, 0.15f), 1.2f, 1.5f);
			CWAudio::PlayAt(this, CWAudio::ESound::AgeUp, Gate, 1.f, 0.7f);
		}
		SeenLastStand[T] = S.bLastStandUsed;
		SeenAbilitySeq[T] = S.ChampionAbilitySeq;
		SeenChampionId[T] = S.ChampionId;
	}
	bChampionTrackerReady = true;
}

FString ACWBattleView::SkillVisualKey(int32 Skill) const
{
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!DataSys || !DataSys->IsLoaded() || Skill < 0 || Skill >= static_cast<int32>(DataSys->GetData().Skills.size()))
	{
		return FString();
	}
	return FString(UTF8_TO_TCHAR(DataSys->GetData().Skills[Skill].VisualKey.c_str()));
}

void ACWBattleView::SpawnDebris(const FVector& Location, int32 Count, const FLinearColor& Color, float Speed)
{
	for (int32 I = 0; I < Count; ++I)
	{
		FEffect E;
		E.Shape = CWVisual::EShape::Cube;
		E.Mesh = AcquireMesh(E.Shape, Color, 0.f, false);
		E.Mesh->SetWorldLocation(Location);
		E.Mesh->SetWorldRotation(FRotator(FMath::FRandRange(0.f, 90.f), FMath::FRandRange(0.f, 90.f), 0.f));
		const float Angle = FMath::FRandRange(0.f, 2.f * PI);
		E.Velocity = FVector(FMath::Cos(Angle) * Speed * 0.5f, FMath::Sin(Angle) * Speed * 0.3f, FMath::FRandRange(Speed * 0.5f, Speed));
		E.bGravity = true;
		E.StartSize = FMath::FRandRange(8.f, 18.f);
		E.EndSize = E.StartSize * 0.4f;
		E.Duration = FMath::FRandRange(0.6f, 1.0f);
		Effects.Add(E);
	}
}

void ACWBattleView::UpdateEffects(float Dt)
{
	for (int32 I = Effects.Num() - 1; I >= 0; --I)
	{
		FEffect& E = Effects[I];
		E.Age += Dt;
		const float T = FMath::Clamp(E.Age / E.Duration, 0.f, 1.f);
		if (E.bGravity)
		{
			E.Velocity.Z -= 980.f * Dt;
			FVector Loc = E.Mesh->GetComponentLocation() + E.Velocity * Dt;
			if (Loc.Z < 2.f)
			{
				Loc.Z = 2.f;
				E.Velocity *= 0.4f;
			}
			E.Mesh->SetWorldLocation(Loc);
		}
		// 爆炸先快速膨胀再收缩消失（基础材质不支持透明，用缩放表现消散）
		const float Size = E.bGravity ? FMath::Lerp(E.StartSize, E.EndSize, T)
		                              : (T < 0.35f ? FMath::Lerp(E.StartSize, E.EndSize, T / 0.35f) : FMath::Lerp(E.EndSize, 0.f, (T - 0.35f) / 0.65f));
		const float Scale = FMath::Max(Size, 0.1f) / 100.f;
		E.Mesh->SetWorldScale3D(E.FixedHeight > 0.f ? FVector(Scale, Scale, E.FixedHeight / 100.f) : FVector(Scale));
		if (E.Light)
		{
			E.Light->SetIntensity(E.LightIntensity * (1.f - T));
		}
		if (T >= 1.f)
		{
			ReleaseMesh(E.Mesh, E.Shape);
			if (E.Light)
			{
				E.Light->DestroyComponent();
			}
			Effects.RemoveAtSwap(I);
		}
	}
}
