#include "View/CWAudio.h"

#include "AudioDeviceManager.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/ConfigCacheIni.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundClass.h"
#include "Sound/SoundConcurrency.h"
#include "Sound/SoundWave.h"
#include "UObject/Package.h"
#include "View/CWMusicSubsystem.h"

namespace CWAudio
{
	namespace
	{
		constexpr int32 SoundCount = static_cast<int32>(ESound::Count);
		constexpr int32 ChannelCount = static_cast<int32>(EChannel::Count);
		struct FSoundProfile
		{
			const TCHAR* Name;
			EChannel Channel;
			float Retrigger;
			int32 Voices;
			int32 Variants;
			float Priority;
		};
		// Short, restrained interface cues; denser battles cannot consume announcement voices.
		const FSoundProfile Profiles[] = {
			{TEXT("Swing"), EChannel::Battle, .080f, 3, 3, .7f},
			{TEXT("HitFlesh"), EChannel::Battle, .075f, 3, 3, .9f},
			{TEXT("HitMetal"), EChannel::Battle, .090f, 3, 3, .9f},
			{TEXT("Sling"), EChannel::Battle, .085f, 3, 3, .8f},
			{TEXT("Bow"), EChannel::Battle, .085f, 3, 3, .8f},
			{TEXT("Gun"), EChannel::Battle, .080f, 3, 3, 1.f},
			{TEXT("MachineGun"), EChannel::Battle, .065f, 3, 3, .8f},
			{TEXT("Cannon"), EChannel::Battle, .220f, 2, 3, 1.5f},
			{TEXT("Explosion"), EChannel::Battle, .180f, 3, 3, 1.6f},
			{TEXT("Death"), EChannel::Battle, .180f, 2, 3, .7f},
			{TEXT("BaseHit"), EChannel::Battle, .320f, 2, 3, 1.8f},
			{TEXT("AgeUp"), EChannel::Announcements, 1.0f, 1, 1, 2.f},
			{TEXT("UIClick"), EChannel::Interface, .045f, 2, 1, 2.f},
			{TEXT("UIError"), EChannel::Interface, .250f, 1, 1, 2.5f},
			{TEXT("Train"), EChannel::Battle, .300f, 2, 1, .7f},
			{TEXT("Victory"), EChannel::Announcements, 2.f, 1, 1, 4.f},
			{TEXT("Defeat"), EChannel::Announcements, 2.f, 1, 1, 4.f},
			{TEXT("SkillWarning"), EChannel::Battle, .500f, 1, 1, 3.f},
			{TEXT("TurretBuild"), EChannel::Battle, .300f, 2, 3, 1.5f},
			{TEXT("MeteorFall"), EChannel::Battle, .180f, 2, 3, 1.5f},
			{TEXT("Laser"), EChannel::Battle, .080f, 3, 3, 1.f},
			{TEXT("Rocket"), EChannel::Battle, .180f, 2, 3, 1.5f},
		};
		static_assert(UE_ARRAY_COUNT(Profiles) == SoundCount, "Every audio event needs a mix profile");
		const TCHAR* ChannelNames[] = {TEXT("Master"), TEXT("Battle"), TEXT("Interface"), TEXT("Announcements"), TEXT("Music")};
		float Volumes[] = {.85f, .8f, .75f, .9f, .55f};
		static_assert(UE_ARRAY_COUNT(ChannelNames) == ChannelCount && UE_ARRAY_COUNT(Volumes) == ChannelCount);
		bool bSettingsLoaded = false;
		bool bMasterMuted = false;
		USoundClass* Classes[ChannelCount] = {};
		USoundConcurrency* GroupConcurrency[ChannelCount] = {};
		USoundConcurrency* EventConcurrency[SoundCount] = {};
		USoundBase* SoundCache[SoundCount][3] = {};
		bool SoundTried[SoundCount][3] = {};
		uint32 LastVariant[SoundCount] = {};
		USoundAttenuation* BattleAttenuation = nullptr;

		bool ValidSound(ESound Sound) { return static_cast<int32>(Sound) < SoundCount; }
		bool ValidChannel(EChannel Channel) { return static_cast<int32>(Channel) < ChannelCount; }
		float SafeVolume(float Value) { return FMath::IsFinite(Value) ? FMath::Clamp(Value, 0.f, 1.f) : 0.f; }

		void LoadSettings()
		{
			if (bSettingsLoaded || !GConfig) return;
			bSettingsLoaded = true;
			GConfig->GetBool(TEXT("CivWar.Audio"), TEXT("Muted"), bMasterMuted, GGameUserSettingsIni);
			for (int32 I = 0; I < ChannelCount; ++I)
			{
				GConfig->GetFloat(TEXT("CivWar.Audio"), ChannelNames[I], Volumes[I], GGameUserSettingsIni);
				Volumes[I] = SafeVolume(Volumes[I]);
			}
		}

		USoundClass* GetClass(EChannel Channel)
		{
			LoadSettings();
			const int32 Index = static_cast<int32>(Channel);
			if (!Classes[Index])
			{
				Classes[Index] = NewObject<USoundClass>(GetTransientPackage());
				Classes[Index]->AddToRoot();
				Classes[Index]->Properties.Volume = bMasterMuted ? 0.f : Volumes[0] * Volumes[Index];
				Classes[Index]->Properties.bIsUISound = Channel != EChannel::Battle;
				Classes[Index]->Properties.bIsMusic = Channel == EChannel::Music;
				// Dynamic classes need registration (there is no imported asset's PostLoad).
				if (GEngine && GEngine->GetAudioDeviceManager())
					GEngine->GetAudioDeviceManager()->RegisterSoundClass(Classes[Index]);
			}
			return Classes[Index];
		}

		USoundConcurrency* MakeConcurrency(int32 Voices, float Retrigger, EMaxConcurrentResolutionRule::Type Rule)
		{
			USoundConcurrency* Result = NewObject<USoundConcurrency>(GetTransientPackage());
			Result->AddToRoot();
			Result->Concurrency.MaxCount = Voices;
			Result->Concurrency.RetriggerTime = Retrigger;
			Result->Concurrency.ResolutionRule = Rule;
			Result->Concurrency.VoiceStealReleaseTime = .035f;
			return Result;
		}

		void Configure(USoundBase* Asset, int32 Index)
		{
			const FSoundProfile& Profile = Profiles[Index];
			const int32 Group = static_cast<int32>(Profile.Channel);
			Asset->SoundClassObject = GetClass(Profile.Channel);
			Asset->Priority = Profile.Priority;
			if (!GroupConcurrency[Group])
			{
				const int32 Voices = Profile.Channel == EChannel::Battle ? 12 : (Profile.Channel == EChannel::Interface ? 4 : 1);
				GroupConcurrency[Group] = MakeConcurrency(Voices, 0.f, EMaxConcurrentResolutionRule::StopLowestPriorityThenPreventNew);
			}
			if (!EventConcurrency[Index])
				EventConcurrency[Index] = MakeConcurrency(Profile.Voices, Profile.Retrigger, EMaxConcurrentResolutionRule::StopOldest);
			Asset->bOverrideConcurrency = false;
			Asset->ConcurrencySet.Reset();
			Asset->ConcurrencySet.Add(GroupConcurrency[Group]);
			Asset->ConcurrencySet.Add(EventConcurrency[Index]);
		}

		const TCHAR* SamplePath(ESound Sound, int32 Variant)
		{
			// Short, licensed historical-weapon one-shots. Keep synthesized variants
			// and the original event mix/concurrency; missing samples safely fall back.
			if (Sound == ESound::HitMetal && Variant == 0)
				return TEXT("/Game/Audio/ThirdParty/TPSFX_SwordMetalHit.TPSFX_SwordMetalHit");
			if (Sound == ESound::HitMetal && Variant == 1)
				return TEXT("/Game/Audio/ThirdParty/TPSFX_ShieldClash.TPSFX_ShieldClash");
			if (Sound == ESound::BaseHit && Variant == 0)
				return TEXT("/Game/Audio/ThirdParty/TPSFX_WoodenSpearHit.TPSFX_WoodenSpearHit");
			if (Sound == ESound::AgeUp && Variant == 0)
				return TEXT("/Game/Audio/ThirdParty/TPSFX_AgeUpEpic.TPSFX_AgeUpEpic");
			return nullptr;
		}

		USoundBase* GetVariant(ESound Sound, int32 Variant)
		{
			if (!ValidSound(Sound)) return nullptr;
			const int32 Index = static_cast<int32>(Sound);
			if (!SoundTried[Index][Variant])
			{
				SoundTried[Index][Variant] = true;
				const FString Name = Variant == 0 ? FString::Printf(TEXT("SFX_%s"), Profiles[Index].Name)
					: FString::Printf(TEXT("SFX_%s_V%02d"), Profiles[Index].Name, Variant + 1);
				const FString Path = FString::Printf(TEXT("/Game/Audio/%s.%s"), *Name, *Name);
				USoundBase* Asset = nullptr;
				if (const TCHAR* Sample = SamplePath(Sound, Variant))
					Asset = LoadObject<USoundBase>(nullptr, Sample, nullptr, LOAD_NoWarn | LOAD_Quiet);
				if (!Asset) Asset = LoadObject<USoundBase>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
				SoundCache[Index][Variant] = Asset;
				if (Asset)
				{
					Asset->AddToRoot();
					Configure(Asset, Index);
				}
			}
			return SoundCache[Index][Variant];
		}

		USoundBase* PickVariant(ESound Sound)
		{
			if (!ValidSound(Sound)) return nullptr;
			const int32 Index = static_cast<int32>(Sound);
			const int32 Count = Profiles[Index].Variants;
			// Round robin is independent of the gameplay RNG; successive impacts never repeat.
			const int32 Variant = LastVariant[Index]++ % Count;
			USoundBase* Asset = GetVariant(Sound, Variant);
			return Asset ? Asset : GetVariant(Sound, 0);
		}

		USoundAttenuation* GetBattleAttenuation()
		{
			if (!BattleAttenuation)
			{
				BattleAttenuation = NewObject<USoundAttenuation>(GetTransientPackage());
				BattleAttenuation->AddToRoot();
				FSoundAttenuationSettings& A = BattleAttenuation->Attenuation;
				A.bAttenuate = true;
				A.bSpatialize = true;
				A.AttenuationShape = EAttenuationShape::Sphere;
				A.AttenuationShapeExtents = FVector(2200.f, 0.f, 0.f);
				A.FalloffDistance = 5500.f;
				A.DistanceAlgorithm = EAttenuationDistanceModel::Linear;
			}
			return BattleAttenuation;
		}

		void NotifyMusic(const UObject* WorldContext, ESound Sound)
		{
			if (!GEngine || bMasterMuted || Volumes[0] <= 0.f || Volumes[static_cast<int32>(EChannel::Music)] <= 0.f
				|| Volumes[static_cast<int32>(Profiles[static_cast<int32>(Sound)].Channel)] <= 0.f) return;
			UWorld* World = GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull);
			UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
			if (UCWMusicSubsystem* Music = Instance ? Instance->GetSubsystem<UCWMusicSubsystem>() : nullptr)
				Music->NotifyMusicEvent(Sound);
		}
	}

	float GetVolume(EChannel Channel)
	{
		LoadSettings();
		return ValidChannel(Channel) ? Volumes[static_cast<int32>(Channel)] : 0.f;
	}

	void SetVolume(EChannel Channel, float Volume)
	{
		if (!ValidChannel(Channel)) return;
		LoadSettings();
		Volumes[static_cast<int32>(Channel)] = SafeVolume(Volume);
		for (int32 I = 1; I < ChannelCount; ++I)
			if (Classes[I]) Classes[I]->Properties.Volume = bMasterMuted ? 0.f : Volumes[0] * Volumes[I];
	}

	bool IsMuted()
	{
		LoadSettings();
		return bMasterMuted;
	}

	void SetMuted(bool bMuted)
	{
		LoadSettings();
		bMasterMuted = bMuted;
		for (int32 I = 1; I < ChannelCount; ++I)
			if (Classes[I]) Classes[I]->Properties.Volume = bMasterMuted ? 0.f : Volumes[0] * Volumes[I];
	}

	void SaveSettings()
	{
		LoadSettings();
		if (!GConfig) return;
		for (int32 I = 0; I < ChannelCount; ++I)
			GConfig->SetFloat(TEXT("CivWar.Audio"), ChannelNames[I], Volumes[I], GGameUserSettingsIni);
		GConfig->SetBool(TEXT("CivWar.Audio"), TEXT("Muted"), bMasterMuted, GGameUserSettingsIni);
		GConfig->Flush(false, GGameUserSettingsIni);
	}

	USoundBase* Get(ESound Sound) { return GetVariant(Sound, 0); }

	void ConfigureMusic(USoundWave* Wave)
	{
		if (!Wave) return;
		Wave->SoundClassObject = GetClass(EChannel::Music);
		Wave->bLooping = true;
		// The player overlaps the file boundary; native looping is its fallback.
		// A music/master mute must not kill the voice or restart the intro.
		Wave->VirtualizationMode = EVirtualizationMode::PlayWhenSilent;
		Wave->Priority = 3.f;
	}

	void Play2D(const UObject* WorldContext, ESound Sound, float Volume, float Pitch)
	{
		if (!WorldContext || !FMath::IsFinite(Volume) || !FMath::IsFinite(Pitch) || Volume <= 0.f) return;
		if (USoundBase* Asset = PickVariant(Sound))
		{
			UGameplayStatics::PlaySound2D(WorldContext, Asset, FMath::Clamp(Volume, 0.f, 1.f), FMath::Clamp(Pitch, .5f, 2.f));
			if (Sound == ESound::AgeUp || Sound == ESound::Victory || Sound == ESound::Defeat)
				NotifyMusic(WorldContext, Sound);
		}
	}

	void PlayAt(const UObject* WorldContext, ESound Sound, const FVector& Location, float Volume, float Pitch)
	{
		if (!WorldContext || Location.ContainsNaN() || !FMath::IsFinite(Volume) || !FMath::IsFinite(Pitch) || Volume <= 0.f) return;
		if (USoundBase* Asset = PickVariant(Sound))
		{
			UGameplayStatics::PlaySoundAtLocation(WorldContext, Asset, Location, FRotator::ZeroRotator,
				FMath::Clamp(Volume, 0.f, 1.f), FMath::Clamp(Pitch, .5f, 2.f), 0.f, GetBattleAttenuation());
			if (Sound == ESound::SkillWarning) NotifyMusic(WorldContext, Sound);
		}
	}
}
