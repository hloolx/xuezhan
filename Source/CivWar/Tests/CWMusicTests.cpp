#include "Misc/AutomationTest.h"
#include "Sound/SoundClass.h"
#include "Sound/SoundWave.h"
#include "View/CWAudio.h"
#include "View/CWMusicSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWLicensedFoleyTest, "CivWar.Audio.LicensedFoley",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWLicensedFoleyTest::RunTest(const FString& Parameters)
{
	for (const TCHAR* Name : {TEXT("SwordMetalHit"), TEXT("ShieldClash"), TEXT("WoodenSpearHit"), TEXT("AgeUpEpic")})
	{
		const FString Path = FString::Printf(TEXT("/Game/Audio/ThirdParty/TPSFX_%s.TPSFX_%s"), Name, Name);
		USoundWave* Wave = LoadObject<USoundWave>(nullptr, *Path);
		TestNotNull(FString::Printf(TEXT("Licensed %s one-shot is imported"), Name), Wave);
		if (!Wave) continue;
		TestEqual(TEXT("Battle one-shots retain spatializable mono"), Wave->NumChannels, 1);
		TestTrue(TEXT("Only one impact plays for each game event"), Wave->Duration > .05f && Wave->Duration <= 2.f && !Wave->bLooping);
	}
	USoundBase* Metal = CWAudio::Get(CWAudio::ESound::HitMetal);
	USoundBase* Structure = CWAudio::Get(CWAudio::ESound::BaseHit);
	USoundBase* AgeUp = CWAudio::Get(CWAudio::ESound::AgeUp);
	TestTrue(TEXT("Metal events actually select the licensed sword sample"), Metal && Metal->GetName() == TEXT("TPSFX_SwordMetalHit"));
	TestTrue(TEXT("Structure impacts actually select the licensed wooden contact"), Structure && Structure->GetName() == TEXT("TPSFX_WoodenSpearHit"));
	TestTrue(TEXT("Age-up uses the preserved melody with its new bass layer"), AgeUp && AgeUp->GetName() == TEXT("TPSFX_AgeUpEpic"));
	if (Metal) TestEqual(TEXT("Real sword samples retain event/group overload protection"), Metal->ConcurrencySet.Num(), 2);
	if (Structure) TestEqual(TEXT("Real structure samples retain event/group overload protection"), Structure->ConcurrencySet.Num(), 2);
	if (AgeUp) TestEqual(TEXT("Composite age-up remains isolated on the announcement group"), AgeUp->ConcurrencySet.Num(), 2);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWMusicAssetAndMixTest, "CivWar.Audio.MusicAssetsAndMix",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWMusicAssetAndMixTest::RunTest(const FString& Parameters)
{
	TArray<USoundWave*> Tracks;
	for (const CWMusic::ECue Cue : {CWMusic::ECue::Menu, CWMusic::ECue::Battle, CWMusic::ECue::Finale})
	{
		USoundWave* Wave = Cast<USoundWave>(CWMusic::AssetPath(Cue).TryLoad());
		TestNotNull(FString::Printf(TEXT("Licensed %s music is imported"), CWMusic::CueName(Cue)), Wave);
		if (!Wave) continue;
		Tracks.Add(Wave);
		// Validate the cooked source properties before runtime safety overrides.
		TestEqual(TEXT("Music retains stereo orchestral image"), Wave->NumChannels, 2);
		TestTrue(TEXT("Music source is a full track, not a placeholder sting"), Wave->Duration >= 30.f && FMath::IsFinite(Wave->Duration));
		TestTrue(TEXT("Native looping remains a fallback if a playback callback is unavailable"), Wave->bLooping != 0);
		TestTrue(TEXT("Long music streams instead of force-inline memory loading"), Wave->IsStreaming());
		TestTrue(TEXT("Imported zero-volume music keeps playback position"), Wave->VirtualizationMode == EVirtualizationMode::PlayWhenSilent);
		CWAudio::ConfigureMusic(Wave);
		TestNotNull(TEXT("Music receives the live native mix class"), Wave->SoundClassObject.Get());
		TestTrue(TEXT("Native class identifies a music bus"), Wave->SoundClassObject->Properties.bIsMusic != 0);
	}
	const float MasterBefore = CWAudio::GetVolume(CWAudio::EChannel::Master);
	const float MusicBefore = CWAudio::GetVolume(CWAudio::EChannel::Music);
	const bool bMutedBefore = CWAudio::IsMuted();
	CWAudio::SetMuted(false);
	USoundBase* Click = CWAudio::Get(CWAudio::ESound::UIClick);
	CWAudio::SetVolume(CWAudio::EChannel::Master, .5f);
	CWAudio::SetVolume(CWAudio::EChannel::Music, .4f);
	for (USoundWave* Wave : Tracks)
		TestTrue(TEXT("Every cached music track follows master times music gain"), FMath::IsNearlyEqual(Wave->SoundClassObject->Properties.Volume, .2f));
	const float ClickGain = Click && Click->SoundClassObject ? Click->SoundClassObject->Properties.Volume : -1.f;
	CWAudio::SetVolume(CWAudio::EChannel::Music, 0.f);
	for (USoundWave* Wave : Tracks)
		TestEqual(TEXT("Music-only mute applies to every cached track"), Wave->SoundClassObject->Properties.Volume, 0.f);
	if (Click && Click->SoundClassObject)
		TestEqual(TEXT("Muting music leaves UI clicks audible at their own level"), Click->SoundClassObject->Properties.Volume, ClickGain);
	CWAudio::SetVolume(CWAudio::EChannel::Music, .6f);
	for (USoundWave* Wave : Tracks)
		TestTrue(TEXT("Music recovers live after mute"), FMath::IsNearlyEqual(Wave->SoundClassObject->Properties.Volume, .3f));
	CWAudio::SetVolume(CWAudio::EChannel::Master, 0.f);
	for (USoundWave* Wave : Tracks)
		TestEqual(TEXT("Master mute also silences the music bus"), Wave->SoundClassObject->Properties.Volume, 0.f);
	CWAudio::SetVolume(CWAudio::EChannel::Master, .5f);
	CWAudio::SetMuted(true);
	for (USoundWave* Wave : Tracks)
		TestEqual(TEXT("Shared mute gate silences cached music"), Wave->SoundClassObject->Properties.Volume, 0.f);
	TestEqual(TEXT("Muting preserves the visible master slider"), CWAudio::GetVolume(CWAudio::EChannel::Master), .5f);
	TestEqual(TEXT("Muting preserves the visible music slider"), CWAudio::GetVolume(CWAudio::EChannel::Music), .6f);
	CWAudio::SetVolume(CWAudio::EChannel::Music, .4f);
	for (USoundWave* Wave : Tracks)
		TestEqual(TEXT("Changing a slider while muted cannot leak audio"), Wave->SoundClassObject->Properties.Volume, 0.f);
	CWAudio::SetMuted(false);
	for (USoundWave* Wave : Tracks)
		TestTrue(TEXT("Unmute restores the selected mix without resetting sliders"), FMath::IsNearlyEqual(Wave->SoundClassObject->Properties.Volume, .2f));
	CWAudio::SetVolume(CWAudio::EChannel::Master, MasterBefore);
	CWAudio::SetVolume(CWAudio::EChannel::Music, MusicBefore);
	CWAudio::SetMuted(bMutedBefore);
	// Deliberately do not save test values to the player's settings.
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWMusicSceneTest, "CivWar.Audio.MusicScenes",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWMusicSceneTest::RunTest(const FString& Parameters)
{
	cw::RulesDef Rules;
	// Non-default rules catch presentation thresholds accidentally hard-coded to
	// 50% HP or 12 minutes rather than following the authoritative game data.
	Rules.LastStandBaseHpRatio = .35f;
	Rules.SuddenDeathTime = 540.f;
	FCWTeamNetState Home;
	FCWTeamNetState Away;
	Home.BaseHp = Home.BaseMaxHp = 1000.f;
	Away.BaseHp = Away.BaseMaxHp = 1500.f;
	const auto Select = [&](ECWMatchPhase Phase, float Time, bool bLatched = false)
	{
		return CWMusic::SelectCue(Phase, Time, Rules, Home, Away, bLatched);
	};
	TestTrue(TEXT("Menu uses Titan"), Select(ECWMatchPhase::Menu, 0.f) == CWMusic::ECue::Menu);
	TestTrue(TEXT("Waiting lobby uses Titan"), Select(ECWMatchPhase::Lobby, 0.f) == CWMusic::ECue::Menu);
	TestTrue(TEXT("Countdown does not start the battle track prematurely"), Select(ECWMatchPhase::Countdown, 0.f) == CWMusic::ECue::Menu);
	TestTrue(TEXT("An ordinary active battle uses Legionnaire"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Battle);
	TestTrue(TEXT("One tick before sudden death is still battle"), Select(ECWMatchPhase::InMatch, 539.95f) == CWMusic::ECue::Battle);
	TestTrue(TEXT("Sudden death starts at the actual rule boundary"), Select(ECWMatchPhase::InMatch, 540.f) == CWMusic::ECue::Finale);
	Home.BaseHp = 350.1f;
	TestTrue(TEXT("No false finale immediately above last-stand HP threshold"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Battle);
	Home.BaseHp = 350.f;
	TestTrue(TEXT("Local base danger starts Juggernaut"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Finale);
	Home.BaseHp = 1000.f;
	TestTrue(TEXT("Repair cannot cause music to chatter back to battle"), Select(ECWMatchPhase::InMatch, 21.f, true) == CWMusic::ECue::Finale);
	Away.BaseHp = 525.f;
	TestTrue(TEXT("Enemy base danger also reflects an imminent decisive assault"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Finale);
	Away.BaseHp = 1500.f;
	Home.bLastStandUsed = true;
	TestTrue(TEXT("Late-joining client recognizes an already-triggered last stand after repair"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Finale);
	Home.bLastStandUsed = false;
	Away.TurretBoostTime = 1.f;
	TestTrue(TEXT("Replicated active last-stand boost starts the finale"), Select(ECWMatchPhase::InMatch, 20.f) == CWMusic::ECue::Finale);
	TestTrue(TEXT("Result screen clears music for outcome stings"), Select(ECWMatchPhase::PostMatch, 20.f, true) == CWMusic::ECue::Silent);
	TestTrue(TEXT("Returning to lobby ignores old last-stand flags and latch"), Select(ECWMatchPhase::Lobby, 20.f, true) == CWMusic::ECue::Menu);
	Away.TurretBoostTime = 0.f;
	TestTrue(TEXT("New match starts with battle music"), Select(ECWMatchPhase::InMatch, 0.f) == CWMusic::ECue::Battle);
	Home.BaseMaxHp = Away.BaseMaxHp = 0.f;
	Home.BaseHp = Away.BaseHp = 0.f;
	TestTrue(TEXT("Uninitialized replicated HP cannot signal a decisive assault"), Select(ECWMatchPhase::InMatch, 0.f) == CWMusic::ECue::Battle);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWMusicLoopAndFocusTest, "CivWar.Audio.MusicLoopAndFocus",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWMusicLoopAndFocusTest::RunTest(const FString& Parameters)
{
	for (const CWMusic::ECue Cue : {CWMusic::ECue::Menu, CWMusic::ECue::Battle, CWMusic::ECue::Finale})
	{
		const USoundWave* Wave = Cast<USoundWave>(CWMusic::AssetPath(Cue).TryLoad());
		if (!TestNotNull(TEXT("Real imported track is available for boundary checks"), Wave)) continue;
		const float Boundary = Wave->Duration - CWMusic::LoopCrossfadeSeconds(Wave->Duration);
		TestFalse(TEXT("Music is not cut before the overlap window"), CWMusic::IsInLoopCrossfade(Boundary - .01f, Wave->Duration));
		TestTrue(TEXT("The next voice starts before the old file ends"), CWMusic::IsInLoopCrossfade(Boundary, Wave->Duration));
		TestFalse(TEXT("A new voice at the intro cannot immediately restart itself"), CWMusic::IsInLoopCrossfade(0.f, Wave->Duration));
	}
	TestFalse(TEXT("Unknown duration never attempts a zero-length loop"), CWMusic::IsInLoopCrossfade(0.f, 0.f));
	TestFalse(TEXT("An accidental short sting is not treated as a music loop"), CWMusic::IsInLoopCrossfade(1.f, 2.f));

	CWMusic::FFocusEnvelope Focus;
	Focus.Trigger(CWAudio::ESound::HitMetal);
	Focus.Tick(.2f);
	TestEqual(TEXT("Routine combat impacts do not pump the music"), Focus.Envelope.Gain, 1.f);
	Focus.Trigger(CWAudio::ESound::AgeUp);
	Focus.Tick(.14f);
	TestTrue(TEXT("An important upgrade briefly clears space for its cue"), FMath::IsNearlyEqual(Focus.Envelope.Gain, .68f));
	for (int32 I = 0; I < 20; ++I) Focus.Trigger(CWAudio::ESound::AgeUp);
	Focus.Tick(.2f);
	TestTrue(TEXT("Repeated events do not multiply the music into silence"), FMath::IsNearlyEqual(Focus.Envelope.Gain, .68f));
	Focus.Trigger(CWAudio::ESound::Victory);
	Focus.Tick(.14f);
	Focus.Trigger(CWAudio::ESound::SkillWarning);
	Focus.Tick(.2f);
	TestTrue(TEXT("A weaker warning cannot cancel the result cue's space"), FMath::IsNearlyEqual(Focus.Envelope.Gain, .38f));
	for (int32 I = 0; I < 50; ++I) Focus.Tick(.1f);
	TestTrue(TEXT("The mix returns to the exact selected level after the hold and release"), FMath::IsNearlyEqual(Focus.Envelope.Gain, 1.f));
	Focus.Trigger(CWAudio::ESound::AgeUp);
	Focus.Tick(.14f);
	Focus.Reset();
	TestEqual(TEXT("A new map does not inherit the previous result duck"), Focus.Envelope.Gain, 1.f);
	TestEqual(TEXT("A new map clears pending focus holds"), Focus.HoldRemaining, 0.f);

	CWMusic::FGainEnvelope ReversibleFade;
	ReversibleFade.To(0.f, 2.5f);
	ReversibleFade.Tick(.8f);
	const float BeforeReverse = ReversibleFade.Gain;
	ReversibleFade.To(1.f, 2.5f);
	TestEqual(TEXT("Returning rapidly to a cue resumes at the current gain without a step"), ReversibleFade.Gain, BeforeReverse);
	ReversibleFade.Tick(2.5f);
	TestEqual(TEXT("The resumed cue reaches full gain"), ReversibleFade.Gain, 1.f);
	return true;
}

#endif
