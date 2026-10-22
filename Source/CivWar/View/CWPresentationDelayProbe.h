#pragma once

#include "CoreMinimal.h"
#include "Net/CWNetTypes.h"

namespace cw { struct GameData; }

class FCWPresentationDelayProbe
{
public:
	void Reset();
	const TArray<FCWUnitNetItem>& Resolve(const TArray<FCWUnitNetItem>& OriginalItems, const cw::GameData& Data, double LocalNow, float ServerNow, bool bStandalone);

private:
	struct FPendingSnapshot
	{
		FCWUnitNetItem Item;
		double ArrivedAt = 0.0;
		uint64 Serial = 0;
		bool bRemoval = false;
	};

	struct FUnitQueue
	{
		TArray<FPendingSnapshot> Pending;
		FCWUnitNetItem LastReceived;
		FCWUnitNetItem LastDelivered;
		bool bHasReceived = false;
		bool bHasDelivered = false;
		bool bAttackObserved = false;
		bool bRemovalQueued = false;
		bool bRemovalDelivered = false;
		bool bFailed = false;
	};

	void Configure(bool bStandalone);
	void Enqueue(FUnitQueue& Queue, const FCWUnitNetItem& Item, double LocalNow, float ServerNow, bool bRemoval);
	void Trace(const TCHAR* Event, const FPendingSnapshot& Snapshot, double LocalNow, float ServerNow, int32 PendingCount) const;
	static bool SameSnapshot(const FCWUnitNetItem& First, const FCWUnitNetItem& Second);

	static constexpr double DelaySeconds = 0.450;
	static constexpr int32 MaximumPending = 64;
	TMap<int32, FUnitQueue> Queues;
	TArray<FCWUnitNetItem> FrameItems;
	FString Run;
	uint64 NextSerial = 1;
	double LastLocalNow = -1.0;
	bool SelectedTeam[2] = { false, false };
	bool bConfigured = false;
	bool bEnabled = false;
};
