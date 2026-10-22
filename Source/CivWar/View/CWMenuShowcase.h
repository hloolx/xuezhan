// Local, cosmetic front-end preview. Never contributes actors to the simulation.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "CWMenuShowcase.generated.h"

class ACWBaseVisual;
class ACWUnitVisual;

UCLASS(NotPlaceable)
class CIVWAR_API ACWMenuShowcase : public AActor
{
	GENERATED_BODY()
public:
	ACWMenuShowcase();
	static ACWMenuShowcase* Get(UWorld* World);
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;
	void SetPreviewAge(int32 Age);
	int32 GetPreviewAge() const { return PreviewAge; }
	FVector GetCameraFocus() const;
	int32 GetPreviewUnitCount() const { return PreviewUnits.Num(); }

private:
	void RebuildPreview();
	void ClearPreview();
	UPROPERTY(Transient) TObjectPtr<ACWBaseVisual> PreviewBase;
	UPROPERTY(Transient) TArray<TObjectPtr<ACWUnitVisual>> PreviewUnits;
	int32 PreviewAge = 0;
	int32 BuiltAge = -1;
	float LaneCenter = 3000.f;
};
