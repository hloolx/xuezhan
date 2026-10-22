// Shared native audio controls for front-end and in-match menus.
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "View/CWAudio.h"

class SCWAudioSettings : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCWAudioSettings) {}
	SLATE_END_ARGS()
	void Construct(const FArguments& InArgs);
	virtual ~SCWAudioSettings() override;
	virtual void Tick(const FGeometry& AllottedGeometry, double InCurrentTime, float InDeltaTime) override;

private:
	TSharedRef<SWidget> MakeVolumeRow(const FText& Label, CWAudio::EChannel Channel);
	FReply ToggleMute();
	FReply PreviewSound(CWAudio::ESound Sound);
	void OnVolumeChanged(float Value, CWAudio::EChannel Channel);
	void SavePendingVolume();
	double LastPreviewTime = -1.0;
	double LastVolumeChangeTime = 0.0;
	bool bVolumeDirty = false;
};
