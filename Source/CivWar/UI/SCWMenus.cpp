#include "UI/SCWMenus.h"

#include "UI/CWHUD.h"
#include "UI/SCWAudioSettings.h"
#include "UI/SCWEpicFrame.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "Game/CWGameInstance.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "Game/CWPlayerState.h"
#include "GameFramework/GameUserSettings.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Kismet/KismetSystemLibrary.h"
#include "View/CWAudio.h"
#include "View/CWMenuShowcase.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/SWindow.h"
#include "Widgets/Text/STextBlock.h"
#if WITH_EDITOR
#include "UnrealClient.h"
#endif

#define LOCTEXT_NAMESPACE "CivWarUI"

TSharedRef<SWidget> CWUI::MakeButton(const TAttribute<FText>& Label, FOnClicked OnClicked, EButtonKind Kind, float Width,
	const TAttribute<bool>& Enabled, const TAttribute<FText>& Tooltip, int32 FontSize)
{
	return SNew(SBox)
		.WidthOverride(Width > 0.f ? FOptionalSize(Width) : FOptionalSize())
		[
			SNew(SButton)
			.ButtonStyle(&ButtonStyle(Kind))
			.IsEnabled(Enabled)
			.ToolTipText(Tooltip)
			.OnClicked(OnClicked)
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			[
				SNew(STextBlock)
				.Text(Label)
				.Font(Font(FontSize, true))
				.ColorAndOpacity(TextMain)
				.Justification(ETextJustify::Center)
			]
		];
}

// ---------------------------------------------------------------------------
// 主菜单
// ---------------------------------------------------------------------------
void SCWMainMenu::Construct(const FArguments& InArgs)
{
	GameInstance = InArgs._GameInstance;
#if WITH_EDITOR
	FString ReviewPage;
	if (FParse::Value(FCommandLine::Get(), TEXT("cwuipage="), ReviewPage))
	{
		if (ReviewPage == TEXT("settings")) Page = EPage::Settings;
		else if (ReviewPage == TEXT("credits")) Page = EPage::Credits;
		else if (ReviewPage == TEXT("guide")) Page = EPage::Guide;
		else if (ReviewPage == TEXT("single")) Page = EPage::Single;
		else if (ReviewPage == TEXT("multi")) Page = EPage::Multi;
		else if (ReviewPage == TEXT("connecting"))
		{
			Page = EPage::Multi;
			bConnectionReview = true;
		}
	}
#endif
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		ErrorText = GI->ConsumePendingError();
		if (!ErrorText.IsEmpty()) Page = EPage::Multi;
	}
	const FString DefaultName = GameInstance.IsValid() ? GameInstance->PlayerName.Left(16) : FString(TEXT("玩家"));
	auto Title = [](const FText& Text, int32 Size, const FLinearColor& Color)
	{
		return SNew(STextBlock).Text(Text).Font(CWUI::Font(Size, true)).ColorAndOpacity(Color).AutoWrapText(true);
	};
	auto Label = [](const TAttribute<FText>& Text, int32 Size = 15)
	{
		return SNew(STextBlock).Text(Text).Font(CWUI::Font(Size)).ColorAndOpacity(CWUI::TextDim).AutoWrapText(true);
	};
	auto PageBox = [this](EPage Which)
	{
		return SNew(SVerticalBox).Visibility_Lambda([this, Which]() { return PageVisibility(Which); });
	};
	auto Back = [this]()
	{
		return CWUI::MakeButton(LOCTEXT("BackToRoot", "返回首页"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Root),
			CWUI::EButtonKind::Normal, 160.f, true, LOCTEXT("BackTip", "Esc 返回首页"), 16);
	};
	auto SettingChoice = [](const FText& Text, FOnClicked OnClicked, float Width, TAttribute<bool> Selected)
	{
		return SNew(SBox).WidthOverride(Width)
		[
			SNew(SButton).ButtonStyle(&CWUI::ButtonStyle()).OnClicked(OnClicked)
			.HAlign(HAlign_Center).VAlign(VAlign_Center)
			[
				SNew(STextBlock).Font(CWUI::Font(16, true))
				.Text_Lambda([Text, Selected]() { return Selected.Get() ? FText::Format(LOCTEXT("SelectedSetting", "[{0}]"), Text) : Text; })
				.ColorAndOpacity_Lambda([Selected]() { return Selected.Get() ? CWUI::Gold : CWUI::TextMain; })
			]
		];
	};
	auto QualitySelected = [](int32 Level)
	{
		return TAttribute<bool>::CreateLambda([Level]()
		{
			const UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr;
			return Settings && Settings->GetOverallScalabilityLevel() == Level;
		});
	};
	auto WindowModeSelected = [](bool Fullscreen)
	{
		return TAttribute<bool>::CreateLambda([Fullscreen]()
		{
			if (GEngine && GEngine->GameViewport)
			{
				const TSharedPtr<SWindow> Window = GEngine->GameViewport->GetWindow();
				if (Window.IsValid() && Window->GetNativeWindow().IsValid())
					return (Window->GetWindowMode() != EWindowMode::Windowed) == Fullscreen;
			}
			const UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr;
			return Settings && (Settings->GetFullscreenMode() != EWindowMode::Windowed) == Fullscreen;
		});
	};

	TSharedRef<SVerticalBox> RootPage = PageBox(EPage::Root);
	RootPage->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 10.f)
	[
		SNew(SBox).HeightOverride(74.f)
		[ CWUI::MakeButton(LOCTEXT("Single", "开始征战"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Single),
			CWUI::EButtonKind::Primary, 0.f, true, LOCTEXT("SingleTip", "选择电脑难度，从石器时代开始一场对局"), 24) ]
	];
	RootPage->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 18.f)
	[ Label(LOCTEXT("SingleDescription", "单人对抗电脑，逐步进化你的文明。"), 14) ];
	RootPage->AddSlot().AutoHeight()
	[
		SNew(SBox).HeightOverride(52.f)
		[ CWUI::MakeButton(LOCTEXT("Multi", "联机对战"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Multi),
			CWUI::EButtonKind::Normal, 0.f, true, LOCTEXT("MultiTip", "创建房间或输入朋友的主机地址，双人对抗"), 18) ]
	];
	RootPage->AddSlot().AutoHeight().Padding(0.f, 30.f, 0.f, 10.f)
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 8.f, 0.f)
		[ CWUI::MakeButton(LOCTEXT("Settings", "画面与声音"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Settings), CWUI::EButtonKind::Normal, 0.f, true, FText::GetEmpty(), 16) ]
		+ SHorizontalBox::Slot().FillWidth(1.f)
		[ CWUI::MakeButton(LOCTEXT("Guide", "操作指南"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Guide), CWUI::EButtonKind::Normal, 0.f, true, FText::GetEmpty(), 16) ]
	];
	RootPage->AddSlot().AutoHeight()
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 8.f, 0.f)
		[ CWUI::MakeButton(LOCTEXT("Credits", "音乐与素材"), FOnClicked::CreateSP(this, &SCWMainMenu::GoTo, EPage::Credits), CWUI::EButtonKind::Normal, 0.f, true, FText::GetEmpty(), 14) ]
		+ SHorizontalBox::Slot().FillWidth(1.f)
		[ CWUI::MakeButton(LOCTEXT("Quit", "退出游戏"), FOnClicked::CreateSP(this, &SCWMainMenu::OnQuit), CWUI::EButtonKind::Normal, 0.f, true, FText::GetEmpty(), 14) ]
	];
	RootPage->AddSlot().AutoHeight().Padding(0.f, 32.f, 0.f, 8.f)
	[ Title(LOCTEXT("FirstBattle", "第一次出征？"), 18, CWUI::TextMain) ];
	RootPage->AddSlot().AutoHeight()
	[ Label(LOCTEXT("MenuIntroduction", "先选国策，再训练部队。\n金币会自动增长，积累经验后进化时代。\n守住己方基地，摧毁敌方基地。")) ];

	TSharedRef<SVerticalBox> SinglePage = PageBox(EPage::Single);
	SinglePage->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 18.f)
	[ Label(LOCTEXT("PickDifficulty", "每局从石器时代开始。电脑与玩家遵守相同的资源、训练和升级规则。")) ];
	for (int32 Difficulty = 0; Difficulty < 3; ++Difficulty)
	{
		const FText Name = Difficulty == 0 ? LOCTEXT("Easy", "简单") : Difficulty == 1 ? LOCTEXT("Normal", "普通") : LOCTEXT("Hard", "困难");
		SinglePage->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 10.f)
		[ SNew(SBox).HeightOverride(54.f)
			[ CWUI::MakeButton(Name, FOnClicked::CreateSP(this, &SCWMainMenu::OnSingle, Difficulty), Difficulty == 1 ? CWUI::EButtonKind::Primary : CWUI::EButtonKind::Normal, 0.f) ] ];
	}
	SinglePage->AddSlot().AutoHeight().Padding(0.f, 8.f, 0.f, 24.f)
	[ Label(LOCTEXT("NewPlayerDifficulty", "首次体验可从简单开始，熟悉训练、国策与统帅操作。")) ];
	SinglePage->AddSlot().AutoHeight()[ Back() ];

	TSharedRef<SVerticalBox> MultiPage = PageBox(EPage::Multi);
	MultiPage->AddSlot().AutoHeight()[ Label(LOCTEXT("NameLabel", "玩家名称 · 最多 16 字")) ];
	MultiPage->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 18.f)
	[
		SAssignNew(NameBox, SEditableTextBox).Style(&CWUI::TextBoxStyle()).Font(CWUI::Font(16))
		.Text(FText::FromString(DefaultName)).OnTextChanged(this, &SCWMainMenu::OnNameChanged)
		.ToolTipText(LOCTEXT("NameTip", "最多 16 字；空格和地址分隔符会替换为下划线。"))
	];
	MultiPage->AddSlot().AutoHeight()
	[ CWUI::MakeButton(LOCTEXT("Host", "创建房间"), FOnClicked::CreateSP(this, &SCWMainMenu::OnHost), CWUI::EButtonKind::Primary, 0.f) ];
	MultiPage->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 26.f)
	[ Label(LOCTEXT("HostDescription", "创建后，将房间里显示的地址发给朋友。"), 14) ];
	MultiPage->AddSlot().AutoHeight()[ Label(LOCTEXT("AddressLabel", "加入朋友的房间")) ];
	MultiPage->AddSlot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 8.f, 0.f)
		[
			SAssignNew(AddressBox, SEditableTextBox).Style(&CWUI::TextBoxStyle()).Font(CWUI::Font(16))
			.HintText(LOCTEXT("AddressHint", "IP 或 IP:端口"))
			.ToolTipText(LOCTEXT("AddressTip", "例如 192.168.1.20，或 192.168.1.20:7777；按 Enter 加入。"))
			.OnTextCommitted_Lambda([this](const FText&, ETextCommit::Type Commit) { if (Commit == ETextCommit::OnEnter && CanInteract()) OnJoin(); })
		]
		+ SHorizontalBox::Slot().AutoWidth()
		[ CWUI::MakeButton(LOCTEXT("Join", "加入"), FOnClicked::CreateSP(this, &SCWMainMenu::OnJoin), CWUI::EButtonKind::Normal, 88.f, true, LOCTEXT("JoinTip", "连接到输入的主机地址，Enter 也可提交"), 16) ]
	];
	MultiPage->AddSlot().AutoHeight().Padding(0.f, 8.f, 0.f, 0.f)
	[
		SNew(STextBlock).Text(this, &SCWMainMenu::GetErrorText).Font(CWUI::Font(15, true)).ColorAndOpacity(CWUI::Bad).AutoWrapText(true)
		.Visibility_Lambda([this]() { return ErrorText.IsEmpty() ? EVisibility::Collapsed : EVisibility::Visible; })
	];
	MultiPage->AddSlot().AutoHeight().Padding(0.f, 16.f, 0.f, 24.f)
	[ Label(LOCTEXT("NetNote", "同一局域网可直接连接。异地联机需主机开放 UDP 7777 端口；地址未带端口时使用 7777。"), 14) ];
	MultiPage->AddSlot().AutoHeight()[ Back() ];

	TSharedRef<SVerticalBox> SettingsPage = PageBox(EPage::Settings);
	SettingsPage->AddSlot().AutoHeight()
	[ Label(TAttribute<FText>::CreateLambda([]()
		{
			const UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr;
			return Settings && Settings->GetOverallScalabilityLevel() < 0 ? LOCTEXT("CustomQuality", "画面质量 · 自定义") : LOCTEXT("Quality", "画面质量");
		})) ];
	TSharedRef<SHorizontalBox> QualityRow = SNew(SHorizontalBox);
	for (int32 Level = 0; Level < 4; ++Level)
	{
		const FText Names[] = { LOCTEXT("Q0", "低"), LOCTEXT("Q1", "中"), LOCTEXT("Q2", "高"), LOCTEXT("Q3", "极高") };
		QualityRow->AddSlot().AutoWidth().Padding(0.f, 0.f, 6.f, 0.f)
		[ SettingChoice(Names[Level], FOnClicked::CreateSP(this, &SCWMainMenu::OnQuality, Level), 92.f, QualitySelected(Level)) ];
	}
	SettingsPage->AddSlot().AutoHeight().Padding(0.f, 4.f, 0.f, 12.f)[ QualityRow ];
	SettingsPage->AddSlot().AutoHeight()[ Label(LOCTEXT("Display", "显示模式")) ];
	SettingsPage->AddSlot().AutoHeight().Padding(0.f, 4.f, 0.f, 20.f)
	[
		SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 6.f, 0.f)
		[ SettingChoice(LOCTEXT("Fullscreen", "全屏"), FOnClicked::CreateSP(this, &SCWMainMenu::OnWindowMode, true), 120.f, WindowModeSelected(true)) ]
		+ SHorizontalBox::Slot().AutoWidth()
		[ SettingChoice(LOCTEXT("Windowed", "窗口"), FOnClicked::CreateSP(this, &SCWMainMenu::OnWindowMode, false), 120.f, WindowModeSelected(false)) ]
	];
	SettingsPage->AddSlot().AutoHeight()[ SNew(SCWAudioSettings) ];
	SettingsPage->AddSlot().AutoHeight().Padding(0.f, 22.f, 0.f, 0.f)[ Back() ];

	TSharedRef<SVerticalBox> GuidePage = PageBox(EPage::Guide);
	GuidePage->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 18.f)
	[ Label(LOCTEXT("GuideAim", "保护基地、训练军队、积累经验，再升级时代。开局与进化时出现的国策，选定后永久生效。")) ];
	auto GuideRow = [&GuidePage](const FText& Keys, const FText& Meaning)
	{
		GuidePage->AddSlot().AutoHeight().Padding(0.f, 0.f, 0.f, 11.f)
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().Padding(0.f, 0.f, 14.f, 0.f)
			[ SNew(SBox).WidthOverride(150.f)
				[ SNew(STextBlock).Text(Keys).Font(CWUI::Font(15, true)).ColorAndOpacity(CWUI::Gold).AutoWrapText(true) ] ]
			+ SHorizontalBox::Slot().FillWidth(1.f)
			[ SNew(STextBlock).Text(Meaning).Font(CWUI::Font(15)).ColorAndOpacity(CWUI::TextMain).AutoWrapText(true) ]
		];
	};
	GuideRow(LOCTEXT("GuideTrainKeys", "1 / 2 / 3"), LOCTEXT("GuideTrainText", "训练对应兵种；点击队列可取消训练"));
	GuideRow(LOCTEXT("GuideEconKeys", "E / U"), LOCTEXT("GuideEconText", "升级金矿 / 进化时代"));
	GuideRow(LOCTEXT("GuideStanceKeys", "F"), LOCTEXT("GuideStanceText", "切换全军推进与驻守"));
	GuideRow(LOCTEXT("GuideSpellKeys", "Q → 左键"), LOCTEXT("GuideSpellText", "选择技能目标；右键或 Esc 取消瞄准"));
	GuideRow(LOCTEXT("GuideCommandKeys", "右键 / G / R"), LOCTEXT("GuideCommandText", "统帅驻守指定位置 / 切换随军 / 战吼"));
	GuideRow(LOCTEXT("GuideCameraKeys", "A D / 左右键"), LOCTEXT("GuideCameraText", "平移镜头；滚轮缩放，也可点击小地图"));
	GuideRow(LOCTEXT("GuideFocusKeys", "空格或 H / C"), LOCTEXT("GuideFocusText", "镜头回到基地 / 聚焦统帅"));
	GuideRow(LOCTEXT("GuideLastStandKeys", "L"), LOCTEXT("GuideLastStandText", "满足条件时发动背水一战"));
	GuidePage->AddSlot().AutoHeight().Padding(0.f, 8.f, 0.f, 20.f)
	[ Label(LOCTEXT("GuideTip", "将鼠标停在战斗按钮上，可查看费用、效果和当前不可用的原因。"), 14) ];
	GuidePage->AddSlot().AutoHeight()[ Back() ];

	TSharedRef<SVerticalBox> CreditsPage = PageBox(EPage::Credits);
	CreditsPage->AddSlot().AutoHeight()
	[ Label(FText::FromString(TEXT("Titan\nLegionnaire (Original)\nJuggernaut\nMusic by Scott Buckley — CC BY 4.0\nwww.scottbuckley.com.au\ncreativecommons.org/licenses/by/4.0/"))) ];
	CreditsPage->AddSlot().AutoHeight().Padding(0.f, 12.f, 0.f, 0.f)
	[ Label(LOCTEXT("MusicModifications", "音乐已进行响度调整与格式转换；游戏中加入循环与淡入淡出。")) ];
	CreditsPage->AddSlot().AutoHeight().Padding(0.f, 20.f, 0.f, 0.f)
	[ Label(FText::FromString(TEXT("Fantasy UI Borders · Kenney · CC0\nkenney.nl/assets/fantasy-ui-borders"))) ];
	CreditsPage->AddSlot().AutoHeight().Padding(0.f, 16.f, 0.f, 0.f)
	[ Label(FText::FromString(TEXT("战斗采样：Sonniss GDC 2026\n344 Audio · Bass Drops & Downers Vol. 1\n344 Audio · Historical Weapons Vol. 2\nsonniss.com/gdc-bundle-license/"))) ];
	CreditsPage->AddSlot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)
	[ Label(LOCTEXT("FoleyModifications", "采样已裁切、调音及混合，其余短音效为本项目原创合成。完整来源与许可随游戏附带。")) ];
	CreditsPage->AddSlot().AutoHeight().Padding(0.f, 20.f, 0.f, 0.f)[ Back() ];

	TSharedRef<SHorizontalBox> EraButtons = SNew(SHorizontalBox);
	if (const UCWGameInstance* GI = GameInstance.Get())
	{
		if (const UCWGameDataSubsystem* Data = GI->GetSubsystem<UCWGameDataSubsystem>())
		{
			for (int32 Age = 0; Age < static_cast<int32>(Data->GetData().Ages.size()); ++Age)
			{
				if (!Data->GetData().Ages[Age].Implemented) continue;
				const FText AgeName = Data->GetAgeName(Age);
				EraButtons->AddSlot().FillWidth(1.f).Padding(Age == 0 ? 0.f : 6.f, 0.f, 0.f, 0.f)
				[
					SNew(SButton).ButtonStyle(&CWUI::ButtonStyle()).HAlign(HAlign_Center).VAlign(VAlign_Center)
					.OnClicked(this, &SCWMainMenu::OnPreviewAge, Age)
					.ToolTipText(FText::Format(LOCTEXT("EraPreviewTip", "预览{0}的基地与部队；不改变对局的起始时代。"), AgeName))
					[
						SNew(STextBlock).Font(CWUI::Font(14, true)).Justification(ETextJustify::Center)
						.Text_Lambda([this, Age, AgeName]() { return GetPreviewAge() == Age ? FText::Format(LOCTEXT("EraSelected", "[{0}]"), AgeName) : AgeName; })
						.ColorAndOpacity_Lambda([this, Age]() { return GetPreviewAge() == Age ? CWUI::Gold : CWUI::TextMain; })
					]
				];
			}
		}
	}

	ChildSlot
	[
		SNew(SOverlay)
		+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Fill).Padding(FMargin(32.f, 28.f, 0.f, 28.f))
		[
			SNew(SCWEpicFrame).BorderImage(CWUI::PanelBrush()).Padding(FMargin(32.f, 26.f)).IsEnabled(this, &SCWMainMenu::CanInteract)
			[
				SNew(SBox).WidthOverride_Lambda([this]() { return FOptionalSize(Page == EPage::Root ? 410.f : Page == EPage::Guide ? 520.f : 460.f); })
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock).Text(this, &SCWMainMenu::GetPageTitle).ColorAndOpacity(CWUI::TextMain)
						.Font_Lambda([this]() { return CWUI::Font(Page == EPage::Root ? 58 : 32, true); })
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 24.f)
					[ Label(TAttribute<FText>::CreateSP(this, &SCWMainMenu::GetPageDescription), 14) ]
					+ SVerticalBox::Slot().FillHeight(1.f)
					[
						SNew(SScrollBox)
						+ SScrollBox::Slot()
						[
							SNew(SVerticalBox)
							+ SVerticalBox::Slot().AutoHeight()[ RootPage ]
							+ SVerticalBox::Slot().AutoHeight()[ SinglePage ]
							+ SVerticalBox::Slot().AutoHeight()[ MultiPage ]
							+ SVerticalBox::Slot().AutoHeight()[ SettingsPage ]
							+ SVerticalBox::Slot().AutoHeight()[ GuidePage ]
							+ SVerticalBox::Slot().AutoHeight()[ CreditsPage ]
						]
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 20.f, 0.f, 0.f)
					[ Label(TAttribute<FText>::CreateLambda([this]() { return Page == EPage::Root ? LOCTEXT("Footer", "一条战线 · 五个时代 · 双方对抗") : LOCTEXT("SubpageFooter", "Esc 返回首页 · Tab 切换控件"); }), 13) ]
				]
			]
		]
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(FMargin(560.f, 0.f, 36.f, 38.f))
		[
			SNew(SCWEpicFrame).BorderImage(CWUI::PanelBrush()).Padding(FMargin(24.f, 20.f))
			.Visibility_Lambda([this]() { return PageVisibility(EPage::Root); }).IsEnabled(this, &SCWMainMenu::CanInteract)
			[
				SNew(SBox).WidthOverride(660.f)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[ SNew(STextBlock).Text(this, &SCWMainMenu::GetPreviewTitle).Font(CWUI::Font(26, true)).ColorAndOpacity(CWUI::TextMain) ]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 16.f)
					[ Label(TAttribute<FText>::CreateSP(this, &SCWMainMenu::GetPreviewUnits), 15) ]
					+ SVerticalBox::Slot().AutoHeight()[ EraButtons ]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 10.f, 0.f, 0.f)
					[ Label(LOCTEXT("EraPreviewOnly", "点击切换时代预览 · 对局始终从石器时代开始"), 13) ]
				]
			]
		]
		// The full viewport scrim consumes pointer input; the underlying controls
		// are disabled so keyboard navigation cannot re-enter a travel action.
		+ SOverlay::Slot()
		[
			SNew(SBorder).Visibility(this, &SCWMainMenu::GetConnectingVisibility).BorderImage(CWUI::WhiteBrush())
			.BorderBackgroundColor(FLinearColor(0.008f, 0.014f, 0.011f, 0.88f)).HAlign(HAlign_Center).VAlign(VAlign_Center)
			.OnMouseButtonDown_Lambda([](const FGeometry&, const FPointerEvent&) { return FReply::Handled(); })
			[
				SNew(SCWEpicFrame).BorderImage(CWUI::PanelBrush()).Padding(FMargin(36.f, 28.f))
				[
					SNew(SBox).WidthOverride(520.f)
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[ SNew(STextBlock).Text(this, &SCWMainMenu::GetConnectingText).Font(CWUI::Font(18, true)).ColorAndOpacity(CWUI::TextMain).AutoWrapText(true).Justification(ETextJustify::Center) ]
						+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 20.f, 0.f, 0.f)
						[
							SNew(SBox).Visibility_Lambda([this]() { const UCWGameInstance* GI = GameInstance.Get(); return GI && GI->IsConnecting() ? EVisibility::Visible : EVisibility::Collapsed; })
							[ CWUI::MakeButton(LOCTEXT("CancelJoin", "取消连接"), FOnClicked::CreateSP(this, &SCWMainMenu::OnCancelJoin), CWUI::EButtonKind::Danger, 180.f, true, LOCTEXT("CancelTip", "Esc 取消连接"), 16) ]
						]
					]
				]
			]
		]
	];
}
void SCWMainMenu::Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime)
{
	SCompoundWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);
	const UCWGameInstance* CurrentGI = GameInstance.Get();
	const ACWGameState* CurrentState = CurrentGI && CurrentGI->GetWorld() ? CurrentGI->GetWorld()->GetGameState<ACWGameState>() : nullptr;
	if (bNeedsInitialFocus && CurrentState && CurrentState->GetPhase() == ECWMatchPhase::Menu && FSlateApplication::IsInitialized())
	{
		bNeedsInitialFocus = false;
		FSlateApplication::Get().SetKeyboardFocus(SharedThis(this), EFocusCause::SetDirectly);
	}
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		if (GI->HasPendingError())
		{
			ErrorText = GI->ConsumePendingError();
			Page = EPage::Multi;
			if (AddressBox.IsValid() && FSlateApplication::IsInitialized())
				FSlateApplication::Get().SetKeyboardFocus(AddressBox, EFocusCause::SetDirectly);
		}
	}
#if WITH_EDITOR
	if (bConnectionReview && CurrentState && CurrentState->GetPhase() == ECWMatchPhase::Menu)
	{
		UCWGameInstance* GI = GameInstance.Get();
		const float WorldSeconds = GI && GI->GetWorld() ? GI->GetWorld()->GetTimeSeconds() : 0.f;
		if (ConnectionReviewStage == 0 && WorldSeconds >= 1.f && GI && AddressBox.IsValid())
		{
			ConnectionReviewStage = 1;
			AddressBox->SetText(FText::FromString(TEXT("127.0.0.1:17777")));
			OnJoin();
			const double ConnectStart = GI->GetConnectStartTime();
			FText SecondError;
			const bool bSecondAccepted = GI->JoinRoom(TEXT("127.0.0.1:17777"), SecondError);
			const bool bPassed = GI->IsConnecting() && !bSecondAccepted && !SecondError.IsEmpty()
				&& GI->GetConnectStartTime() == ConnectStart && !CanInteract()
				&& GetConnectingVisibility() == EVisibility::Visible;
			if (bPassed)
			{
				UE_LOG(LogTemp, Display, TEXT("CIVWAR_MENU_FLOW passed step=repeat_guard connecting=1 duplicate_rejected=1 timestamp_unchanged=1 modal=1"));
			}
			else
			{
				UE_LOG(LogTemp, Error, TEXT("CIVWAR_MENU_FLOW failed step=repeat_guard connecting=%d accepted_again=%d timestamp_unchanged=%d"),
					GI->IsConnecting(), bSecondAccepted, GI->GetConnectStartTime() == ConnectStart);
			}
		}
		else if (ConnectionReviewStage == 1 && WorldSeconds >= 10.f && GI && AddressBox.IsValid())
		{
			const FString AddressBefore = AddressBox->GetText().ToString();
			const FKeyEvent Escape(EKeys::Escape, FModifierKeysState(), 0, false, 0, 0);
			const FReply Reply = OnPreviewKeyDown(AllottedGeometry, Escape);
			const bool bAddressKept = AddressBox->GetText().ToString() == AddressBefore;
			const bool bPassed = Reply.IsEventHandled() && !GI->IsConnecting() && CanInteract()
				&& bAddressKept && Page == EPage::Multi && GetConnectingVisibility() == EVisibility::Collapsed;
			if (bPassed)
			{
				UE_LOG(LogTemp, Display, TEXT("CIVWAR_MENU_FLOW passed step=escape_recovery cancelled=1 address_kept=1 interactive=1"));
			}
			else
			{
				UE_LOG(LogTemp, Error, TEXT("CIVWAR_MENU_FLOW failed step=escape_recovery connecting=%d address_kept=%d interactive=%d"),
					GI->IsConnecting(), bAddressKept, CanInteract());
			}
			ConnectionRecoveryFrame = GFrameCounter;
			ConnectionReviewStage = 2;
		}
		else if (ConnectionReviewStage == 2 && GFrameCounter > ConnectionRecoveryFrame)
		{
			ConnectionReviewStage = 3;
			FString Prefix = TEXT("CivWar");
			FParse::Value(FCommandLine::Get(), TEXT("cwshotprefix="), Prefix);
			FScreenshotRequest::RequestScreenshot(Prefix + TEXT("_net_recovered.png"), true, false);
		}
	}
#endif
}

FReply SCWMainMenu::GoTo(EPage InPage)
{
	if (!CanInteract()) return FReply::Handled();
	CWAudio::SaveSettings();
	Page = InPage;
	return FReply::Handled().SetUserFocus(SharedThis(this), EFocusCause::SetDirectly);
}

bool SCWMainMenu::CanInteract() const
{
	const UCWGameInstance* GI = GameInstance.Get();
	return GI && !GI->IsTransitionPending();
}

FReply SCWMainMenu::OnPreviewKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	if (InKeyEvent.GetKey() == EKeys::Escape)
	{
		const UCWGameInstance* GI = GameInstance.Get();
		if (GI && GI->IsConnecting()) return OnCancelJoin();
		if (Page != EPage::Root) return GoTo(EPage::Root);
	}
	return SCompoundWidget::OnPreviewKeyDown(MyGeometry, InKeyEvent);
}

FText SCWMainMenu::GetPageTitle() const
{
	switch (Page)
	{
	case EPage::Single: return LOCTEXT("SingleTitle", "开始征战");
	case EPage::Multi: return LOCTEXT("MultiTitle", "联机对战");
	case EPage::Settings: return LOCTEXT("SettingsTitle", "画面与声音");
	case EPage::Credits: return LOCTEXT("CreditsTitle", "音乐与素材");
	case EPage::Guide: return LOCTEXT("GuideTitle", "操作指南");
	default: return LOCTEXT("GameTitle", "血战文明");
	}
}

FText SCWMainMenu::GetPageDescription() const
{
	switch (Page)
	{
	case EPage::Single: return LOCTEXT("SingleSubtitle", "选择难度，开始一场新的对局。");
	case EPage::Multi: return LOCTEXT("MultiSubtitle", "创建主机，或通过地址加入朋友。");
	case EPage::Settings: return LOCTEXT("SettingsSubtitle", "调好画面与混音，让指挥更从容。");
	case EPage::Credits: return LOCTEXT("CreditsSubtitle", "让这片战场有声有色的创作者。");
	case EPage::Guide: return LOCTEXT("GuideSubtitle", "鼠标完成指挥，快捷键让行动更快。");
	default: return LOCTEXT("GameSubtitle", "从第一柄石斧，到最后一道星火。");
	}
}

FReply SCWMainMenu::OnPreviewAge(int32 Age)
{
	if (!CanInteract()) return FReply::Handled();
	if (UCWGameInstance* GI = GameInstance.Get())
		if (ACWMenuShowcase* Showcase = ACWMenuShowcase::Get(GI->GetWorld())) Showcase->SetPreviewAge(Age);
	return FReply::Handled();
}

int32 SCWMainMenu::GetPreviewAge() const
{
	if (const UCWGameInstance* GI = GameInstance.Get())
		if (const ACWMenuShowcase* Showcase = ACWMenuShowcase::Get(GI->GetWorld())) return Showcase->GetPreviewAge();
	return 0;
}

FText SCWMainMenu::GetPreviewTitle() const
{
	if (const UCWGameInstance* GI = GameInstance.Get())
		if (const UCWGameDataSubsystem* Data = GI->GetSubsystem<UCWGameDataSubsystem>()) return Data->GetAgeName(GetPreviewAge());
	return LOCTEXT("PreviewLoading", "文明预览");
}

FText SCWMainMenu::GetPreviewUnits() const
{
	const UCWGameInstance* GI = GameInstance.Get();
	const UCWGameDataSubsystem* Data = GI ? GI->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!Data || !Data->IsLoaded()) return LOCTEXT("PreviewUnitsFallback", "基地与部队展示");
	const int32 Age = GetPreviewAge();
	const auto Army = Data->GetData().UnitsForAge(Age);
	const int32 Champion = Data->GetData().ChampionForAge(Age);
	TArray<FString> Names;
	if (!Army.empty()) Names.Add(Data->GetUnitName(Army[0]).ToString());
	if (Champion >= 0) Names.Add(Data->GetChampionName(Champion).ToString());
	if (Army.size() > 1) Names.Add(Data->GetUnitName(Army[1]).ToString());
	return FText::FromString(FString::Join(Names, TEXT("  ·  ")));
}

void SCWMainMenu::OnNameChanged(const FText& Text)
{
	if (NameBox.IsValid() && Text.ToString().Len() > 16)
		NameBox->SetText(FText::FromString(Text.ToString().Left(16)));
}

void SCWMainMenu::ApplyName()
{
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		if (NameBox.IsValid())
		{
			const FString Name = NameBox->GetText().ToString().TrimStartAndEnd().Left(16);
			GI->PlayerName = Name.IsEmpty() ? TEXT("玩家") : Name;
		}
	}
}

FReply SCWMainMenu::OnSingle(int32 Difficulty)
{
	if (!CanInteract()) return FReply::Handled();
	CWAudio::SaveSettings();
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		ErrorText = FText::GetEmpty();
		GI->StartSinglePlayer(Difficulty);
	}
	return FReply::Handled();
}

FReply SCWMainMenu::OnHost()
{
	if (!CanInteract()) return FReply::Handled();
	CWAudio::SaveSettings();
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		ApplyName();
		ErrorText = FText::GetEmpty();
		GI->HostRoom();
	}
	return FReply::Handled();
}

FReply SCWMainMenu::OnJoin()
{
	if (!CanInteract()) return FReply::Handled();
#if WITH_EDITOR
	if (!bConnectionReview)
#endif
	CWAudio::SaveSettings();
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		ApplyName();
		FText Error;
		if (!GI->JoinRoom(AddressBox.IsValid() ? AddressBox->GetText().ToString() : FString(), Error))
		{
			ErrorText = Error;
		}
		else
		{
			ErrorText = FText::GetEmpty();
		}
	}
	return FReply::Handled().SetUserFocus(SharedThis(this), EFocusCause::SetDirectly);
}

FReply SCWMainMenu::OnCancelJoin()
{
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		GI->CancelJoin();
	}
	return AddressBox.IsValid() ? FReply::Handled().SetUserFocus(AddressBox.ToSharedRef(), EFocusCause::SetDirectly) : FReply::Handled();
}

EVisibility SCWMainMenu::GetConnectingVisibility() const
{
	const UCWGameInstance* GI = GameInstance.Get();
	return GI && GI->IsTransitionPending() ? EVisibility::Visible : EVisibility::Collapsed;
}

FText SCWMainMenu::GetConnectingText() const
{
	const UCWGameInstance* GI = GameInstance.Get();
	if (!GI)
	{
		return FText::GetEmpty();
	}
	if (!GI->IsConnecting()) return LOCTEXT("EnteringMatch", "正在准备战场…\n请稍候");
	const int32 Seconds = FMath::FloorToInt(static_cast<float>(FPlatformTime::Seconds() - GI->GetConnectStartTime()));
	return FText::Format(LOCTEXT("Connecting", "正在连接 {0}\n已等待 {1} 秒 · Esc 可取消\n请检查地址、防火墙与 UDP 端口。"),
		FText::FromString(GI->GetJoinAddress()), FText::AsNumber(Seconds));
}

FReply SCWMainMenu::OnQuality(int32 Level)
{
	if (UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr)
	{
		Settings->SetOverallScalabilityLevel(Level);
		Settings->ApplySettings(false);
	}
	return FReply::Handled();
}

FReply SCWMainMenu::OnWindowMode(bool bFullscreen)
{
	if (UGameUserSettings* Settings = GEngine ? GEngine->GetGameUserSettings() : nullptr)
	{
		Settings->SetFullscreenMode(bFullscreen ? EWindowMode::WindowedFullscreen : EWindowMode::Windowed);
		Settings->ApplySettings(false);
	}
	return FReply::Handled();
}

FReply SCWMainMenu::OnQuit()
{
	CWAudio::SaveSettings();
	if (UCWGameInstance* GI = GameInstance.Get())
	{
		UKismetSystemLibrary::QuitGame(GI->GetWorld(), GI->GetFirstLocalPlayerController(), EQuitPreference::Quit, false);
	}
	return FReply::Handled();
}

// ---------------------------------------------------------------------------
// 房间
// ---------------------------------------------------------------------------
void SCWLobby::Construct(const FArguments& InArgs)
{
	Controller = InArgs._Controller;
	ChildSlot
	[
		SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		[
			SNew(SCWEpicFrame)
			.BorderImage(CWUI::PanelBrush())
			.Padding(FMargin(40.f, 30.f))
			[
				SNew(SBox)
				.WidthOverride(760.f)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(STextBlock).Text(LOCTEXT("Room", "对战房间")).Font(CWUI::Font(34, true)).ColorAndOpacity(CWUI::TextMain)
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 6.f, 0.f, 22.f)
					[
						SNew(STextBlock).Text(this, &SCWLobby::GetHeaderText).Font(CWUI::Font(16)).ColorAndOpacity(CWUI::TextDim)
						.Justification(ETextJustify::Center).AutoWrapText(true)
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 10.f, 0.f)
						[
							MakeSlotCard(0)
						]
						+ SHorizontalBox::Slot().FillWidth(1.f).Padding(10.f, 0.f, 0.f, 0.f)
						[
							MakeSlotCard(1)
						]
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 22.f, 0.f, 6.f)
					[
						SNew(STextBlock).Text(this, &SCWLobby::GetCountdownText).Font(CWUI::Font(22, true)).ColorAndOpacity(CWUI::Gold)
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 0.f, 0.f, 16.f)
					[
						SNew(STextBlock).Text(this, &SCWLobby::GetStatusText).Font(CWUI::Font(16)).ColorAndOpacity(CWUI::Warning).AutoWrapText(true).Justification(ETextJustify::Center)
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().Padding(8.f, 0.f)
						[
							CWUI::MakeButton(TAttribute<FText>::Create(TAttribute<FText>::FGetter::CreateSP(this, &SCWLobby::GetReadyLabel)),
								FOnClicked::CreateSP(this, &SCWLobby::OnToggleReady),
								CWUI::EButtonKind::Primary, 220.f)
						]
						+ SHorizontalBox::Slot().AutoWidth().Padding(8.f, 0.f)
						[
							CWUI::MakeButton(LOCTEXT("Leave", "离开房间"), FOnClicked::CreateSP(this, &SCWLobby::OnLeave), CWUI::EButtonKind::Danger, 220.f)
						]
						+ SHorizontalBox::Slot().AutoWidth().Padding(8.f, 0.f)
						[
							CWUI::MakeButton(LOCTEXT("RoomSound", "声音设置"), FOnClicked::CreateSP(this, &SCWLobby::OnAudioSettings), CWUI::EButtonKind::Normal, 160.f, true, LOCTEXT("RoomSoundTip", "Esc 也可打开声音设置"), 16)
						]
					]
				]
			]
		]
	];
}

TSharedRef<SWidget> SCWLobby::MakeSlotCard(int32 Team)
{
	return SNew(SBorder)
		.BorderImage(CWUI::PanelLightBrush())
		.Padding(FMargin(20.f, 16.f))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(STextBlock)
				.Text(Team == 0 ? LOCTEXT("TeamBlue", "蓝方（主机）") : LOCTEXT("TeamRed", "红方"))
				.Font(CWUI::Font(16, true))
				.ColorAndOpacity(CWUI::TeamColor(Team))
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 8.f)
			[
				SNew(STextBlock).Text_Lambda([this, Team]() { return GetSlotName(Team); }).Font(CWUI::Font(22, true)).ColorAndOpacity(CWUI::TextMain).AutoWrapText(true)
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(STextBlock)
				.Text_Lambda([this, Team]() { return GetSlotStatus(Team); })
				.Font(CWUI::Font(16))
				.ColorAndOpacity_Lambda([this, Team]() { return GetSlotStatusColor(Team); })
			]
		];
}

FText SCWLobby::GetHeaderText() const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	if (!State)
	{
		return LOCTEXT("Syncing", "正在同步房间信息…");
	}
	if (PC->HasAuthority())
	{
		return FText::Format(LOCTEXT("HostHeader", "房间已创建。对方在“加入房间”中输入：{0}\n（本机测试可输入 127.0.0.1）"), FText::FromString(State->HostAddress));
	}
	return FText::Format(LOCTEXT("ClientHeader", "已加入房间 {0}"), FText::FromString(State->HostAddress));
}

FText SCWLobby::GetSlotName(int32 Team) const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	if (!State || !State->GetLobbySlots().IsValidIndex(Team) || !State->GetLobbySlots()[Team].bOccupied)
	{
		return LOCTEXT("Waiting", "等待玩家加入…");
	}
	const FString Name = State->GetLobbySlots()[Team].Name;
	return PC->GetTeam() == Team ? FText::Format(LOCTEXT("You", "{0}（你）"), FText::FromString(Name)) : FText::FromString(Name);
}

FText SCWLobby::GetSlotStatus(int32 Team) const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	if (!State || !State->GetLobbySlots().IsValidIndex(Team) || !State->GetLobbySlots()[Team].bOccupied)
	{
		return LOCTEXT("Empty", "空位");
	}
	return State->GetLobbySlots()[Team].bReady ? LOCTEXT("Ready", "已准备") : LOCTEXT("NotReady", "未准备");
}

FSlateColor SCWLobby::GetSlotStatusColor(int32 Team) const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	const bool bReady = State && State->GetLobbySlots().IsValidIndex(Team) && State->GetLobbySlots()[Team].bReady;
	return FSlateColor(bReady ? CWUI::Good : CWUI::TextDim);
}

bool SCWLobby::IsLocalReady() const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWPlayerState* PS = PC ? PC->GetPlayerState<ACWPlayerState>() : nullptr;
	return PS && PS->IsReady();
}

FText SCWLobby::GetReadyLabel() const
{
	return IsLocalReady() ? LOCTEXT("Unready", "取消准备") : LOCTEXT("ReadyBtn", "准备");
}

FText SCWLobby::GetStatusText() const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	return State ? FText::FromString(State->GetStatusMessage()) : FText::GetEmpty();
}

FText SCWLobby::GetCountdownText() const
{
	const ACWPlayerController* PC = Controller.Get();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	if (State && State->GetPhase() == ECWMatchPhase::Countdown)
	{
		return FText::Format(LOCTEXT("Countdown", "双方已准备，{0} 秒后开战"), FText::AsNumber(FMath::CeilToInt(State->GetPhaseTimeLeft())));
	}
	return LOCTEXT("NeedReady", "双方都准备后开始对局");
}

FReply SCWLobby::OnToggleReady()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->ServerSetReady(!IsLocalReady());
	}
	return FReply::Handled();
}

FReply SCWLobby::OnLeave()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		if (ACWHUD* HUD = Cast<ACWHUD>(PC->GetHUD())) HUD->RequestLeaveMatch();
	}
	return FReply::Handled();
}

FReply SCWLobby::OnAudioSettings()
{
	if (ACWPlayerController* PC = Controller.Get())
		if (ACWHUD* HUD = Cast<ACWHUD>(PC->GetHUD())) HUD->ToggleFrontendMenu();
	return FReply::Handled();
}

FReply SCWLobby::OnPreviewKeyDown(const FGeometry& MyGeometry, const FKeyEvent& InKeyEvent)
{
	if (InKeyEvent.GetKey() == EKeys::Escape) return OnAudioSettings();
	return SCompoundWidget::OnPreviewKeyDown(MyGeometry, InKeyEvent);
}

#undef LOCTEXT_NAMESPACE
