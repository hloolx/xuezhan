#include "View/CWMusicSubsystem.h"

#include "Components/AudioComponent.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/AssetManager.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/StreamableManager.h"
#include "Engine/World.h"
#include "Game/CWGameState.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/App.h"
#if WITH_EDITOR
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#endif
#include "Sound/SoundWave.h"
#include "View/CWAudio.h"

DEFINE_LOG_CATEGORY_STATIC(LogCWMusic, Log, All);

namespace
{
	constexpr float CrossfadeSeconds = 2.5f;
	void DestroyVoice(TObjectPtr<UAudioComponent>& Voice)
	{
		if (IsValid(Voice))
		{
			Voice->OnAudioPlaybackPercentNative.Clear();
			Voice->Stop();
			Voice->DestroyComponent();
		}
		Voice = nullptr;
	}
}

FSoftObjectPath CWMusic::AssetPath(ECue Cue)
{
	switch (Cue)
	{
	case ECue::Menu: return FSoftObjectPath(TEXT("/Game/Audio/Music/MUS_Titan.MUS_Titan"));
	case ECue::Battle: return FSoftObjectPath(TEXT("/Game/Audio/Music/MUS_Legionnaire.MUS_Legionnaire"));
	case ECue::Finale: return FSoftObjectPath(TEXT("/Game/Audio/Music/MUS_Juggernaut.MUS_Juggernaut"));
	default: return FSoftObjectPath();
	}
}

const TCHAR* CWMusic::CueName(ECue Cue)
{
	switch (Cue)
	{
	case ECue::Menu: return TEXT("Titan");
	case ECue::Battle: return TEXT("Legionnaire");
	case ECue::Finale: return TEXT("Juggernaut");
	default: return TEXT("Silent");
	}
}

CWMusic::ECue CWMusic::SelectCue(ECWMatchPhase Phase, float MatchTime, const cw::RulesDef& Rules,
	const FCWTeamNetState& Team0, const FCWTeamNetState& Team1, bool bFinaleLatched)
{
	if (Phase == ECWMatchPhase::PostMatch) return ECue::Silent; // Leave room for the victory/defeat sting.
	if (Phase != ECWMatchPhase::InMatch) return ECue::Menu;
	const auto IsFinalAssault = [&Rules](const FCWTeamNetState& Team)
	{
		return Team.bLastStandUsed || Team.TurretBoostTime > 0.f
			|| (Team.BaseMaxHp > 0.f && Team.BaseHp > 0.f
				&& Team.BaseHp <= Team.BaseMaxHp * Rules.LastStandBaseHpRatio);
	};
	return bFinaleLatched || MatchTime >= Rules.SuddenDeathTime || IsFinalAssault(Team0) || IsFinalAssault(Team1)
		? ECue::Finale : ECue::Battle;
}

float CWMusic::LoopCrossfadeSeconds(float Duration)
{
	return FMath::IsFinite(Duration) && Duration >= 12.f ? FMath::Min(6.f, Duration * .1f) : 0.f;
}

bool CWMusic::IsInLoopCrossfade(float PlaybackSeconds, float Duration)
{
	const float Overlap = LoopCrossfadeSeconds(Duration);
	return Overlap > 0.f && FMath::IsFinite(PlaybackSeconds)
		&& PlaybackSeconds >= Duration - Overlap && PlaybackSeconds < Duration;
}

void CWMusic::FGainEnvelope::To(float Value, float Seconds)
{
	Start = Gain;
	Target = FMath::Clamp(Value, 0.f, 1.f);
	Elapsed = 0.f;
	Duration = FMath::Max(0.f, Seconds);
	if (Duration <= 0.f) Gain = Target;
}

void CWMusic::FGainEnvelope::Tick(float DeltaTime)
{
	Elapsed = FMath::Min(Duration, Elapsed + FMath::Max(0.f, DeltaTime));
	const float Alpha = Duration > 0.f ? Elapsed / Duration : 1.f;
	Gain = FMath::Lerp(Start, Target, Alpha * Alpha * (3.f - 2.f * Alpha));
}

void CWMusic::FFocusEnvelope::Trigger(CWAudio::ESound Sound)
{
	float Gain = 1.f;
	float Hold = 0.f;
	switch (Sound)
	{
	case CWAudio::ESound::AgeUp: Gain = .68f; Hold = 1.9f; break;
	case CWAudio::ESound::Victory:
	case CWAudio::ESound::Defeat: Gain = .38f; Hold = 2.5f; break;
	case CWAudio::ESound::SkillWarning: Gain = .78f; Hold = .8f; break;
	default: return;
	}
	// Repeated cues extend the hold rather than multiply the attenuation. A weaker
	// cue cannot undo a stronger outcome sting that is already in progress.
	if (HoldRemaining <= 0.f || Gain < Envelope.Target) Envelope.To(Gain, .14f);
	HoldRemaining = FMath::Max(HoldRemaining, Hold);
}

void CWMusic::FFocusEnvelope::Tick(float DeltaTime)
{
	if (HoldRemaining > 0.f)
	{
		HoldRemaining = FMath::Max(0.f, HoldRemaining - FMath::Max(0.f, DeltaTime));
		if (HoldRemaining <= 0.f) Envelope.To(1.f, 1.2f);
	}
	Envelope.Tick(DeltaTime);
}

void CWMusic::FFocusEnvelope::Reset()
{
	*this = FFocusEnvelope();
}

UCWMusicSubsystem::UCWMusicSubsystem() : FTickableGameObject(ETickableTickType::Never) {}

bool UCWMusicSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	return !IsRunningDedicatedServer() && Cast<UGameInstance>(Outer) && Super::ShouldCreateSubsystem(Outer);
}

void UCWMusicSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	LoadedTracks.SetNum(4);
	SetTickableTickType(ETickableTickType::Conditional);
}

bool UCWMusicSubsystem::IsTickable() const
{
	const UWorld* World = GetTickableGameObjectWorld();
	return !bEnding && !IsTemplate() && World && !World->IsNetMode(NM_DedicatedServer)
		&& (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE);
}

UWorld* UCWMusicSubsystem::GetTickableGameObjectWorld() const
{
	return GetGameInstance() ? GetGameInstance()->GetWorld() : nullptr;
}

TStatId UCWMusicSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UCWMusicSubsystem, STATGROUP_Tickables);
}

void UCWMusicSubsystem::Tick(float DeltaTime)
{
	if (bEnding) return;
	UWorld* World = GetTickableGameObjectWorld();
	if (!World || World->GetNetMode() == NM_DedicatedServer) return;
	// UI music keeps time when gameplay pauses or changes speed. Mixer callbacks
	// provide the exact track position; this clock drives only gain envelopes.
	const float AudioDelta = FMath::Max(0.f, static_cast<float>(FApp::GetDeltaTime()));
	TickVoices(AudioDelta);
	RetryTimeLeft = FMath::Max(0.f, RetryTimeLeft - AudioDelta);
	if (LastWorld.Get() != World)
	{
		if (LastWorld.IsValid() || Active)
			UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_TRAVEL retained=%d cue=%s position=%.1f"),
				IsValid(Active) && Active->IsPlaying() ? 1 : 0, CWMusic::CueName(ActiveState.Cue), ActiveState.PlaybackSeconds);
		LastWorld = World;
		LastMatchTime = -1.f;
		bFinaleLatched = false;
		Focus.Reset();
	}
	const ACWGameState* State = World->GetGameState<ACWGameState>();
	const UCWGameDataSubsystem* Data = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	if (!State || !Data || !Data->IsLoaded()) return;

	if (State->GetPhase() != ECWMatchPhase::InMatch || State->GetMatchTime() + .1f < LastMatchTime)
		bFinaleLatched = false;
	LastMatchTime = State->GetMatchTime();
	const CWMusic::ECue Cue = CWMusic::SelectCue(State->GetPhase(), LastMatchTime, Data->GetData().Rules,
		State->GetTeam(0), State->GetTeam(1), bFinaleLatched);
	if (Cue == CWMusic::ECue::Finale) bFinaleLatched = true;
	if (Cue != DesiredCue)
	{
		UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_SELECT cue=%s phase=%d match_time=%.1f world=%s"),
			CWMusic::CueName(Cue), static_cast<int32>(State->GetPhase()), LastMatchTime, *World->GetName());
		RequestCue(Cue);
	}

	if (DesiredCue != CWMusic::ECue::Silent && !LoadHandle.IsValid())
	{
		if (bPendingStart && !Retiring) StartLoadedCue(DesiredCue);
		if (!Retiring && IsValid(Active) && Active->IsPlaying())
		{
			if (ActiveState.Cue != DesiredCue && LoadedTracks[static_cast<int32>(DesiredCue)])
				StartLoadedCue(DesiredCue);
			else if (ActiveState.Cue == DesiredCue && CWMusic::IsInLoopCrossfade(ActiveState.PlaybackSeconds, ActiveState.Duration))
				StartLoadedCue(DesiredCue, true);
		}
		// Recover a lost voice after a device reset. The five-second throttle also
		// prevents a disabled audio device from allocating components every frame.
		if (RetryTimeLeft <= 0.f && (!IsValid(Active) || !Active->IsPlaying())
			&& GEngine && GEngine->UseSound() && World->bAllowAudioPlayback)
			RequestCue(DesiredCue);
	}
}

void UCWMusicSubsystem::TickVoices(float DeltaTime)
{
	Focus.Tick(DeltaTime);
	const auto UpdateVoice = [this, DeltaTime](TObjectPtr<UAudioComponent>& Voice, CWMusic::FVoiceState& State)
	{
		if (!IsValid(Voice)) { Voice = nullptr; return; }
		State.Envelope.Tick(DeltaTime);
		if (!State.bHasPlaybackCallback && Voice->IsPlaying() && State.Duration > 0.f)
			State.PlaybackSeconds = FMath::Fmod(State.PlaybackSeconds + DeltaTime, State.Duration);
		Voice->SetVolumeMultiplier(State.Envelope.Gain * Focus.Envelope.Gain);
		if (State.Envelope.Target == 0.f && State.Envelope.Gain <= 0.f) DestroyVoice(Voice);
	};
	UpdateVoice(Active, ActiveState);
	UpdateVoice(Retiring, RetiringState);
}

void UCWMusicSubsystem::OnPlaybackPercent(const UAudioComponent* Voice, const USoundWave* Wave, float Percent)
{
	if (!Wave || !FMath::IsFinite(Percent) || Percent < 0.f) return;
	CWMusic::FVoiceState* State = Voice == Active ? &ActiveState : (Voice == Retiring ? &RetiringState : nullptr);
	if (!State || State->Duration <= 0.f) return;
	State->PlaybackSeconds = FMath::Fmod(Percent * State->Duration, State->Duration);
	State->bHasPlaybackCallback = true;
}

void UCWMusicSubsystem::NotifyMusicEvent(CWAudio::ESound Sound)
{
	if (bEnding) return;
	Focus.Trigger(Sound);
	UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_FOCUS event=%d gain=%.2f hold=%.1f"),
		static_cast<int32>(Sound), Focus.Envelope.Target, Focus.HoldRemaining);
}

void UCWMusicSubsystem::RequestCue(CWMusic::ECue Cue)
{
	DesiredCue = Cue;
	bPendingStart = false;
	RetryTimeLeft = 5.f;
	const uint32 Generation = ++LoadGeneration;
	if (LoadHandle.IsValid())
	{
		LoadHandle->CancelHandle();
		LoadHandle.Reset();
	}
	if (Cue == CWMusic::ECue::Silent)
	{
		// Both voices may still be audible during a crossfade. Fade both without
		// abruptly discarding one or restarting an already-requested fade.
		if (Active) ActiveState.Envelope.To(0.f, CrossfadeSeconds);
		if (Retiring) RetiringState.Envelope.To(0.f, CrossfadeSeconds);
		return;
	}
	UWorld* World = GetTickableGameObjectWorld();
	if (!GEngine || !GEngine->UseSound() || !World || !World->bAllowAudioPlayback) return;
	if (LoadedTracks[static_cast<int32>(Cue)])
	{
		StartLoadedCue(Cue);
		return;
	}
	LoadHandle = UAssetManager::GetStreamableManager().RequestAsyncLoad(CWMusic::AssetPath(Cue),
		FStreamableDelegate::CreateWeakLambda(this, [this, Cue, Generation]()
		{
			// A superseded async callback must not clear the newer request's handle,
			// including A -> B -> A transitions that share the same cue value.
			if (bEnding || DesiredCue != Cue || LoadGeneration != Generation) return;
			LoadedTracks[static_cast<int32>(Cue)] = Cast<USoundWave>(CWMusic::AssetPath(Cue).ResolveObject());
			LoadHandle.Reset();
			StartLoadedCue(Cue);
		}));
}

void UCWMusicSubsystem::StartLoadedCue(CWMusic::ECue Cue, bool bLoopRestart)
{
	bPendingStart = false;
	USoundWave* Wave = LoadedTracks[static_cast<int32>(Cue)];
	if (!Wave)
	{
		RetryTimeLeft = TNumericLimits<float>::Max();
		UE_LOG(LogCWMusic, Warning, TEXT("CW_MUSIC_MISSING asset=%s"), *CWMusic::AssetPath(Cue).ToString());
		return;
	}
	if (!bLoopRestart)
	{
		if (IsValid(Active) && Active->IsPlaying() && ActiveState.Cue == Cue)
		{
			ActiveState.Envelope.To(1.f, CrossfadeSeconds);
			if (Retiring) RetiringState.Envelope.To(0.f, CrossfadeSeconds);
			return;
		}
		if (IsValid(Retiring) && Retiring->IsPlaying() && RetiringState.Cue == Cue)
		{
			Swap(Active, Retiring);
			Swap(ActiveState, RetiringState);
			ActiveState.Envelope.To(1.f, CrossfadeSeconds);
			if (Retiring) RetiringState.Envelope.To(0.f, CrossfadeSeconds);
			UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_RESUME cue=%s position=%.1f"), CWMusic::CueName(Cue), ActiveState.PlaybackSeconds);
			return;
		}
	}
	// Three rapid scene changes cannot produce three voices or cut an audible
	// tail. The newest loaded request starts as soon as the retiring slot is free.
	if (Retiring) { bPendingStart = true; return; }
	CWAudio::ConfigureMusic(Wave);
	const float FadeSeconds = bLoopRestart ? CWMusic::LoopCrossfadeSeconds(Wave->Duration) : CrossfadeSeconds;
	RetireActive(FadeSeconds);
	Active = UGameplayStatics::CreateSound2D(GetGameInstance(), Wave, 0.f, 1.f, 0.f, nullptr, true, false);
	if (Active)
	{
		ActiveState = CWMusic::FVoiceState();
		ActiveState.Cue = Cue;
		ActiveState.Duration = Wave->Duration;
		ActiveState.Envelope.Gain = 0.f;
		ActiveState.Envelope.To(1.f, FadeSeconds);
		Active->OnAudioPlaybackPercentNative.AddUObject(this, &UCWMusicSubsystem::OnPlaybackPercent);
		float StartSeconds = 0.f;
#if WITH_EDITOR
		// Offscreen validation can exercise the real streamed track boundary in a
		// short run. Shipping builds always start every new cue at its beginning.
		if (!bReviewSeekUsed && !bLoopRestart && FParse::Param(FCommandLine::Get(), TEXT("cwmusicseekend")))
		{
			bReviewSeekUsed = true;
			StartSeconds = FMath::Max(0.f, Wave->Duration - 10.f);
			UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_REVIEW_SEEK cue=%s position=%.1f"), CWMusic::CueName(Cue), StartSeconds);
		}
#endif
		ActiveState.PlaybackSeconds = StartSeconds;
		Active->Play(StartSeconds);
		UE_LOG(LogCWMusic, Display, TEXT("CW_MUSIC_%s cue=%s looping=1 voices=%d crossfade=%.1f persistent=1"),
			bLoopRestart ? TEXT("LOOP") : TEXT("PLAY"), CWMusic::CueName(Cue), Retiring ? 2 : 1, FadeSeconds);
	}
}

void UCWMusicSubsystem::RetireActive(float FadeSeconds)
{
	check(!Retiring);
	if (IsValid(Active))
	{
		Retiring = Active;
		RetiringState = ActiveState;
		RetiringState.Envelope.To(0.f, FadeSeconds);
	}
	Active = nullptr;
}

void UCWMusicSubsystem::StopAll()
{
	bEnding = true;
	if (LoadHandle.IsValid())
	{
		LoadHandle->CancelHandle();
		LoadHandle.Reset();
	}
	DestroyVoice(Active);
	DestroyVoice(Retiring);
	LoadedTracks.Reset();
	Focus.Reset();
}

void UCWMusicSubsystem::BeginDestroy()
{
	SetTickableTickType(ETickableTickType::Never);
	Super::BeginDestroy();
}

void UCWMusicSubsystem::Deinitialize()
{
	SetTickableTickType(ETickableTickType::Never);
	StopAll();
	Super::Deinitialize();
}
