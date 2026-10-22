#include "UI/SCWAudioSettings.h"

#include "UI/CWUIStyle.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SSlider.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CivWarAudioSettings"

void SCWAudioSettings::Construct(const FArguments& InArgs)
{
	auto Action = [](const TAttribute<FText>& Text, FOnClicked Click, const FText& Tooltip)
	{
		return SNew(SButton).ButtonStyle(&CWUI::ButtonStyle()).OnClicked(Click).ToolTipText(Tooltip)
			.HAlign(HAlign_Center).VAlign(VAlign_Center)
			[ SNew(STextBlock).Text(Text).Font(CWUI::Font(14, true)).ColorAndOpacity(CWUI::TextMain) ];
	};
	ChildSlot
	[
		SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()
		[ MakeVolumeRow(LOCTEXT("Master", "主音量"), CWAudio::EChannel::Master) ]
		+ SVerticalBox::Slot().AutoHeight()
		[ MakeVolumeRow(LOCTEXT("Music", "史诗配乐"), CWAudio::EChannel::Music) ]
		+ SVerticalBox::Slot().AutoHeight()
		[ MakeVolumeRow(LOCTEXT("Battle", "战场音效"), CWAudio::EChannel::Battle) ]
		+ SVerticalBox::Slot().AutoHeight()
		[ MakeVolumeRow(LOCTEXT("Interface", "界面反馈"), CWAudio::EChannel::Interface) ]
		+ SVerticalBox::Slot().AutoHeight()
		[ MakeVolumeRow(LOCTEXT("Announcements", "战局提示"), CWAudio::EChannel::Announcements) ]
		+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f, 0.f, 8.f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 6.f, 0.f)
			[ Action(TAttribute<FText>::CreateLambda([]() { return CWAudio::IsMuted() ? LOCTEXT("Unmute", "恢复声音") : LOCTEXT("Mute", "全部静音"); }),
				FOnClicked::CreateSP(this, &SCWAudioSettings::ToggleMute), LOCTEXT("MuteTip", "临时关闭全部声音，保留每一路音量；再次点击恢复。")) ]
			+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 6.f, 0.f)
			[ Action(LOCTEXT("PreviewBattle", "试听战场"), FOnClicked::CreateSP(this, &SCWAudioSettings::PreviewSound, CWAudio::ESound::HitMetal),
				LOCTEXT("PreviewBattleTip", "以当前音量试听一次短促金属碰撞。不会解除静音。")) ]
			+ SHorizontalBox::Slot().FillWidth(1.f)
			[ Action(LOCTEXT("PreviewNotice", "试听提示"), FOnClicked::CreateSP(this, &SCWAudioSettings::PreviewSound, CWAudio::ESound::AgeUp),
				LOCTEXT("PreviewNoticeTip", "以当前音量试听一次升级提示。不会解除静音。")) ]
		]
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(STextBlock).Font(CWUI::Font(13)).AutoWrapText(true)
			.ColorAndOpacity_Lambda([]() { return CWAudio::IsMuted() ? CWUI::Warning : CWUI::TextDim; })
			.Text_Lambda([]()
			{
				if (CWAudio::IsMuted()) return LOCTEXT("MutedState", "全部声音已静音，音量设置仍保留。点击“恢复声音”继续播放。");
				if (CWAudio::GetVolume(CWAudio::EChannel::Master) <= 0.f) return LOCTEXT("ZeroMaster", "主音量为 0%，提高主音量后可听到声音。");
				return LOCTEXT("SavedHint", "调整立即生效并自动保存。Tab 切换项目，方向键微调音量。");
			})
		]
	];
}

TSharedRef<SWidget> SCWAudioSettings::MakeVolumeRow(const FText& Label, CWAudio::EChannel Channel)
{
	static const FSliderStyle SliderStyle = []()
	{
		FSliderStyle Style;
		const FSlateRoundedBoxBrush Bar(FLinearColor::White, 2.f);
		const FSlateRoundedBoxBrush Thumb(FLinearColor::White, 3.f, FVector2f(16.f, 20.f));
		Style.SetNormalBarImage(Bar).SetHoveredBarImage(Bar).SetDisabledBarImage(Bar);
		Style.SetNormalThumbImage(Thumb).SetHoveredThumbImage(Thumb).SetDisabledThumbImage(Thumb);
		Style.SetBarThickness(4.f);
		return Style;
	}();
	return SNew(SVerticalBox)
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().FillWidth(1.f)
			[ SNew(STextBlock).Text(Label).Font(CWUI::Font(15)).ColorAndOpacity(CWUI::TextMain) ]
			+ SHorizontalBox::Slot().AutoWidth()
			[ SNew(STextBlock).Font(CWUI::Font(15, true)).ColorAndOpacity(CWUI::Gold)
				.Text_Lambda([Channel]() { return FText::AsPercent(CWAudio::GetVolume(Channel)); }) ]
		]
		+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f, 0.f, 10.f)
		[
			SNew(SSlider).Style(&SliderStyle).IsFocusable(true).RequiresControllerLock(false).MouseUsesStep(true)
			.Value_Lambda([Channel]() { return CWAudio::GetVolume(Channel); }).StepSize(0.05f)
			.ToolTipText(Label).SliderBarColor(FLinearColor(0.36f, 0.43f, 0.38f)).SliderHandleColor(CWUI::Gold)
			.OnValueChanged(this, &SCWAudioSettings::OnVolumeChanged, Channel)
			.OnMouseCaptureEnd(this, &SCWAudioSettings::SavePendingVolume)
			.OnControllerCaptureEnd(this, &SCWAudioSettings::SavePendingVolume)
		];
}

SCWAudioSettings::~SCWAudioSettings()
{
	SavePendingVolume();
}

void SCWAudioSettings::Tick(const FGeometry& AllottedGeometry, double InCurrentTime, float InDeltaTime)
{
	SCompoundWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);
	// Arrow-key navigation does not capture SSlider when RequiresControllerLock
	// is false. Debounce that path too; never flush the ini on every drag pixel.
	if (bVolumeDirty && FPlatformTime::Seconds() - LastVolumeChangeTime >= 0.4) SavePendingVolume();
}

void SCWAudioSettings::OnVolumeChanged(float Value, CWAudio::EChannel Channel)
{
	CWAudio::SetVolume(Channel, Value);
	LastVolumeChangeTime = FPlatformTime::Seconds();
	bVolumeDirty = true;
}

void SCWAudioSettings::SavePendingVolume()
{
	if (bVolumeDirty) CWAudio::SaveSettings();
	bVolumeDirty = false;
}

FReply SCWAudioSettings::ToggleMute()
{
	CWAudio::SetMuted(!CWAudio::IsMuted());
	CWAudio::SaveSettings();
	return FReply::Handled();
}

FReply SCWAudioSettings::PreviewSound(CWAudio::ESound Sound)
{
	const double Now = FPlatformTime::Seconds();
	if (Now - LastPreviewTime < 1.5 || CWAudio::IsMuted()) return FReply::Handled();
	LastPreviewTime = Now;
	if (GEngine && GEngine->GameViewport)
	{
		CWAudio::Play2D(GEngine->GameViewport->GetWorld(), Sound, 0.5f);
	}
	return FReply::Handled();
}

#undef LOCTEXT_NAMESPACE
