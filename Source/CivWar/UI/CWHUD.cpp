#include "UI/CWHUD.h"

#include "CivWar.h"
#include "Data/CWGameDataSubsystem.h"
#include "Engine/Canvas.h"
#include "Engine/DirectionalLight.h"
#include "EngineUtils.h"
#include "Camera/PlayerCameraManager.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Game/CWGameInstance.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Net/CWBattleReplicator.h"
#include "UnrealClient.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "UI/CWUIStyle.h"
#include "UI/CWFrontendFlow.h"
#include "UI/CWUIText.h"
#include "UI/SCWBattleHud.h"
#include "UI/SCWMenus.h"
#include "UI/SCWAudioSettings.h"
#include "UI/SCWEpicFrame.h"
#include "View/CWAudio.h"
#include "View/CWBattlefield.h"
#include "View/CWBattleView.h"
#include "View/CWCameraRig.h"
#include "View/CWUnitVisual.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/SBoxPanel.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerInput.h"
#include "InputCoreTypes.h"
#include "Widgets/SOverlay.h"
#include "Widgets/SWeakWidget.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CivWarUI"

namespace
{
// Child controls keep normal Slate focus; every unhandled input stops at this
// full-viewport boundary instead of reaching the live battlefield below it.
class SCWFrontendModal : public SBorder
{
public:
	void Construct(const SBorder::FArguments& Args, TFunction<void()> InBack)
	{
		Back = MoveTemp(InBack);
		SBorder::Construct(Args);
	}
	virtual bool SupportsKeyboardFocus() const override { return true; }
	virtual FReply OnPreviewKeyDown(const FGeometry&, const FKeyEvent& Event) override
	{
		if (Event.GetKey() == EKeys::Escape) { Back(); return FReply::Handled(); }
		return FReply::Unhandled();
	}
	virtual FReply OnKeyDown(const FGeometry&, const FKeyEvent&) override { return FReply::Handled(); }
	virtual FReply OnMouseButtonDown(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
	virtual FReply OnMouseButtonUp(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
	virtual FReply OnMouseWheel(const FGeometry&, const FPointerEvent&) override { return FReply::Handled(); }
private:
	TFunction<void()> Back;
};
}

ACWHUD::ACWHUD()
{
	PrimaryActorTick.bCanEverTick = true;
}

void ACWHUD::BeginPlay()
{
	Super::BeginPlay();
	UCWGameInstance* GI = GetGameInstance<UCWGameInstance>();
	const UCWGameDataSubsystem* DataSys = GI ? GI->GetSubsystem<UCWGameDataSubsystem>() : nullptr;

	// 战场表现只在本地生成
	FActorSpawnParameters Params;
	Params.Owner = this;
	Battlefield = GetWorld()->SpawnActor<ACWBattlefield>(Params);
	if (Battlefield && DataSys && DataSys->IsLoaded())
	{
		Battlefield->Build(DataSys->GetData().Rules.LaneLength, DataSys->GetData().Rules.BaseHalfWidth);
	}
	else if (Battlefield)
	{
		Battlefield->Build(6000.f, 300.f);
	}
	BattleView = GetWorld()->SpawnActor<ACWBattleView>(Params);

	if (GI && DataSys && !DataSys->IsLoaded())
	{
		GI->SetPendingError(FText::Format(LOCTEXT("DataError", "数据加载失败：{0}"), FText::FromString(DataSys->GetLoadError())));
	}
	bPerfLog = FParse::Param(FCommandLine::Get(), TEXT("cwperf"));
	bAutoShots = FParse::Param(FCommandLine::Get(), TEXT("cwshots"));
	FParse::Value(FCommandLine::Get(), TEXT("cwshotprefix="), ShotPrefix);
	FParse::Value(FCommandLine::Get(), TEXT("cwquitafter="), QuitAfterSeconds);
#if WITH_EDITOR
	if (bAutoShots) FParse::Value(FCommandLine::Get(), TEXT("cwreviewduration="), ReviewWorldDuration);
#endif
	PerfWindowStart = FPlatformTime::Seconds();
	CreateWidgets();
}

void ACWHUD::UpdateAutomationShots()
{
#if WITH_EDITOR
	// A cold asset load must not consume the time reserved for rendered checks.
	if (ReviewWorldDuration > 0.f && GetWorld()->GetTimeSeconds() >= ReviewWorldDuration)
	{
		ReviewWorldDuration = 0.f;
		if (APlayerController* PC = GetOwningPlayerController()) PC->ConsoleCommand(TEXT("quit"));
		return;
	}
#endif
	const float AppTime = static_cast<float>(FPlatformTime::Seconds() - GStartTime);
	if (QuitAfterSeconds > 0.f && AppTime > QuitAfterSeconds)
	{
		QuitAfterSeconds = 0.f;
		if (APlayerController* PC = GetOwningPlayerController())
		{
			PC->ConsoleCommand(TEXT("quit"));
		}
		return;
	}
	if (!bAutoShots)
	{
		return;
	}
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	if (!State)
	{
		return;
	}
	FString Name;
	switch (State->GetPhase())
	{
	case ECWMatchPhase::Menu:
		if (GetWorld()->GetTimeSeconds() > 6.0)
		{
			Name = TEXT("menu");
		}
		break;
	case ECWMatchPhase::Lobby:
		if (GetWorld()->GetTimeSeconds() > 4.0)
		{
			Name = TEXT("lobby");
		}
		break;
	case ECWMatchPhase::InMatch:
	{
		ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
		ACWCameraRig* Rig = PC && !IsFrontendMenuOpen() ? PC->GetCameraRig() : nullptr;
		const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
		const float Lane = DataSys && DataSys->IsLoaded() ? DataSys->GetData().Rules.LaneLength : 6000.f;
		const int32 MyTeam = PC ? FMath::Max(PC->GetTeam(), 0) : 0;
		// 时代变化：依次拍摄该阵营基地与当前前线
		for (int32 Team = 0; Team < 2; ++Team)
		{
			const int32 Age = State->GetTeam(Team).Age;
			if (Age != ShotSeenAge[Team])
			{
				if (ShotSeenAge[Team] >= 0 || Age > 0)
				{
					const TCHAR* Side = Team == MyTeam ? TEXT("own") : TEXT("enemy");
					PendingShots.Add({ FString::Printf(TEXT("age%d_%s_base"), Age, Side), Team == 0 ? 0.f : Lane });
					PendingShots.Add({ FString::Printf(TEXT("age%d_%s_front"), Age, Side), -1.f });
				}
				ShotSeenAge[Team] = Age;
			}
		}
		// 背水一战：按钮出现时、发动后各截一张（镜头对准己方城门）
		{
			const FCWTeamNetState& Mine = State->GetTeam(MyTeam);
			const UCWGameDataSubsystem* ShotData = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
			const bool bReady = ShotData && ShotData->IsLoaded() && !Mine.bLastStandUsed && Mine.BaseMaxHp > 0.f
				&& Mine.BaseHp <= Mine.BaseMaxHp * ShotData->GetData().Rules.LastStandBaseHpRatio;
			const float HomeX = MyTeam == 0 ? 900.f : Lane - 900.f;
			if (bReady && !ShotsQueued.Contains(TEXT("laststand_ready")))
			{
				ShotsQueued.Add(TEXT("laststand_ready"));
				PendingShots.Add({ TEXT("laststand_ready"), HomeX });
			}
			if (Mine.bLastStandUsed && !ShotsQueued.Contains(TEXT("laststand_used")))
			{
				ShotsQueued.Add(TEXT("laststand_used"));
				// 特效持续时间短：插到下一张，避免排在其他截图后面
				PendingShots.Insert({ TEXT("laststand_used"), HomeX }, PendingShots.Num() > 0 ? 1 : 0);
			}
		}
		static const TArray<int32> ShotTimes = []
		{
			TArray<int32> Times = { 8, 45, 120, 240, 420, 600, 780, 960, 1140 };
			int32 FixtureAge = -1;
			if (FParse::Value(FCommandLine::Get(), TEXT("cwerafixture="), FixtureAge) && FixtureAge >= 1 && FixtureAge <= 4)
			{
				Times.Insert(18, 1);
				Times.Insert(26, 2);
				Times.Insert(35, 3);
			}
			return Times;
		}();
		for (const int32 T : ShotTimes)
		{
			const FString TimedName = FString::Printf(TEXT("match_%03d"), T);
			if (State->GetMatchTime() >= static_cast<float>(T) && !ShotsQueued.Contains(TimedName))
			{
				ShotsQueued.Add(TimedName);
				PendingShots.Add({ TimedName, -1.f });
			}
		}
		if (PendingShots.Num() > 0)
		{
			FPendingShot& Shot = PendingShots[0];
			const double Now = FPlatformTime::Seconds();
			if (Shot.ShootAt < 0.0)
			{
				// 先瞬移镜头，等画面稳定后再截图（-1 表示拍摄前线）
				if (Rig)
				{
					Rig->FocusX(Shot.FocusX >= 0.f ? Shot.FocusX : FrontLineX(), true);
				}
				Shot.ShootAt = Now + 0.6;
			}
			else if (Now >= Shot.ShootAt)
			{
				Name = Shot.Name;
				PendingShots.RemoveAt(0);
			}
		}
		else if (Rig)
		{
			Rig->FocusX(FrontLineX());
		}
		break;
	}
	case ECWMatchPhase::PostMatch:
		Name = TEXT("result");
		break;
	default:
		break;
	}
	if (!Name.IsEmpty() && !ShotsTaken.Contains(Name))
	{
		ShotsTaken.Add(Name);
		// bShowUI = true：截图包含 Slate 界面；文件保存在 Saved/Screenshots/ 下
		FScreenshotRequest::RequestScreenshot(FString::Printf(TEXT("%s_%s.png"), *ShotPrefix, *Name), true, false);
		UE_LOG(LogCivWar, Display, TEXT("CIVWAR_SHOT %s"), *Name);
	}
}

float ACWHUD::FrontLineX() const
{
	// 双方最靠前单位的中点；只有一方有单位时取该方最前者；都没有时取车道中央
	const ACWGameState* State = GetWorld()->GetGameState<ACWGameState>();
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	const float Lane = DataSys && DataSys->IsLoaded() ? DataSys->GetData().Rules.LaneLength : 6000.f;
	const ACWBattleReplicator* Rep = State ? State->GetReplicator() : nullptr;
	if (!Rep)
	{
		return Lane * 0.5f;
	}
	float Front[2] = { -1.f, -1.f };
	bool bHas[2] = { false, false };
	for (const FCWUnitNetItem& U : Rep->GetUnits().Items)
	{
		const int32 T = U.Team == 1 ? 1 : 0;
		if (!bHas[T] || (T == 0 ? U.X > Front[T] : U.X < Front[T]))
		{
			Front[T] = U.X;
			bHas[T] = true;
		}
	}
	if (bHas[0] && bHas[1])
	{
		return (Front[0] + Front[1]) * 0.5f;
	}
	return bHas[0] ? Front[0] : (bHas[1] ? Front[1] : Lane * 0.5f);
}

void ACWHUD::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (ViewportWidget.IsValid())
	{
		if (UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr)
		{
			Viewport->RemoveViewportWidgetContent(ViewportWidget.ToSharedRef());
		}
	}
	ViewportWidget.Reset();
	FrontendOverlay.Reset();
	RootWidget.Reset();
	BattleHud.Reset();
	if (BattleView)
	{
		BattleView->Destroy();
	}
	if (Battlefield)
	{
		Battlefield->Destroy();
	}
	Super::EndPlay(EndPlayReason);
}

void ACWHUD::CreateWidgets()
{
	UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
	ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
	if (!Viewport || !PC)
	{
		return;
	}
	TWeakObjectPtr<ACWPlayerController> WeakPC(PC);
	TWeakObjectPtr<UCWGameInstance> WeakGI(GetGameInstance<UCWGameInstance>());
	auto PhaseIs = [WeakPC](TFunction<bool(const ACWGameState&)> Pred)
	{
		return [WeakPC, Pred]()
		{
			const ACWPlayerController* P = WeakPC.Get();
			const ACWGameState* G = P ? P->GetCWGameState() : nullptr;
			return G && Pred(*G) ? EVisibility::SelfHitTestInvisible : EVisibility::Collapsed;
		};
	};

	SAssignNew(BattleHud, SCWBattleHud).Controller(WeakPC);
	FrontendOverlay = MakeFrontendOverlay();
	RootWidget = SNew(SOverlay)
		+ SOverlay::Slot()
		[
			SNew(SBox)
			.Visibility_Lambda(PhaseIs([](const ACWGameState& G) { return G.GetPhase() == ECWMatchPhase::Menu; }))
			[
				SNew(SCWMainMenu).GameInstance(WeakGI)
			]
		]
		+ SOverlay::Slot()
		[
			SNew(SBox)
			.Visibility_Lambda(PhaseIs([](const ACWGameState& G)
			{
				return G.GetPhase() == ECWMatchPhase::Lobby || (G.GetPhase() == ECWMatchPhase::Countdown && !G.bSinglePlayer);
			}))
			[
				SNew(SCWLobby).Controller(WeakPC)
			]
		]
		+ SOverlay::Slot()
		[
			SNew(SBox)
			.Visibility_Lambda(PhaseIs([](const ACWGameState& G)
			{
				return G.GetPhase() == ECWMatchPhase::InMatch || G.GetPhase() == ECWMatchPhase::PostMatch
					|| (G.GetPhase() == ECWMatchPhase::Countdown && G.bSinglePlayer);
			}))
			[
				BattleHud.ToSharedRef()
			]
		]
		// 尚未收到服务器状态
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			SNew(STextBlock)
			.Text(LOCTEXT("Loading", "正在进入…"))
			.Font(CWUI::Font(24, true, true))
			.ColorAndOpacity(CWUI::TextMain)
			.Visibility_Lambda([WeakPC]()
			{
				const ACWPlayerController* P = WeakPC.Get();
				return P && P->GetCWGameState() ? EVisibility::Collapsed : EVisibility::HitTestInvisible;
			})
		]
		+ SOverlay::Slot()
		[
			FrontendOverlay.ToSharedRef()
		];

	ViewportWidget = SNew(SWeakWidget).PossiblyNullContent(RootWidget);
	Viewport->AddViewportWidgetContent(ViewportWidget.ToSharedRef(), 10);
}

TSharedRef<SWidget> ACWHUD::MakeFrontendOverlay()
{
	return SNew(SCWFrontendModal, [this]() { HandleFrontendBack(); })
		.BorderImage(CWUI::WhiteBrush())
		.BorderBackgroundColor(FLinearColor(0.008f, 0.015f, 0.013f, 0.84f))
		.Padding(24.f)
		.HAlign(HAlign_Center).VAlign(VAlign_Center)
		.Visibility_Lambda([this]() { return IsFrontendMenuOpen() ? EVisibility::Visible : EVisibility::Collapsed; })
		[
			SNew(SCWEpicFrame)
			.BorderImage(CWUI::PanelBrush()).Padding(24.f)
			[
				SNew(SBox).WidthOverride(560.f).MaxDesiredHeight(620.f)
				[
					SNew(SScrollBox)
					+ SScrollBox::Slot()
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[
							SNew(STextBlock).Font(CWUI::Font(28, true)).ColorAndOpacity(CWUI::TextMain)
							.Text_Lambda([this]() { return bConfirmLeave ? LOCTEXT("ConfirmLeaveTitle", "返回主菜单？") : LOCTEXT("BattleSettingsTitle", "声音与战局"); })
						]
						+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 8.f, 0.f, 22.f)
						[
							SNew(STextBlock).Font(CWUI::Font(14)).ColorAndOpacity(CWUI::TextDim).AutoWrapText(true)
							.Text_Lambda([this]()
							{
								const ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
								const ACWGameState* G = PC ? PC->GetCWGameState() : nullptr;
								if (bConfirmLeave)
								{
									if (G && !G->bSinglePlayer && PC->HasAuthority())
										return LOCTEXT("LeaveHostWarning", "你是房主。返回主菜单会关闭房间，其他玩家将断开连接。当前对局不会保存。");
									if (G && G->GetPhase() == ECWMatchPhase::Lobby)
										return LOCTEXT("LeaveLobbyWarning", "你将离开当前房间，返回主菜单。也可以取消并继续等待。");
									if (G && G->GetPhase() == ECWMatchPhase::PostMatch)
										return LOCTEXT("LeaveResultWarning", "本局已结束。返回主菜单后，可以重新发起对局。");
									return G && !G->bSinglePlayer
										? LOCTEXT("LeaveClientWarning", "中途退出联机对局将判负，当前对局不会保存。")
										: LOCTEXT("LeaveSingleWarning", "当前对局不会保存。你可以取消并继续战斗。");
								}
								if (G && G->GetPhase() == ECWMatchPhase::PostMatch)
									return LOCTEXT("SettingsResult", "本局已结束。你可以调整下一局的音量，设置会自动保存。");
								return G && (G->GetPhase() == ECWMatchPhase::InMatch || G->GetPhase() == ECWMatchPhase::Countdown)
									? LOCTEXT("SettingsBattleLive", "对局仍在继续。设置期间作战按键与镜头输入已锁定，音量自动保存。")
									: LOCTEXT("SettingsLobbyLive", "房间保持连接，准备状态不变。音量设置自动保存。");
							})
						]
						+ SVerticalBox::Slot().AutoHeight()
						[
							SNew(SBox).Visibility_Lambda([this]() { return !bConfirmLeave ? EVisibility::Visible : EVisibility::Collapsed; })
							[
								SNew(SVerticalBox)
								+ SVerticalBox::Slot().AutoHeight()[SNew(SCWAudioSettings)]
								+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 22.f, 0.f, 0.f)
								[
									SNew(SHorizontalBox)
									+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 12.f, 0.f)
									[
										CWUI::MakeButton(TAttribute<FText>::CreateLambda([this]()
										{
											const ACWGameState* G = GetWorld() ? GetWorld()->GetGameState<ACWGameState>() : nullptr;
											return G && G->GetPhase() == ECWMatchPhase::Lobby ? LOCTEXT("ReturnRoom", "返回房间  Esc") : LOCTEXT("ResumeBattle", "返回战局  Esc");
										}), FOnClicked::CreateLambda([this]() { CloseFrontendMenu(); return FReply::Handled(); }), CWUI::EButtonKind::Primary, 250.f, true, FText::GetEmpty(), 16)
									]
									+ SHorizontalBox::Slot().FillWidth(1.f)
									[
										CWUI::MakeButton(LOCTEXT("LeaveToMenu", "返回主菜单"), FOnClicked::CreateLambda([this]() { RequestLeaveMatch(); return FReply::Handled(); }), CWUI::EButtonKind::Normal, 250.f, true, FText::GetEmpty(), 16)
									]
								]
							]
						]
						+ SVerticalBox::Slot().AutoHeight()
						[
							SNew(SHorizontalBox).Visibility_Lambda([this]() { return bConfirmLeave ? EVisibility::Visible : EVisibility::Collapsed; })
							+ SHorizontalBox::Slot().FillWidth(1.f).Padding(0.f, 0.f, 12.f, 0.f)
							[
								CWUI::MakeButton(LOCTEXT("CancelLeave", "取消并返回  Esc"), FOnClicked::CreateLambda([this]() { CloseFrontendMenu(); return FReply::Handled(); }), CWUI::EButtonKind::Primary, 250.f, true, FText::GetEmpty(), 16)
							]
							+ SHorizontalBox::Slot().FillWidth(1.f)
							[
								CWUI::MakeButton(LOCTEXT("ConfirmLeave", "确认返回主菜单"), FOnClicked::CreateLambda([this]()
								{
									CWAudio::SaveSettings();
									if (UCWGameInstance* GI = GetGameInstance<UCWGameInstance>()) GI->OpenMainMenu();
									return FReply::Handled();
								}), CWUI::EButtonKind::Danger, 250.f, true, FText::GetEmpty(), 16)
							]
						]
					]
				]
			]
		];
}

void ACWHUD::SetFrontendMenuOpen(bool bOpen)
{
	bFrontendMenuOpen = bOpen;
	if (ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController()))
	{
		PC->CancelSkillTargeting();
		if (PC->PlayerInput) PC->PlayerInput->FlushPressedKeys();
		if (ACWCameraRig* Rig = PC->GetCameraRig()) Rig->StopManualMovement();
	}
	if (BattleHud) BattleHud->CloseBuildMenu();
	if (bOpen && FrontendOverlay && FSlateApplication::IsInitialized())
		FSlateApplication::Get().SetKeyboardFocus(FrontendOverlay, EFocusCause::SetDirectly);
	else if (!bOpen && FSlateApplication::IsInitialized())
		FSlateApplication::Get().SetAllUserFocusToGameViewport();
}

void ACWHUD::CloseFrontendMenu()
{
	bConfirmLeave = false;
#if WITH_EDITOR
	if (!bFrontendFlowChecking)
#endif
	CWAudio::SaveSettings();
	SetFrontendMenuOpen(false);
}

void ACWHUD::ToggleFrontendMenu()
{
	if (IsFrontendMenuOpen()) { CloseFrontendMenu(); return; }
	const ACWGameState* G = GetWorld() ? GetWorld()->GetGameState<ACWGameState>() : nullptr;
	if (G && G->GetPhase() != ECWMatchPhase::Menu) SetFrontendMenuOpen(true);
}

void ACWHUD::RequestLeaveMatch()
{
	SetFrontendMenuOpen(true);
	bConfirmLeave = true;
}

void ACWHUD::HandleFrontendBack()
{
	ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
	const ACWGameState* G = PC ? PC->GetCWGameState() : nullptr;
	if (!PC || !G) return;
	switch (CWFrontend::ResolveBack(PC->IsSkillTargeting(), BattleHud && BattleHud->IsBuildMenuOpen(), IsFrontendMenuOpen(), G->GetPhase()))
	{
	case CWFrontend::EBackAction::CancelSkill: PC->CancelSkillTargeting(); break;
	case CWFrontend::EBackAction::CloseBuildMenu: BattleHud->CloseBuildMenu(); break;
	case CWFrontend::EBackAction::CloseOverlay: CloseFrontendMenu(); break;
	case CWFrontend::EBackAction::OpenOverlay: SetFrontendMenuOpen(true); break;
	default: break;
	}
}

void ACWHUD::HandleCommandRejected(uint8 Type, uint8 Result)
{
	if (BattleHud.IsValid())
	{
		BattleHud->ShowToast(CWUIText::CommandResult(Result), true);
	}
	CWAudio::Play2D(this, CWAudio::ESound::UIError, 0.6f);
}

void ACWHUD::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	UpdateAutomationShots();
	if (bPerfLog)
	{
		if (!bLightLogged && GetWorld()->GetTimeSeconds() > 3.0)
		{
			// 诊断：记录实际生效的平行光朝向与镜头位置，用于核对“光从镜头一侧照来”
			bLightLogged = true;
			for (TActorIterator<ADirectionalLight> It(GetWorld()); It; ++It)
			{
				const FVector F = It->GetActorForwardVector();
				UE_LOG(LogCivWar, Display, TEXT("CIVWAR_LIGHT %s rot=%s fwd=(%.2f,%.2f,%.2f)"), *It->GetName(), *It->GetActorRotation().ToString(), F.X, F.Y, F.Z);
			}
			if (const APlayerController* LightPC = GetOwningPlayerController())
			{
				if (LightPC->PlayerCameraManager)
				{
					UE_LOG(LogCivWar, Display, TEXT("CIVWAR_CAMERA loc=%s rot=%s"), *LightPC->PlayerCameraManager->GetCameraLocation().ToString(),
						*LightPC->PlayerCameraManager->GetCameraRotation().ToString());
				}
			}
		}
		++PerfFrames;
		PerfWorstFrame = FMath::Max(PerfWorstFrame, static_cast<float>(FApp::GetDeltaTime() * 1000.0));
		const double Now = FPlatformTime::Seconds();
		if (Now - PerfWindowStart >= 5.0)
		{
			const double Elapsed = Now - PerfWindowStart;
			const ACWGameState* PerfState = GetWorld()->GetGameState<ACWGameState>();
			FVector2D ViewportSize = FVector2D::ZeroVector;
			if (GEngine && GEngine->GameViewport)
			{
				GEngine->GameViewport->GetViewportSize(ViewportSize);
			}
			UE_LOG(LogCivWar, Display, TEXT("CIVWAR_PERF t=%.0f fps=%.1f avgms=%.2f worstms=%.1f units=%d projectiles=%d res=%dx%d"),
				PerfState ? PerfState->GetMatchTime() : 0.f, PerfFrames / Elapsed, Elapsed * 1000.0 / FMath::Max(PerfFrames, 1), PerfWorstFrame,
				BattleView ? BattleView->GetUnitVisuals().Num() : 0, BattleView ? BattleView->GetActiveProjectileCount() : 0,
				FMath::RoundToInt(ViewportSize.X), FMath::RoundToInt(ViewportSize.Y));
			PerfWindowStart = Now;
			PerfFrames = 0;
			PerfWorstFrame = 0.f;
		}
	}
	ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
	if (!PC)
	{
		return;
	}
	if (Battlefield && PC->GetTeam() >= 0)
	{
		const ACWCameraRig* ViewRig = PC->GetCameraRig();
		Battlefield->SetViewTeam(ViewRig && ViewRig->IsArtReviewEnabled() ? ViewRig->GetViewTeam() : PC->GetTeam());
	}
	if (!bBoundController)
	{
		PC->OnCommandRejected.AddUObject(this, &ACWHUD::HandleCommandRejected);
		bBoundController = true;
	}
	const ACWGameState* State = PC->GetCWGameState();
	if (State)
	{
		const uint8 Phase = static_cast<uint8>(State->GetPhase());
		if (Phase != LastPhase)
		{
			LastPhase = Phase;
			if (State->GetPhase() == ECWMatchPhase::Menu || State->GetPhase() == ECWMatchPhase::PostMatch)
			{
				if (IsFrontendMenuOpen()) CloseFrontendMenu();
			}
			if (ACWCameraRig* Rig = PC->GetCameraRig())
			{
				Rig->SetAttractMode(State->GetPhase() == ECWMatchPhase::Menu || State->GetPhase() == ECWMatchPhase::Lobby);
				if (const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>())
				{
					Rig->SetLaneLength(DataSys->GetData().Rules.LaneLength);
				}
			}
			if (State->GetPhase() == ECWMatchPhase::Countdown || State->GetPhase() == ECWMatchPhase::InMatch)
			{
				PC->FocusHome();
			}
			if (State->GetPhase() != ECWMatchPhase::InMatch)
			{
				PC->CancelSkillTargeting();
			}
			if (State->GetPhase() == ECWMatchPhase::PostMatch)
			{
				const bool bWin = State->GetWinner() == FMath::Max(PC->GetTeam(), 0);
				CWAudio::Play2D(this, bWin || State->GetWinner() < 0 ? CWAudio::ESound::Victory : CWAudio::ESound::Defeat, 0.9f, State->GetWinner() < 0 ? 0.8f : 1.f);
			}
		}
	}
#if WITH_EDITOR
	// Offscreen review also exercises the real controller/HUD back path without
	// issuing server commands or changing the simulation's rules.
	FString FrontendFixture;
	if (!bFrontendFixtureOpened && State && State->GetPhase() == ECWMatchPhase::InMatch && State->GetMatchTime() >= 3.f
		&& FParse::Value(FCommandLine::Get(), TEXT("cwuiinmatch="), FrontendFixture)
		&& (FrontendFixture == TEXT("settings") || FrontendFixture == TEXT("leave")))
	{
		bFrontendFixtureOpened = true;
		bFrontendFlowChecking = true;
		PC->BeginSkillTargeting();
		HandleFrontendBack();
		const bool bSkillBack = !PC->IsSkillTargeting() && !IsFrontendMenuOpen();
		HandleFrontendBack();
		const bool bInputsBlocked = IsFrontendMenuOpen() && !PC->CanUseBattleInput() && !PC->CanUseCameraInput();
		PC->BeginSkillTargeting();
		const bool bNoTargetBehindModal = !PC->IsSkillTargeting();
		const uint32 CommandsBefore = PC->GetLocalCommandDispatchCount();
		PC->RequestTrain(0);
		PC->RequestUpgradeAge();
		PC->RequestSellTurret(0);
		const uint32 CommandsAfter = PC->GetLocalCommandDispatchCount();
		const bool bRequestsBlocked = CommandsBefore == CommandsAfter;
		HandleFrontendBack();
		const bool bRestored = !IsFrontendMenuOpen() && PC->CanUseBattleInput() && PC->CanUseCameraInput();
		const bool bPassed = bSkillBack && bInputsBlocked && bNoTargetBehindModal && bRequestsBlocked && bRestored;
		if (bPassed)
		{
			UE_LOG(LogCivWar, Display, TEXT("CIVWAR_FRONTEND_FLOW passed skill_back=%d modal_block=%d target_block=%d rpc_before=%u rpc_after=%u restored=%d"), bSkillBack, bInputsBlocked, bNoTargetBehindModal, CommandsBefore, CommandsAfter, bRestored);
		}
		else
		{
			UE_LOG(LogCivWar, Error, TEXT("CIVWAR_FRONTEND_FLOW failed skill_back=%d modal_block=%d target_block=%d rpc_before=%u rpc_after=%u restored=%d"), bSkillBack, bInputsBlocked, bNoTargetBehindModal, CommandsBefore, CommandsAfter, bRestored);
		}
		bFrontendFlowChecking = false;
		if (FrontendFixture == TEXT("leave")) RequestLeaveMatch();
		else ToggleFrontendMenu();
	}
#endif
	UpdateTargetingPreview();
}

void ACWHUD::UpdateTargetingPreview()
{
	ACWPlayerController* PC = Cast<ACWPlayerController>(GetOwningPlayerController());
	const UCWGameDataSubsystem* DataSys = GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>();
	const ACWGameState* State = PC ? PC->GetCWGameState() : nullptr;
	if (!BattleView || !PC || !DataSys || !DataSys->IsLoaded() || !State)
	{
		return;
	}
	float X = 0.f;
	if (!PC->IsSkillTargeting() || !PC->GetCursorLaneX(X))
	{
		BattleView->SetTargetingPreview(false, 0.f, 0.f, false);
		return;
	}
	const cw::GameData& Data = DataSys->GetData();
	const int32 Team = FMath::Max(PC->GetTeam(), 0);
	const int32 Skill = Data.SkillForAge(State->GetTeam(Team).Age);
	const float Radius = Skill >= 0 ? Data.Skills[Skill].Radius : 300.f;
	// 与服务器相同的落点规则（服务器仍会再次校验）
	float Min = Data.Rules.BaseHalfWidth;
	float Max = Data.Rules.LaneLength - Data.Rules.BaseHalfWidth;
	if (Team == 0)
	{
		Max -= Data.Rules.SkillMinDistanceFromEnemyBase;
	}
	else
	{
		Min += Data.Rules.SkillMinDistanceFromEnemyBase;
	}
	BattleView->SetTargetingPreview(true, X, Radius, X >= Min && X <= Max);
}

void ACWHUD::DrawHUD()
{
	Super::DrawHUD();
	DrawUnitBars();
}

void ACWHUD::DrawUnitBars()
{
	if (!BattleView || !Canvas)
	{
		return;
	}
	for (const TPair<int32, TObjectPtr<ACWUnitVisual>>& Pair : BattleView->GetUnitVisuals())
	{
		const ACWUnitVisual* Unit = Pair.Value.Get();
		if (!Unit || Unit->IsDying())
		{
			continue;
		}
		const float Ratio = Unit->GetHpRatio();
		const bool bChampion = Unit->IsChampion();
		const int32 Rank = Unit->GetRank();
		// 满血且最近未受击时不显示，减少画面干扰（统帅与老兵始终显示）
		if (Ratio > 0.999f && Unit->GetTimeSinceHit() > 2.f && !bChampion && Rank <= 0)
		{
			continue;
		}
		const FVector Screen = Project(Unit->GetActorLocation() + FVector(0.f, 0.f, Unit->GetHeight() + 28.f), true);
		if (Screen.Z <= 0.f)
		{
			continue;
		}
		const float Width = bChampion ? 86.f : (Unit->GetHeight() > 200.f ? 62.f : 42.f);
		const float Height = bChampion ? 8.f : 5.f;
		const float X = Screen.X - Width * 0.5f;
		const FLinearColor Gold(1.f, 0.78f, 0.25f);
		if (bChampion)
		{
			DrawRect(Gold, X - 3.f, Screen.Y - 3.f, Width + 6.f, Height + 6.f); // 统帅：金色描边
		}
		const bool bShowBar = bChampion || Ratio <= 0.999f || Unit->GetTimeSinceHit() <= 2.f;
		if (bShowBar)
		{
			DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.65f), X - 1.f, Screen.Y - 1.f, Width + 2.f, Height + 2.f);
			DrawRect(CWUI::TeamColor(Unit->GetTeam()), X, Screen.Y, Width * FMath::Clamp(Ratio, 0.f, 1.f), Height);
		}
		// 老兵等级：血条上方的金色小方块（★ 数量）
		for (int32 I = 0; I < Rank; ++I)
		{
			const float PipX = Screen.X - (Rank * 9.f - 3.f) * 0.5f + I * 9.f;
			DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.7f), PipX - 1.f, Screen.Y - 10.f, 8.f, 8.f);
			DrawRect(Gold, PipX, Screen.Y - 9.f, 6.f, 6.f);
		}
	}
}

#undef LOCTEXT_NAMESPACE
