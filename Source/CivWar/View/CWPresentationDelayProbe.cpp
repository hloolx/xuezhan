#include "View/CWPresentationDelayProbe.h"

#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Sim/SimTypes.h"

void FCWPresentationDelayProbe::Configure(bool bStandalone)
{
	if (bConfigured) return;
	bConfigured = true;
	FString RequestedDelay;
	if (!FParse::Value(FCommandLine::Get(), TEXT("cwartpresentationdelay="), RequestedDelay)) return;
	Run = TEXT("unspecified");
	FParse::Value(FCommandLine::Get(), TEXT("cwarttimingrun="), Run);
	bEnabled = RequestedDelay == TEXT("450") && bStandalone && Run != TEXT("unspecified") && !Run.IsEmpty() &&
		FParse::Param(FCommandLine::Get(), TEXT("cwstoneaxepilot")) && FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"));
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only status=%s pid=%u delay_ms=450 network_transport=false"),
		*Run, bEnabled ? TEXT("enabled") : TEXT("rejected"), FPlatformProcess::GetCurrentProcessId());
}

void FCWPresentationDelayProbe::Reset()
{
	if (bEnabled)
	{
		int32 PendingCount = 0;
		for (const TPair<int32, FUnitQueue>& Entry : Queues) PendingCount += Entry.Value.Pending.Num();
		UE_LOG(LogTemp, Display, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only event=reset pid=%u units=%d pending=%d"),
			*Run, FPlatformProcess::GetCurrentProcessId(), Queues.Num(), PendingCount);
	}
	Queues.Reset();
	FrameItems.Reset();
	SelectedTeam[0] = false;
	SelectedTeam[1] = false;
	LastLocalNow = -1.0;
}

bool FCWPresentationDelayProbe::SameSnapshot(const FCWUnitNetItem& First, const FCWUnitNetItem& Second)
{
	return First.Id == Second.Id && First.Team == Second.Team && First.Row == Second.Row && First.Def == Second.Def &&
		First.X == Second.X && First.Hp == Second.Hp && First.State == Second.State && First.AttackSeq == Second.AttackSeq &&
		First.AttackStartServerTime == Second.AttackStartServerTime && First.AttackOutcome == Second.AttackOutcome &&
		First.AttackEndServerTime == Second.AttackEndServerTime && First.HitSeq == Second.HitSeq && First.TargetId == Second.TargetId &&
		First.MaxHp == Second.MaxHp && First.Rank == Second.Rank && First.Flags == Second.Flags;
}

void FCWPresentationDelayProbe::Trace(const TCHAR* Event, const FPendingSnapshot& Snapshot, double LocalNow, float ServerNow, int32 PendingCount) const
{
	const FCWUnitNetItem& Item = Snapshot.Item;
	UE_LOG(LogTemp, Display, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only event=%s pid=%u serial=%llu id=%d team=%u def=%u row=%u seq=%u start_server=%.9g outcome=%u end_server=%.9g x=%.9g hp=%u state=%u hit_seq=%u target=%d max_hp=%u rank=%u flags=%u arrived=%.6f now=%.6f held_ms=%.3f server_now=%.6f pending=%d removal=%d"),
		*Run, Event, FPlatformProcess::GetCurrentProcessId(), static_cast<unsigned long long>(Snapshot.Serial), Item.Id, static_cast<uint32>(Item.Team), static_cast<uint32>(Item.Def), static_cast<uint32>(Item.Row), static_cast<uint32>(Item.AttackSeq),
		Item.AttackStartServerTime, static_cast<uint32>(Item.AttackOutcome), Item.AttackEndServerTime, Item.X, static_cast<uint32>(Item.Hp), static_cast<uint32>(Item.State), static_cast<uint32>(Item.HitSeq), Item.TargetId,
		static_cast<uint32>(Item.MaxHp), static_cast<uint32>(Item.Rank), static_cast<uint32>(Item.Flags), Snapshot.ArrivedAt, LocalNow, (LocalNow - Snapshot.ArrivedAt) * 1000.0, ServerNow, PendingCount, Snapshot.bRemoval ? 1 : 0);
}

void FCWPresentationDelayProbe::Enqueue(FUnitQueue& Queue, const FCWUnitNetItem& Item, double LocalNow, float ServerNow, bool bRemoval)
{
	if (Queue.bFailed) return;
	if (Queue.Pending.Num() >= MaximumPending)
	{
		Queue.bFailed = true;
		UE_LOG(LogTemp, Error, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only status=failed reason=queue_overflow pid=%u id=%d pending=%d"),
			*Run, FPlatformProcess::GetCurrentProcessId(), Item.Id, Queue.Pending.Num());
		return;
	}
	FPendingSnapshot& Snapshot = Queue.Pending.AddDefaulted_GetRef();
	Snapshot.Item = Item;
	Snapshot.ArrivedAt = LocalNow;
	Snapshot.Serial = NextSerial++;
	Snapshot.bRemoval = bRemoval;
	Trace(bRemoval ? TEXT("enqueue_remove") : TEXT("enqueue"), Snapshot, LocalNow, ServerNow, Queue.Pending.Num());
}

const TArray<FCWUnitNetItem>& FCWPresentationDelayProbe::Resolve(const TArray<FCWUnitNetItem>& OriginalItems, const cw::GameData& Data, double LocalNow, float ServerNow, bool bStandalone)
{
	Configure(bStandalone);
	if (!bEnabled) return OriginalItems;
	if (!bStandalone || !FMath::IsFinite(LocalNow) || !FMath::IsFinite(ServerNow) || LocalNow < LastLocalNow)
	{
		UE_LOG(LogTemp, Error, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only status=failed reason=invalid_context_or_clock pid=%u"), *Run, FPlatformProcess::GetCurrentProcessId());
		bEnabled = false;
		return OriginalItems;
	}
	LastLocalNow = LocalNow;
	FrameItems.Reset(OriginalItems.Num() + 2);
	TSet<int32> Live;
	for (const FCWUnitNetItem& Item : OriginalItems)
	{
		Live.Add(Item.Id);
		if (!Queues.Contains(Item.Id) && Item.Team < 2 && !SelectedTeam[Item.Team] && Item.Def < Data.Units.size() &&
			(Item.Flags & CWUnitFlags::Champion) == 0 && Data.Units[Item.Def].VisualKey == "Unit_StoneAxe")
		{
			SelectedTeam[Item.Team] = true;
			Queues.Add(Item.Id);
			UE_LOG(LogTemp, Display, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only event=select pid=%u id=%d team=%u cohort=first_ordinary_stoneaxe"),
				*Run, FPlatformProcess::GetCurrentProcessId(), Item.Id, static_cast<uint32>(Item.Team));
		}
		FUnitQueue* Queue = Queues.Find(Item.Id);
		if (!Queue)
		{
			FrameItems.Add(Item);
			continue;
		}
		if (Queue->bFailed) continue;
		if (Queue->bRemovalQueued)
		{
			Queue->bFailed = true;
			UE_LOG(LogTemp, Error, TEXT("CIVWAR_PRESENTATION_DELAY run=%s mode=local_presentation_only status=failed reason=unit_reappeared_without_reset pid=%u id=%d"), *Run, FPlatformProcess::GetCurrentProcessId(), Item.Id);
			continue;
		}
		const bool bChanged = !Queue->bHasReceived || !SameSnapshot(Queue->LastReceived, Item);
		Queue->LastReceived = Item;
		Queue->bHasReceived = true;
		if (Item.AttackStartServerTime >= 0.f) Queue->bAttackObserved = true;
		if (Queue->bAttackObserved && bChanged) Enqueue(*Queue, Item, LocalNow, ServerNow, false);
	}
	for (TPair<int32, FUnitQueue>& Entry : Queues)
	{
		FUnitQueue& Queue = Entry.Value;
		if (!Live.Contains(Entry.Key) && !Queue.bRemovalQueued)
		{
			Queue.bRemovalQueued = true;
			Enqueue(Queue, Queue.LastReceived, LocalNow, ServerNow, true);
		}
		if (!Queue.bFailed && !Queue.Pending.IsEmpty() && LocalNow >= Queue.Pending[0].ArrivedAt + DelaySeconds)
		{
			const FPendingSnapshot Snapshot = Queue.Pending[0];
			Queue.Pending.RemoveAt(0, 1, EAllowShrinking::No);
			if (Snapshot.bRemoval)
			{
				Queue.bRemovalDelivered = true;
				Queue.bHasDelivered = false;
			}
			else
			{
				Queue.LastDelivered = Snapshot.Item;
				Queue.bHasDelivered = true;
			}
			Trace(Snapshot.bRemoval ? TEXT("deliver_remove") : TEXT("deliver"), Snapshot, LocalNow, ServerNow, Queue.Pending.Num());
		}
		if (Queue.bHasDelivered && !Queue.bRemovalDelivered) FrameItems.Add(Queue.LastDelivered);
	}
	return FrameItems;
}
