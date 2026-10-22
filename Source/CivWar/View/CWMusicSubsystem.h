// Adaptive music is presentation only. The player survives map travel.
#pragma once

#include "CoreMinimal.h"
#include "Net/CWNetTypes.h"
#include "Sim/SimTypes.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "Tickable.h"
#include "CWMusicSubsystem.generated.h"

class UAudioComponent;
class USoundWave;
struct FStreamableHandle;
namespace CWAudio { enum class ESound : uint8; }

namespace CWMusic
{
	enum class ECue : uint8 { Silent, Menu, Battle, Finale };
	FSoftObjectPath AssetPath(ECue Cue);
	const TCHAR* CueName(ECue Cue);
	// Uses replicated match facts and the actual rules table. Finale latches until
	// the match ends, so repairing a base cannot alternate tracks at the threshold.
	ECue SelectCue(ECWMatchPhase Phase, float MatchTime, const cw::RulesDef& Rules,
		const FCWTeamNetState& Team0, const FCWTeamNetState& Team1, bool bFinaleLatched);
	float LoopCrossfadeSeconds(float Duration);
	bool IsInLoopCrossfade(float PlaybackSeconds, float Duration);

	struct FGainEnvelope
	{
		float Gain = 1.f;
		float Target = 1.f;
		float Start = 1.f;
		float Elapsed = 0.f;
		float Duration = 0.f;
		void To(float Value, float Seconds);
		void Tick(float DeltaTime);
	};
	// A transient mix gain; never changes a saved user volume or a shared sound class.
	struct FFocusEnvelope
	{
		FGainEnvelope Envelope;
		float HoldRemaining = 0.f;
		void Trigger(CWAudio::ESound Sound);
		void Tick(float DeltaTime);
		void Reset();
	};
	struct FVoiceState
	{
		ECue Cue = ECue::Silent;
		FGainEnvelope Envelope;
		float Duration = 0.f;
		float PlaybackSeconds = 0.f;
		bool bHasPlaybackCallback = false;
	};
}

UCLASS()
class CIVWAR_API UCWMusicSubsystem : public UGameInstanceSubsystem, public FTickableGameObject
{
	GENERATED_BODY()

public:
	UCWMusicSubsystem();
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override;
	virtual bool IsTickableWhenPaused() const override { return true; }
	virtual UWorld* GetTickableGameObjectWorld() const override;
	virtual void BeginDestroy() override;
	virtual void Deinitialize() override;
	CWMusic::ECue GetDesiredCue() const { return DesiredCue; }
	void NotifyMusicEvent(CWAudio::ESound Sound);

private:
	void RequestCue(CWMusic::ECue Cue);
	void StartLoadedCue(CWMusic::ECue Cue, bool bLoopRestart = false);
	void RetireActive(float FadeSeconds);
	void TickVoices(float DeltaTime);
	void OnPlaybackPercent(const UAudioComponent* Voice, const USoundWave* Wave, float Percent);
	void StopAll();

	UPROPERTY(Transient) TObjectPtr<UAudioComponent> Active;
	UPROPERTY(Transient) TObjectPtr<UAudioComponent> Retiring;
	UPROPERTY(Transient) TArray<TObjectPtr<USoundWave>> LoadedTracks;
	TSharedPtr<FStreamableHandle> LoadHandle;
	CWMusic::ECue DesiredCue = CWMusic::ECue::Silent;
	CWMusic::FVoiceState ActiveState;
	CWMusic::FVoiceState RetiringState;
	CWMusic::FFocusEnvelope Focus;
	TWeakObjectPtr<UWorld> LastWorld;
	uint32 LoadGeneration = 0;
	float RetryTimeLeft = 0.f;
	float LastMatchTime = -1.f;
	bool bFinaleLatched = false;
	bool bPendingStart = false;
	bool bReviewSeekUsed = false;
	bool bEnding = false;
};
