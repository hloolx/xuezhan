#include "Misc/AutomationTest.h"
#include "View/CWAudio.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundClass.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWAudioAssetAndMixTest, "CivWar.Audio.AssetsAndMix",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWAudioAssetAndMixTest::RunTest(const FString& Parameters)
{
	for (uint8 I = 0; I < static_cast<uint8>(CWAudio::ESound::Count); ++I)
	{
		USoundBase* Asset = CWAudio::Get(static_cast<CWAudio::ESound>(I));
		TestNotNull(FString::Printf(TEXT("Playable event %d exists after import"), I), Asset);
		if (!Asset) continue;
		TestTrue(TEXT("Every event has positive finite duration"), FMath::IsFinite(Asset->GetDuration()) && Asset->GetDuration() > 0.f);
		TestEqual(TEXT("Slate and gameplay assets share native group and event concurrency"), Asset->ConcurrencySet.Num(), 2);
		TestNotNull(TEXT("All sounds have a volume-controlled class"), Asset->SoundClassObject.Get());
	}

	// Slate plays Get(UIClick) directly, bypassing Play2D. Its class must still obey mute.
	USoundBase* Click = CWAudio::Get(CWAudio::ESound::UIClick);
	if (Click && Click->SoundClassObject)
	{
		const float OldMaster = CWAudio::GetVolume(CWAudio::EChannel::Master);
		const float OldUI = CWAudio::GetVolume(CWAudio::EChannel::Interface);
		const bool bWasMuted = CWAudio::IsMuted();
		CWAudio::SetMuted(false);
		CWAudio::SetVolume(CWAudio::EChannel::Master, .5f);
		CWAudio::SetVolume(CWAudio::EChannel::Interface, .4f);
		TestTrue(TEXT("Direct Slate resource receives combined master/UI gain"),
			FMath::IsNearlyEqual(Click->SoundClassObject->Properties.Volume, .2f));
		CWAudio::SetVolume(CWAudio::EChannel::Master, 0.f);
		TestEqual(TEXT("Master mute applies to cached Slate click"), Click->SoundClassObject->Properties.Volume, 0.f);
		CWAudio::SetVolume(CWAudio::EChannel::Master, OldMaster);
		CWAudio::SetVolume(CWAudio::EChannel::Interface, OldUI);
		CWAudio::SetMuted(bWasMuted);
	}
	return true;
}

#endif
