// 血战文明 - 主菜单与房间界面（Slate）
#pragma once

#include "CoreMinimal.h"
#include "Widgets/SCompoundWidget.h"
#include "UI/CWUIStyle.h"

class ACWPlayerController;
class SEditableTextBox;
class UCWGameInstance;

namespace CWUI
{
	// 通用按钮：正常/悬停/按下/禁用四态由样式提供；禁用原因显示在提示与按钮下方
	TSharedRef<SWidget> MakeButton(const TAttribute<FText>& Label, FOnClicked OnClicked, EButtonKind Kind = EButtonKind::Normal,
		float Width = 300.f, const TAttribute<bool>& Enabled = true, const TAttribute<FText>& Tooltip = FText::GetEmpty(), int32 FontSize = 18);
}

class SCWMainMenu : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCWMainMenu) {}
		SLATE_ARGUMENT(TWeakObjectPtr<UCWGameInstance>, GameInstance)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual void Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime) override;
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual FReply OnPreviewKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;
	FReply OnPreviewAge(int32 Age);
	int32 GetPreviewAge() const;

private:
	enum class EPage : uint8
	{
		Root,
		Single,
		Multi,
		Settings,
		Credits,
		Guide,
	};

	EVisibility PageVisibility(EPage InPage) const { return Page == InPage ? EVisibility::Visible : EVisibility::Collapsed; }
	FReply GoTo(EPage InPage);
	FReply OnSingle(int32 Difficulty);
	FReply OnHost();
	FReply OnJoin();
	FReply OnCancelJoin();
	FReply OnQuality(int32 Level);
	FReply OnWindowMode(bool bFullscreen);
	FReply OnQuit();
	FText GetPageTitle() const;
	FText GetPageDescription() const;
	FText GetPreviewTitle() const;
	FText GetPreviewUnits() const;
	bool CanInteract() const;
	void OnNameChanged(const FText& Text);
	FText GetErrorText() const { return ErrorText; }
	FText GetConnectingText() const;
	EVisibility GetConnectingVisibility() const;
	void ApplyName();

	TWeakObjectPtr<UCWGameInstance> GameInstance;
	TSharedPtr<SEditableTextBox> AddressBox;
	TSharedPtr<SEditableTextBox> NameBox;
	EPage Page = EPage::Root;
	FText ErrorText;
	bool bNeedsInitialFocus = true;
#if WITH_EDITOR
	// A local, opt-in connection/cancel capture fixture; never hosts a room.
	bool bConnectionReview = false;
	uint8 ConnectionReviewStage = 0;
	uint64 ConnectionRecoveryFrame = 0;
#endif
};

class SCWLobby : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCWLobby) {}
		SLATE_ARGUMENT(TWeakObjectPtr<ACWPlayerController>, Controller)
	SLATE_END_ARGS()

	void Construct(const FArguments& InArgs);
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual FReply OnPreviewKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent) override;

private:
	TSharedRef<SWidget> MakeSlotCard(int32 Team);
	FText GetSlotName(int32 Team) const;
	FText GetSlotStatus(int32 Team) const;
	FSlateColor GetSlotStatusColor(int32 Team) const;
	FText GetReadyLabel() const;
	FText GetHeaderText() const;
	FText GetStatusText() const;
	FText GetCountdownText() const;
	FReply OnToggleReady();
	FReply OnLeave();
	FReply OnAudioSettings();
	bool IsLocalReady() const;

	TWeakObjectPtr<ACWPlayerController> Controller;
};
