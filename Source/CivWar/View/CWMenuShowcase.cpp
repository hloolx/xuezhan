#include "View/CWMenuShowcase.h"

#include "Data/CWGameDataSubsystem.h"
#include "Components/SceneComponent.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Game/CWGameState.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWNetTypes.h"
#include "Sim/SimState.h"
#include "View/CWBaseVisual.h"
#include "View/CWUnitVisual.h"

ACWMenuShowcase::ACWMenuShowcase()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PrePhysics;
	SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("Root")));
	SetReplicates(false);
	SetActorEnableCollision(false);
#if WITH_EDITOR
	int32 ReviewAge = 0;
	if (FParse::Value(FCommandLine::Get(), TEXT("cwpreviewage="), ReviewAge))
		PreviewAge = FMath::Clamp(ReviewAge, 0, 4);
#endif
}

ACWMenuShowcase* ACWMenuShowcase::Get(UWorld* World)
{
	if (World)
		for (TActorIterator<ACWMenuShowcase> It(World); It; ++It)
			if (IsValid(*It)) return *It;
	return nullptr;
}

void ACWMenuShowcase::SetPreviewAge(int32 Age)
{
	const UCWGameDataSubsystem* Data = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (Data && Data->IsLoaded() && Age >= 0 && Age < static_cast<int32>(Data->GetData().Ages.size())
		&& Data->GetData().Ages[Age].Implemented)
		PreviewAge = Age;
}

FVector ACWMenuShowcase::GetCameraFocus() const
{
	// Leave the left third for navigation; the army occupies the open right side.
	return FVector(LaneCenter, 40.f, 120.f);
}

void ACWMenuShowcase::ClearPreview()
{
	for (ACWUnitVisual* Unit : PreviewUnits)
		if (IsValid(Unit)) Unit->Destroy();
	PreviewUnits.Reset();
	if (IsValid(PreviewBase)) PreviewBase->Destroy();
	PreviewBase = nullptr;
}

void ACWMenuShowcase::RebuildPreview()
{
	const UCWGameDataSubsystem* DataSys = GetGameInstance() ? GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!DataSys || !DataSys->IsLoaded()) return;
	const cw::GameData& Data = DataSys->GetData();
	if (PreviewAge < 0 || PreviewAge >= static_cast<int32>(Data.Ages.size())) return;
	ClearPreview();
	LaneCenter = Data.Rules.LaneLength * 0.5f;
	FActorSpawnParameters Params;
	Params.Owner = this;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	PreviewBase = GetWorld()->SpawnActor<ACWBaseVisual>(Params);
	if (PreviewBase)
	{
		PreviewBase->Init(0, LaneCenter + 500.f, Data.Rules.BaseHalfWidth);
		FCWTeamNetState PreviewState;
		PreviewState.Age = static_cast<uint8>(PreviewAge);
		PreviewState.BaseHp = PreviewState.BaseMaxHp = Data.Ages[PreviewAge].BaseMaxHp;
		PreviewBase->SyncState(PreviewState, DataSys);
		// A preview change is not an in-game age-up; settle its one-shot animation.
		PreviewBase->UpdateVisual(1.5f);
		PreviewBase->ConsumeAgeUpEvent();
		PreviewBase->SetActorLocation(FVector(LaneCenter + 500.f, -220.f, 0.f));
		PreviewBase->SetActorRotation(FRotator(0.f, 55.f, 0.f));
		PreviewBase->SetActorEnableCollision(false);
	}
	const auto Army = Data.UnitsForAge(PreviewAge);
	TArray<int32> Defs;
	if (!Army.empty()) Defs.Add(Army[0]);
	const int32 Champion = Data.ChampionForAge(PreviewAge);
	if (Champion >= 0) Defs.Add(Data.Champions[Champion].UnitDefIndex);
	if (Army.size() > 1) Defs.Add(Army[1]);
	for (int32 Index = 0; Index < Defs.Num(); ++Index)
	{
		const int32 DefIndex = Defs[Index];
		if (DefIndex < 0 || DefIndex >= static_cast<int32>(Data.Units.size())) continue;
		const cw::UnitDef& Def = Data.Units[DefIndex];
		ACWUnitVisual* Unit = GetWorld()->SpawnActor<ACWUnitVisual>(Params);
		if (!Unit) continue;
		const float X = LaneCenter + 130.f + Index * 285.f;
		const float Y = Index == 1 ? 410.f : 290.f;
		Unit->Init(-100 - Index, 0, DefIndex, FName(UTF8_TO_TCHAR(Def.VisualKey.c_str())),
			Def.MaxHp, Def.MoveSpeed, Def.AttackWindup, X, Y);
		FCWUnitNetItem Idle;
		Idle.Id = -100 - Index;
		Idle.Def = static_cast<uint16>(DefIndex);
		Idle.X = X;
		Idle.Hp = Idle.MaxHp = static_cast<uint16>(FMath::Clamp(Def.MaxHp, 1.f, 65535.f));
		Idle.State = static_cast<uint8>(cw::UnitState::Blocked);
		Unit->ApplyNetState(Idle);
		Unit->SetActorScale3D(FVector(1.18f));
		Unit->SetActorEnableCollision(false);
		PreviewUnits.Add(Unit);
	}
	BuiltAge = PreviewAge;
	UE_LOG(LogTemp, Display, TEXT("CW_MENU_PREVIEW age=%d units=%d base=%d cosmetic=1"), BuiltAge, PreviewUnits.Num(), PreviewBase ? 1 : 0);
}

void ACWMenuShowcase::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	if (!State || State->GetPhase() != ECWMatchPhase::Menu)
	{
		Destroy();
		return;
	}
	if (BuiltAge != PreviewAge) RebuildPreview();
	if (PreviewBase) PreviewBase->UpdateVisual(DeltaSeconds);
	for (ACWUnitVisual* Unit : PreviewUnits)
	{
		if (!IsValid(Unit)) continue;
		Unit->UpdateVisual(DeltaSeconds);
		Unit->SetActorRotation(FRotator(0.f, 65.f, 0.f));
	}
}

void ACWMenuShowcase::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	ClearPreview();
	Super::EndPlay(EndPlayReason);
}
