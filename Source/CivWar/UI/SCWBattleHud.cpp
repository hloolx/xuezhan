#include "UI/SCWBattleHud.h"

#include "Data/CWGameDataSubsystem.h"
#include "Game/CWGameInstance.h"
#include "Game/CWGameState.h"
#include "Game/CWPlayerController.h"
#include "Net/CWBattleReplicator.h"
#include "Sim/SimTypes.h"
#include "UI/CWUIText.h"
#include "UI/CWHUD.h"
#include "UI/CWFrontendFlow.h"
#include "UI/SCWMenus.h"
#include "UI/SCWMinimap.h"
#include "UI/SCWEpicFrame.h"
#include "Widgets/Images/SImage.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SSpacer.h"
#include "Widgets/SLeafWidget.h"
#include "Rendering/DrawElements.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SOverlay.h"
#include "Widgets/Text/STextBlock.h"

#define LOCTEXT_NAMESPACE "CivWarUI"

// One coherent line-symbol set: blade, bow and shield encode unit roles, never unit portraits.
namespace
{
// Disabled commands must still explain their cost and recovery condition. Only the
// child paint state is overridden; Slate's normal disabled input routing is retained.
class SCWReadableCommandContent : public SCompoundWidget
{
public:
	SLATE_BEGIN_ARGS(SCWReadableCommandContent) {}
		SLATE_DEFAULT_SLOT(FArguments, Content)
	SLATE_END_ARGS()
	void Construct(const FArguments& Args) { ChildSlot[Args._Content.Widget]; }
	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& Clip,
		FSlateWindowElementList& Draw, int32 Layer, const FWidgetStyle& Style, bool) const override
	{
		return SCompoundWidget::OnPaint(Args, Geometry, Clip, Draw, Layer, Style, true);
	}
};

class SCWCommandButton : public SButton
{
public:
	void Construct(const SButton::FArguments& Args)
	{
		SButton::FArguments ReadableArgs = Args;
		ReadableArgs[SNew(SCWReadableCommandContent)[Args._Content.Widget]];
		SButton::Construct(ReadableArgs);
		SetShowEffectWhenDisabled(false);
	}
};

class SCWRoleGlyph : public SLeafWidget
{
public:
	SLATE_BEGIN_ARGS(SCWRoleGlyph) {}
		SLATE_ATTRIBUTE(int32, Role)
	SLATE_END_ARGS()
	void Construct(const FArguments& Args) { Role = Args._Role; }
	virtual FVector2D ComputeDesiredSize(float) const override { return FVector2D(38.f, 38.f); }
	virtual int32 OnPaint(const FPaintArgs&, const FGeometry& G, const FSlateRect&, FSlateWindowElementList& Draw,
		int32 Layer, const FWidgetStyle&, bool) const override
	{
		auto Stroke = [&](std::initializer_list<FVector2f> Points)
		{
			TArray<FVector2f> P;
			for (const FVector2f& V : Points) { P.Add(V); }
			FSlateDrawElement::MakeLines(Draw, Layer, G.ToPaintGeometry(), P, ESlateDrawEffect::None, CWUI::Gold, true, 1.8f);
		};
		if (Role.Get() == 1)
		{
			Stroke({{11,5},{22,11},{25,19},{22,27},{11,33}});
			Stroke({{11,5},{16,19},{11,33}});
			Stroke({{6,19},{33,19},{28,14}});
			Stroke({{33,19},{28,24}});
		}
		else if (Role.Get() == 2)
		{
			Stroke({{19,4},{32,10},{29,26},{19,34},{9,26},{6,10},{19,4}});
			Stroke({{19,9},{19,28}});
			Stroke({{11,16},{27,16}});
		}
		else
		{
			Stroke({{11,27},{27,6},{33,5},{32,11},{15,31}});
			Stroke({{7,23},{19,33}});
			Stroke({{13,29},{8,35},{4,32},{9,26}});
		}
		return Layer + 1;
	}
private:
	TAttribute<int32> Role;
};
}


// ---------------------------------------------------------------------------
// 数据访问
// ---------------------------------------------------------------------------
const ACWGameState* SCWBattleHud::GS() const
{
	const ACWPlayerController* PC = Controller.Get();
	return PC ? PC->GetCWGameState() : nullptr;
}

const cw::GameData* SCWBattleHud::Data() const
{
	const ACWPlayerController* PC = Controller.Get();
	const UGameInstance* GI = PC ? PC->GetGameInstance() : nullptr;
	const UCWGameDataSubsystem* Sys = GI ? GI->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	return Sys && Sys->IsLoaded() ? &Sys->GetData() : nullptr;
}

int32 SCWBattleHud::MyTeam() const
{
	const ACWPlayerController* PC = Controller.Get();
	return PC ? FMath::Max(PC->GetTeam(), 0) : 0;
}

int32 SCWBattleHud::SideTeam(int32 Side) const
{
	return Side == 0 ? MyTeam() : 1 - MyTeam();
}

const FCWTeamNetState* SCWBattleHud::TeamState(int32 Team) const
{
	const ACWGameState* G = GS();
	return G ? &G->GetTeam(Team) : nullptr;
}

int32 SCWBattleHud::UnitDefForSlot(int32 Slot) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(MyTeam());
	if (!D || !S)
	{
		return -1;
	}
	const std::vector<int32_t> List = D->UnitsForAge(S->Age);
	return Slot >= 0 && Slot < static_cast<int32>(List.size()) ? List[Slot] : -1;
}

static FString CWHud_DoctrineNames(const UCWGameDataSubsystem& Sys, const FCWTeamNetState& S)
{
	FString Names;
	for (const uint8 Pick : S.Doctrines)
	{
		Names += (Names.IsEmpty() ? TEXT("") : TEXT("、")) + Sys.GetDoctrineName(Pick).ToString();
	}
	return Names;
}

static cw::DoctrineEffects CWHud_Effects(const cw::GameData& D, const FCWTeamNetState& S)
{
	std::vector<int32_t> Picks;
	Picks.reserve(S.Doctrines.Num());
	for (const uint8 Pick : S.Doctrines)
	{
		Picks.push_back(Pick);
	}
	return D.ComputeEffects(Picks);
}

// Match Simulation::IncomePerSecond, including doctrine and sudden-death modifiers.
static float CWHud_IncomeFactor(const cw::GameData& D, const FCWTeamNetState& S, const ACWGameState& G)
{
	return FMath::Max(1.f + CWHud_Effects(D, S).Income, 0.f)
		* (G.GetMatchTime() >= D.Rules.SuddenDeathTime ? D.Rules.SuddenDeathIncomeMultiplier : 1.f);
}

static FText CWHud_RateText(float Value)
{
	FNumberFormattingOptions Format;
	Format.SetMaximumFractionalDigits(1);
	return FText::AsNumber(Value, &Format);
}

int32 SCWBattleHud::EffectiveCost(int32 Team, int32 Def) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(Team);
	return D && S ? D->EffectiveUnitCost(CWHud_Effects(*D, *S), Def) : 0;
}

float SCWBattleHud::EffectiveTrainTime(int32 Team, int32 Def) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(Team);
	return D && S ? D->EffectiveTrainTime(CWHud_Effects(*D, *S), Def) : 1.f;
}

const FCWUnitNetItem* SCWBattleHud::FindUnitItem(int32 Id) const
{
	const ACWGameState* G = GS();
	const ACWBattleReplicator* Rep = G ? G->GetReplicator() : nullptr;
	if (!Rep || Id < 0)
	{
		return nullptr;
	}
	for (const FCWUnitNetItem& U : Rep->GetUnits().Items)
	{
		if (U.Id == Id)
		{
			return &U;
		}
	}
	return nullptr;
}

FText SCWBattleHud::ChampionStatusText(int32 Team) const
{
	const FCWTeamNetState* S = TeamState(Team);
	const ACWPlayerController* PC = Controller.Get();
	const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!S || !Sys || S->ChampionDef < 0)
	{
		return FText::GetEmpty();
	}
	const FText Name = Sys->GetChampionName(S->ChampionDef);
	if (S->ChampionId < 0)
	{
		return FText::Format(LOCTEXT("ChampionDeadStatus", "统帅 {0} 阵亡 · {1} 秒后复活"), Name, FText::AsNumber(FMath::CeilToInt(FMath::Max(S->ChampionRespawn, 0.f))));
	}
	return FText::Format(S->ChampionOrder == 1 ? LOCTEXT("ChampionHoldStatus", "统帅 {0} · 坚守") : LOCTEXT("ChampionFollowStatus", "统帅 {0} · 随军"), Name);
}

// ---------------------------------------------------------------------------
// 构建
// ---------------------------------------------------------------------------
void SCWBattleHud::Construct(const FArguments& InArgs)
{
	Controller = InArgs._Controller;

	ChildSlot
	[
		SNew(SOverlay)
		+ SOverlay::Slot().VAlign(VAlign_Top).Padding(FMargin(16.f, 12.f))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				MakeTopBar()
			]
			// 背水一战：基地生命降到一半以下且本局未使用时出现
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Left).Padding(0.f, 8.f, 0.f, 0.f)
			[
				SNew(SBox)
				.WidthOverride(342.f)
				.MinDesiredHeight(112.f)
				.Visibility_Lambda([this]()
				{
					const ACWGameState* G = GS();
					const cw::GameData* D = Data();
					const FCWTeamNetState* S = TeamState(MyTeam());
					const bool bAvailable = G && D && S && G->GetPhase() == ECWMatchPhase::InMatch && !S->bLastStandUsed && S->BaseMaxHp > 0.f
						&& S->BaseHp <= S->BaseMaxHp * D->Rules.LastStandBaseHpRatio;
					return bAvailable ? EVisibility::Visible : EVisibility::Collapsed;
				})
				[
					SNew(SCWCommandButton)
					.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Danger))
					.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnLastStand))
					.ToolTipText_Lambda([this]()
					{
						const cw::GameData* D = Data();
						return D ? FText::Format(LOCTEXT("LastStandTip", "每局一次：修复 {0}% 城墙，免费征召 {1} 名本时代近战兵，全军伤害 +{2}%、攻速 +{3}% 持续 {4} 秒，炮塔伤害 +{5}% 持续 {6} 秒；阵亡的统帅立即复活。快捷键 L"),
							FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandRepair * 100.f)), FText::AsNumber(D->Rules.LastStandMilitia),
							FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandDamageBonus * 100.f)), FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandAttackSpeedBonus * 100.f)),
							FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandBuffDuration)), FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandTurretBonus * 100.f)),
							FText::AsNumber(FMath::RoundToInt(D->Rules.LastStandTurretDuration))) : FText::GetEmpty();
					})
					[
						SNew(SVerticalBox)
						+ SVerticalBox::Slot().AutoHeight()
						[
							SNew(STextBlock)
							.Font(CWUI::Font(18, true, true))
							.ColorAndOpacity(CWUI::TextMain)
							.Text(LOCTEXT("LastStandTitle", "背水一战！（L）"))
						]
						+ SVerticalBox::Slot().AutoHeight()
						[
							SNew(STextBlock)
							.Font(CWUI::Font(13))
							.ColorAndOpacity(FLinearColor(1.f, 0.85f, 0.8f))
							.AutoWrapText(true)
							.WrapTextAt(314.f)
							.Text(LOCTEXT("LastStandDesc", "每局一次：修复城墙、征召民兵、全军鼓舞、炮塔强化"))
						]
					]
				]
			]
			// 玩法提示：开局前几分钟轮流显示（新玩家熟悉统帅、国策、老兵等操作）
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Left).Padding(0.f, 8.f, 0.f, 0.f)
			[
				SNew(SBorder)
				.BorderImage(CWUI::PanelLightBrush())
				.Padding(FMargin(12.f, 6.f))
				.Visibility_Lambda([this]()
				{
					const ACWGameState* G = GS();
					return G && G->GetPhase() == ECWMatchPhase::InMatch && G->GetMatchTime() < 240.f ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
				})
				[
					SNew(SBox)
					.WidthOverride(318.f)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(12))
						.AutoWrapText(true)
						.ColorAndOpacity(FLinearColor(0.85f, 0.92f, 1.f))
						.Text_Lambda([this]()
						{
							static const FText Tips[] = {
								LOCTEXT("Tip1", "提示：先在下方三张卡里选一项国策，它会决定这一局的打法。"),
								LOCTEXT("Tip2", "提示：统帅会自动跟随部队作战；右键点击战场，可以让他坚守在那里。"),
								LOCTEXT("Tip3", "提示：按 R 施放战吼，范围内友军加伤、加攻速并回血，两军接战时用效果最好。"),
								LOCTEXT("Tip4", "提示：统帅残血时右键点己方城门让他撤回，城门附近没有敌人时回血很快。"),
								LOCTEXT("Tip5", "提示：单位击杀敌人会晋升老兵（头顶金色方块），保住老兵比硬拼更划算。"),
								LOCTEXT("Tip6", "提示：兵力不利时按 F 驻守，在炮塔掩护下集结，攒够了再按 F 推进。"),
								LOCTEXT("Tip7", "提示：击杀敌方统帅能拿到赏金；敌方统帅冲得太靠前时集中火力。"),
								LOCTEXT("Tip8", "提示：经验和金币够了按 U 进化——新时代有更强的兵种、统帅和新的国策。"),
							};
							const ACWGameState* G = GS();
							const int32 Index = G ? FMath::FloorToInt(G->GetMatchTime() / 12.f) % UE_ARRAY_COUNT(Tips) : 0;
							return Tips[Index];
						})
					]
				]
			]
		]
		// 提示条
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Top).Padding(FMargin(0.f, 204.f, 0.f, 0.f))
		[
			SNew(SBorder)
			.BorderImage(CWUI::PanelBrush())
			.Padding(FMargin(22.f, 10.f))
			.Visibility(this, &SCWBattleHud::GetToastVisibility)
			[
				SNew(STextBlock)
				.Text(this, &SCWBattleHud::GetToastText)
				.Font(CWUI::Font(20, true))
				.ColorAndOpacity_Lambda([this]() { return FSlateColor(ToastColor); })
			]
		]
		// 技能瞄准提示
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 292.f))
		[
			SNew(STextBlock)
			.Text(LOCTEXT("TargetHint", "左键点击战场选择技能落点 · 右键 / Esc 取消"))
			.Font(CWUI::Font(18, true, true))
			.ColorAndOpacity(CWUI::Gold)
			.Visibility_Lambda([this]()
			{
				const ACWPlayerController* PC = Controller.Get();
				return PC && PC->IsSkillTargeting() ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
			})
		]
		// 开局倒计时
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
		[
			SNew(STextBlock)
			.Font(CWUI::Font(110, true, true))
			.ColorAndOpacity(CWUI::Gold)
			.Text_Lambda([this]()
			{
				const ACWGameState* G = GS();
				return G ? FText::AsNumber(FMath::CeilToInt(G->GetPhaseTimeLeft())) : FText::GetEmpty();
			})
			.Visibility_Lambda([this]()
			{
				const ACWGameState* G = GS();
				return G && G->GetPhase() == ECWMatchPhase::Countdown ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
			})
		]
		// 底部指令面板
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 12.f))
		[
			MakeCommandPanel()
		]
		// 国策三选一（不暂停游戏）
		+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 0.f, 320.f))
		[
			MakeDoctrinePanel()
		]
		// 战局设置始终可找到；退出确认在全屏模态层内进行。
		+ SOverlay::Slot().HAlign(HAlign_Right).VAlign(VAlign_Top).Padding(FMargin(0.f, 156.f, 16.f, 0.f))
		[
			CWUI::MakeButton(LOCTEXT("BattleMenu", "声音 / 菜单  Esc"), FOnClicked::CreateSP(this, &SCWBattleHud::OnFrontendMenu), CWUI::EButtonKind::Normal, 156.f, true,
				LOCTEXT("BattleMenuTip", "调整音量或返回主菜单；对局仍在继续"), 14)
		]
		// 结算
		+ SOverlay::Slot()
		[
			MakeResultPanel()
		]
	];
}

TSharedRef<SWidget> SCWBattleHud::MakeBar(TAttribute<float> Ratio, TAttribute<FSlateColor> Color, float Width, float Height, TAttribute<FText> Text)
{
	return SNew(SBox)
		.WidthOverride(Width)
		.HeightOverride(Height)
		[
			SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SImage).Image(CWUI::RoundedFill()).ColorAndOpacity(FLinearColor(0.f, 0.f, 0.f, 0.65f))
			]
			+ SOverlay::Slot().HAlign(HAlign_Left)
			[
				SNew(SBox)
				.WidthOverride_Lambda([Ratio, Width]() { return FOptionalSize(Width * FMath::Clamp(Ratio.Get(), 0.f, 1.f)); })
				[
					SNew(SImage).Image(CWUI::RoundedFill()).ColorAndOpacity(Color)
				]
			]
			+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
			[
				SNew(STextBlock).Text(Text).Font(CWUI::Font(13, true, true)).ColorAndOpacity(CWUI::TextMain)
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeSideInfo(int32 Side)
{
	return SNew(SBorder)
		.BorderImage(CWUI::PanelBrush())
		.Padding(FMargin(12.f, 9.f))
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight()
			[
				SNew(SHorizontalBox)
				+ SHorizontalBox::Slot().AutoWidth()
				[
					SNew(STextBlock)
					.Text(Side == 0 ? LOCTEXT("Mine", "我方") : LOCTEXT("Enemy", "敌方"))
					.Font(CWUI::Font(15, true))
					.ColorAndOpacity_Lambda([this, Side]() { return FSlateColor(CWUI::TeamColor(SideTeam(Side))); })
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(10.f, 0.f, 0.f, 0.f)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(15, true))
					.ColorAndOpacity(CWUI::Gold)
					.Text_Lambda([this, Side]()
					{
						const cw::GameData* D = Data();
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return D && S && S->Age < D->Ages.size() ? CWUIText::FromUtf8(D->Ages[S->Age].DisplayName) : FText::GetEmpty();
					})
				]
				+ SHorizontalBox::Slot().AutoWidth().Padding(10.f, 0.f, 0.f, 0.f)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, false))
					.ColorAndOpacity(CWUI::Warning)
					.Text_Lambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return S && S->bUpgrading
							? FText::Format(LOCTEXT("Evolving", "进化中 {0} 秒"), FText::AsNumber(FMath::CeilToInt(S->UpgradeTimeLeft)))
							: FText::GetEmpty();
					})
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)
			[
				MakeBar(
					TAttribute<float>::CreateLambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return S && S->BaseMaxHp > 0.f ? S->BaseHp / S->BaseMaxHp : 0.f;
					}),
					TAttribute<FSlateColor>::CreateLambda([this, Side]() { return FSlateColor(CWUI::TeamColor(SideTeam(Side))); }),
					314.f, 16.f,
					TAttribute<FText>::CreateLambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return S ? FText::Format(LOCTEXT("BaseHp", "基地 {0} / {1}"), FText::AsNumber(FMath::CeilToInt(S->BaseHp)),
							FText::AsNumber(FMath::RoundToInt(S->BaseMaxHp))) : FText::GetEmpty();
					}))
			]
			// 统帅：名称、状态与生命
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.WrapTextAt(314.f)
					.Text_Lambda([this, Side]() { return ChampionStatusText(SideTeam(Side)); })
					.ColorAndOpacity_Lambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return FSlateColor(S && S->ChampionId < 0 ? CWUI::Bad : CWUI::TextMain);
					})
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f, 0.f, 0.f)
				[
					SNew(SBox)
					.Visibility_Lambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						return S && S->ChampionId >= 0 ? EVisibility::Visible : EVisibility::Collapsed;
					})
					[
						MakeBar(
							TAttribute<float>::CreateLambda([this, Side]()
							{
								const FCWTeamNetState* S = TeamState(SideTeam(Side));
								const FCWUnitNetItem* U = S ? FindUnitItem(S->ChampionId) : nullptr;
								return U && U->MaxHp > 0 ? static_cast<float>(U->Hp) / static_cast<float>(U->MaxHp) : 0.f;
							}),
							TAttribute<FSlateColor>::CreateLambda([this, Side]() { return FSlateColor(CWUI::TeamColor(SideTeam(Side)) * 0.8f + FLinearColor(0.2f, 0.2f, 0.2f, 0.2f)); }),
							314.f, 4.f, TAttribute<FText>())
					]
				]
			]
			// 已选国策（对手也能看到，便于针对）
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 5.f, 0.f, 0.f)
			[
				SNew(SBox)
				.WidthOverride(314.f)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(11))
					.OverflowPolicy(ETextOverflowPolicy::Ellipsis)
					.ToolTipText_Lambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						const ACWPlayerController* PC = Controller.Get();
						const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
						return S && Sys ? FText::FromString(CWHud_DoctrineNames(*Sys, *S)) : FText::GetEmpty();
					})
					.ColorAndOpacity(FLinearColor(1.f, 0.85f, 0.55f))
					.Text_Lambda([this, Side]()
					{
						const FCWTeamNetState* S = TeamState(SideTeam(Side));
						const ACWPlayerController* PC = Controller.Get();
						const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
						if (!S || !Sys || Sys->GetData().Doctrines.empty())
						{
							return FText::GetEmpty();
						}
						if (S->Doctrines.Num() == 0)
						{
							return S->Offer.Num() > 0 ? LOCTEXT("DoctrinePending", "国策：正在抉择…") : LOCTEXT("DoctrineNone", "国策：暂无");
						}
						FString Names;
						for (const uint8 Pick : S->Doctrines)
						{
							Names += (Names.IsEmpty() ? TEXT("") : TEXT("、")) + Sys->GetDoctrineName(Pick).ToString();
						}
						return FText::Format(LOCTEXT("DoctrineList", "国策：{0}"), FText::FromString(Names));
					})
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeTopBar()
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Left).VAlign(VAlign_Top)
		[
			MakeSideInfo(0)
		]
		+ SHorizontalBox::Slot().AutoWidth().HAlign(HAlign_Center)
		[
			SNew(SBorder)
			.BorderImage(CWUI::PanelBrush())
			.Padding(FMargin(12.f, 6.f))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(26, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([this]() { const ACWGameState* G = GS(); return G ? CWUIText::Clock(G->GetMatchTime()) : FText::GetEmpty(); })
				]
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.WrapTextAt(444.f)
					.Justification(ETextJustify::Center)
					.ColorAndOpacity(CWUI::Bad)
					.Text_Lambda([this]()
					{
						const ACWGameState* G = GS();
						const cw::GameData* D = Data();
						if (!G || !D || G->GetMatchTime() < D->Rules.SuddenDeathTime)
						{
							return D && G ? FText::Format(LOCTEXT("SuddenSoon", "距决战 {0}"), CWUIText::Clock(D->Rules.SuddenDeathTime - G->GetMatchTime()))
							              : FText::GetEmpty();
						}
						const float Minutes = (G->GetMatchTime() - D->Rules.SuddenDeathTime) / 60.f;
						const float Mult = FMath::Min(D->Rules.SuddenDeathBaseDamage + D->Rules.SuddenDeathRampPerMinute * Minutes, D->Rules.SuddenDeathMaxMultiplier);
						const float TurretMult = FMath::Max(D->Rules.SuddenDeathTurretMin, 1.f - D->Rules.SuddenDeathTurretDecayPerMinute * Minutes);
						const FText Format = D->Rules.SuddenDeathIncomeMultiplier <= 0.f
							? LOCTEXT("SuddenDeathNoIncome", "决战阶段 · 基础收入停止 · 基地受伤 ×{0} · 炮塔 ×{1} · 时限 {2}")
							: LOCTEXT("SuddenDeath", "决战阶段 · 基地受伤 ×{0} · 炮塔 ×{1} · 时限 {2}");
						return FText::Format(Format,
							FText::AsNumber(FMath::RoundToFloat(Mult * 10.f) / 10.f), FText::AsNumber(FMath::RoundToFloat(TurretMult * 100.f) / 100.f),
							CWUIText::Clock(D->Rules.MatchTimeLimit - G->GetMatchTime()));
					})
				]
				// 小地图：点击/拖动跳转镜头
				+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 4.f, 0.f, 0.f)
				[
					SNew(SCWMinimap).Controller(Controller)
				]
			]
		]
		+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right).VAlign(VAlign_Top)
		[
			MakeSideInfo(1)
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeResourceRow()
{
	return SNew(SBorder)
		.BorderImage(CWUI::PanelBrush())
		.Padding(FMargin(14.f, 6.f))
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth()
			[
				SNew(STextBlock)
				.Font(CWUI::Font(19, true))
				.ColorAndOpacity(CWUI::Gold)
				.Text_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					const cw::GameData* D = Data();
					const ACWGameState* G = GS();
					if (!S || !D || !G || S->Age >= D->Ages.size())
					{
						return FText::GetEmpty();
					}
					const float Income = D->Ages[S->Age].IncomePerSec * (1.f + D->Rules.EconomyIncomeBonus * S->EconomyLevel)
						* CWHud_IncomeFactor(*D, *S, *G);
					return FText::Format(LOCTEXT("Gold", "{0} 金   +{1}/秒"), FText::AsNumber(S->Gold), CWHud_RateText(Income));
				})
			]
			+ SHorizontalBox::Slot().AutoWidth().Padding(24.f, 0.f, 0.f, 0.f)
			[
				SNew(STextBlock)
				.Font(CWUI::Font(19, true))
				.ColorAndOpacity(FLinearColor(0.55f, 0.8f, 1.f))
				.Text_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					const cw::GameData* D = Data();
					if (!S || !D)
					{
						return FText::GetEmpty();
					}
					const int32 Next = S->Age + 1;
					if (Next >= static_cast<int32>(D->Ages.size()))
					{
						return FText::Format(LOCTEXT("XpMax", "经验 {0}"), FText::AsNumber(S->Xp));
					}
					return FText::Format(LOCTEXT("Xp", "经验  {0} / {1}"), FText::AsNumber(S->Xp), FText::AsNumber(D->Ages[Next].XpToEnter));
				})
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeCommandPanel()
{
	auto SectionTitle = [](const FText& Text)
	{
		return SNew(STextBlock).Text(Text).Font(CWUI::Font(13, true)).ColorAndOpacity(CWUI::TextMain);
	};
	auto Panel = [](TSharedRef<SWidget> Content)
	{
		return SNew(SCWEpicFrame).BorderImage(CWUI::PanelBrush()).Padding(FMargin(12.f, 10.f))[Content];
	};
	TSharedRef<SHorizontalBox> UnitRow = SNew(SHorizontalBox);
	for (int32 I = 0; I < 3; ++I)
	{
		UnitRow->AddSlot().AutoWidth().Padding(I == 0 ? 0.f : 6.f, 0.f, 0.f, 0.f)[MakeUnitButton(I)];
	}
	TSharedRef<SHorizontalBox> QueueRow = SNew(SHorizontalBox);
	for (int32 I = 0; I < 5; ++I)
	{
		QueueRow->AddSlot().AutoWidth().Padding(3.f, 0.f)[MakeQueueSlot(I)];
	}
	TSharedRef<SHorizontalBox> TurretRow = SNew(SHorizontalBox);
	for (int32 I = 0; I < 3; ++I)
	{
		TurretRow->AddSlot().AutoWidth().Padding(I == 0 ? 0.f : 5.f, 0.f, 0.f, 0.f)[MakeTurretSlot(I)];
	}
	return SNew(SVerticalBox)
		.Visibility_Lambda([this]()
		{
			const ACWGameState* G = GS();
			return G && (G->GetPhase() == ECWMatchPhase::InMatch || G->GetPhase() == ECWMatchPhase::Countdown) ? EVisibility::SelfHitTestInvisible : EVisibility::Collapsed;
		})
		+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Right).Padding(0.f, 0.f, 0.f, 6.f)[MakeBuildMenu()]
		+ SVerticalBox::Slot().AutoHeight().Padding(232.f, 0.f, 0.f, 6.f).HAlign(HAlign_Left)[MakeResourceRow()]
		+ SVerticalBox::Slot().AutoHeight()
		[
			SNew(SHorizontalBox)
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom)
			[
				Panel(SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 8.f)[SectionTitle(LOCTEXT("DevelopmentSection", "文明发展"))]
					+ SVerticalBox::Slot().AutoHeight()[MakeAgeButton()]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)[MakeEconomyButton()])
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom).Padding(8.f, 0.f)
			[
				Panel(SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 8.f)[SectionTitle(LOCTEXT("TrainSection", "征召部队"))]
					+ SVerticalBox::Slot().AutoHeight()[UnitRow]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 7.f, 0.f, 0.f)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 8.f, 0.f)
						[
							SNew(STextBlock).Font(CWUI::Font(11)).ColorAndOpacity(CWUI::TextDim)
							.Text_Lambda([this]()
							{
								const FCWTeamNetState* S = TeamState(MyTeam());
								const cw::GameData* D = Data();
								return S && D ? FText::Format(LOCTEXT("Queue", "队列 {0}/{1}"), FText::AsNumber(S->Queue.Num()), FText::AsNumber(D->Rules.QueueCapacity)) : FText::GetEmpty();
							})
						]
						+ SHorizontalBox::Slot().AutoWidth()
						[
							SNew(SOverlay)
							+ SOverlay::Slot()[QueueRow]
							+ SOverlay::Slot().VAlign(VAlign_Center)
							[
								SNew(STextBlock).Font(CWUI::Font(11)).ColorAndOpacity(CWUI::TextDim)
								.Text(LOCTEXT("QueueEmpty", "点击兵种征召 · 点击队列取消"))
								.Visibility_Lambda([this]()
								{
									const FCWTeamNetState* S = TeamState(MyTeam());
									return S && S->Queue.Num() == 0 ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
								})
							]
						]
					])
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom)
			[
				Panel(SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 8.f)[SectionTitle(LOCTEXT("CommandSection", "战术指挥"))]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth()[MakeSkillButton()]
						+ SHorizontalBox::Slot().AutoWidth().Padding(6.f, 0.f, 0.f, 0.f)
						[
							SNew(SVerticalBox)
							+ SVerticalBox::Slot().AutoHeight()[MakeChampionAbilityButton()]
							+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)[MakeChampionOrderButton()]
						]
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 0.f)[MakeStanceButton()])
			]
			+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Bottom).Padding(8.f, 0.f, 0.f, 0.f)
			[
				Panel(SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 8.f)[SectionTitle(LOCTEXT("DefenseSection", "城防工事"))]
					+ SVerticalBox::Slot().AutoHeight()[TurretRow]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 8.f, 0.f, 0.f)
					[SNew(STextBlock).Text(LOCTEXT("DefenseHelp", "点击空位建造 · 升级 / 出售")) .Font(CWUI::Font(11)).ColorAndOpacity(CWUI::TextDim)])
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeUnitButton(int32 Slot)
{
	return SNew(SBox)
		.WidthOverride(166.f).HeightOverride(132.f)
		.Visibility_Lambda([this, Slot]() { return UnitDefForSlot(Slot) >= 0 ? EVisibility::Visible : EVisibility::Hidden; })
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.ContentPadding(FMargin(2.f, 5.f))
			.IsEnabled_Lambda([this, Slot]() { FText Reason; return CanTrain(Slot, Reason); })
			.ToolTipText_Lambda([this, Slot]()
			{
				const cw::GameData* D = Data();
				const int32 Def = UnitDefForSlot(Slot);
				const ACWPlayerController* PC = Controller.Get();
				const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
				return D && Def >= 0 && Sys ? CWUIText::UnitTooltip(D->Units[Def], Sys->GetUnitDescription(Def)) : FText::GetEmpty();
			})
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnTrain, Slot))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(SCWRoleGlyph).Role_Lambda([this, Slot]()
						{
							const cw::GameData* D = Data();
							const int32 Def = UnitDefForSlot(Slot);
							return D && Def >= 0 ? static_cast<int32>(D->Units[Def].Role) : 0;
						})
					]
					+ SHorizontalBox::Slot().FillWidth(1.f).HAlign(HAlign_Right).VAlign(VAlign_Center)
					[
						SNew(STextBlock).Font(CWUI::Font(17, true)).ColorAndOpacity(CWUI::Gold)
						.Text_Lambda([this, Slot]()
						{
							const int32 Def = UnitDefForSlot(Slot);
							return Def >= 0 ? FText::Format(LOCTEXT("Cost", "{0} 金"), FText::AsNumber(EffectiveCost(MyTeam(), Def))) : FText::GetEmpty();
						})
					]
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 6.f, 0.f, 3.f)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth().VAlign(VAlign_Center).Padding(0.f, 0.f, 6.f, 0.f)
					[
						SNew(SBorder).BorderImage(CWUI::PanelLightBrush()).Padding(FMargin(5.f, 1.f))
						[SNew(STextBlock).Text(FText::AsNumber(Slot + 1)).Font(CWUI::Font(11, true)).ColorAndOpacity(CWUI::Gold)]
					]
					+ SHorizontalBox::Slot().FillWidth(1.f).VAlign(VAlign_Center)
					[
						SNew(STextBlock).Font(CWUI::Font(15, true)).ColorAndOpacity(CWUI::TextMain)
						.OverflowPolicy(ETextOverflowPolicy::Ellipsis)
						.Text_Lambda([this, Slot]()
						{
							const cw::GameData* D = Data();
							const int32 Def = UnitDefForSlot(Slot);
							return D && Def >= 0 ? CWUIText::FromUtf8(D->Units[Def].DisplayName) : FText::GetEmpty();
						})
					]
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock).Font(CWUI::Font(11)).AutoWrapText(true)
					.ColorAndOpacity_Lambda([this, Slot]() { FText Reason; return FSlateColor(CanTrain(Slot, Reason) || Reason.IsEmpty() ? CWUI::TextDim : CWUI::Bad); })
					.Text_Lambda([this, Slot]()
					{
						FText Reason;
						if (!CanTrain(Slot, Reason) && !Reason.IsEmpty()) { return Reason; }
						const cw::GameData* D = Data();
						const int32 Def = UnitDefForSlot(Slot);
						return D && Def >= 0 ? FText::Format(LOCTEXT("UnitRole", "{0} · {1}"), CWUIText::RoleName(D->Units[Def].Role), CWUIText::ArmorName(D->Units[Def].Armor)) : FText::GetEmpty();
					})
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeQueueSlot(int32 Index)
{
	return SNew(SBox)
		.WidthOverride(58.f)
		.HeightOverride(30.f)
		.Visibility_Lambda([this, Index]()
		{
			const FCWTeamNetState* S = TeamState(MyTeam());
			return S && Index < S->Queue.Num() ? EVisibility::Visible : EVisibility::Hidden;
		})
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::CompactButtonStyle(CWUI::EButtonKind::Normal))
			.ContentPadding(FMargin(1.f))
			.ToolTipText(LOCTEXT("CancelTip", "点击取消训练，返还全部金币"))
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnCancelQueue, Index))
			[
				SNew(SOverlay)
				+ SOverlay::Slot().HAlign(HAlign_Center).VAlign(VAlign_Center)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(11, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([this, Index]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						const cw::GameData* D = Data();
						if (!S || !D || Index >= S->Queue.Num() || S->Queue[Index].Def >= D->Units.size())
						{
							return FText::GetEmpty();
						}
						return FText::FromString(CWUIText::FromUtf8(D->Units[S->Queue[Index].Def].DisplayName).ToString().Left(2));
					})
				]
				+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom)
				[
					SNew(SBox)
					.HeightOverride(3.f)
					.WidthOverride_Lambda([this, Index]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						const cw::GameData* D = Data();
						if (!S || !D || Index != 0 || S->Queue.Num() == 0 || S->Queue[0].Def >= D->Units.size())
						{
							return FOptionalSize(0.f);
						}
						return FOptionalSize(52.f * FMath::Clamp(S->Queue[0].Progress / EffectiveTrainTime(MyTeam(), S->Queue[0].Def), 0.f, 1.f));
					})
					[
						SNew(SImage).Image(CWUI::WhiteBrush()).ColorAndOpacity(CWUI::Good)
					]
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeAgeButton()
{
	return SNew(SBox)
		.WidthOverride(204.f)
		.HeightOverride(98.f)
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Primary))
			.IsEnabled_Lambda([this]() { FText Reason; return CanUpgradeAge(Reason); })
			.ToolTipText(LOCTEXT("AgeTip", "进入下一时代：解锁新兵种、炮塔与技能，提升基地生命上限与金币收入。已出场的单位继续存在，训练队列中的旧单位照常出生。"))
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnUpgradeAge))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(15, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([this]()
					{
						const cw::GameData* D = Data();
						const FCWTeamNetState* S = TeamState(MyTeam());
						if (!D || !S)
						{
							return FText::GetEmpty();
						}
						const int32 Next = S->Age + 1;
						return Next < static_cast<int32>(D->Ages.size())
							? FText::Format(LOCTEXT("AgeNext", "U  进化 · {0}"), CWUIText::FromUtf8(D->Ages[Next].DisplayName))
							: LOCTEXT("AgeTop", "已是最终时代");
					})
				]
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12))
					.ColorAndOpacity(CWUI::Gold)
					.AutoWrapText(true)
					.Text_Lambda([this]()
					{
						const cw::GameData* D = Data();
						const FCWTeamNetState* S = TeamState(MyTeam());
						if (!D || !S || S->Age + 1 >= static_cast<int32>(D->Ages.size()))
						{
							return FText::GetEmpty();
						}
						const cw::AgeDef& Next = D->Ages[S->Age + 1];
						return FText::Format(LOCTEXT("AgeReq", "{2} 金 · 经验 {0}/{1}"), FText::AsNumber(FMath::Min(S->Xp, Next.XpToEnter)),
							FText::AsNumber(Next.XpToEnter), FText::AsNumber(Next.GoldToEnter));
					})
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(11))
					.ColorAndOpacity(CWUI::Bad)
					.AutoWrapText(true)
					.Text_Lambda([this]() { FText Reason; CanUpgradeAge(Reason); return Reason; })
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeSkillButton()
{
	auto CooldownRatio = [this]()
	{
		const cw::GameData* D = Data();
		const FCWTeamNetState* S = TeamState(MyTeam());
		if (!D || !S)
		{
			return 0.f;
		}
		const int32 Skill = D->SkillForAge(S->Age);
		return Skill >= 0 && D->Skills[Skill].Cooldown > 0.f ? FMath::Clamp(S->SkillCooldown / D->Skills[Skill].Cooldown, 0.f, 1.f) : 0.f;
	};
	return SNew(SBox)
		.WidthOverride(144.f)
		.HeightOverride(100.f)
		[
			SNew(SOverlay)
			+ SOverlay::Slot()
			[
				SNew(SCWCommandButton)
				.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
				.IsEnabled_Lambda([this]() { FText Reason; return CanCastSkill(Reason); })
				.ToolTipText_Lambda([this]()
				{
					const cw::GameData* D = Data();
					const FCWTeamNetState* S = TeamState(MyTeam());
					const ACWPlayerController* PC = Controller.Get();
					const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
					if (!D || !S || !Sys)
					{
						return FText::GetEmpty();
					}
					const int32 Skill = D->SkillForAge(S->Age);
					if (Skill < 0)
					{
						return FText::GetEmpty();
					}
					const cw::SkillDef& K = D->Skills[Skill];
					return FText::FromString(FString::Printf(TEXT("%s\n%s\n\n伤害 %.0f（%s）  半径 %.0f\n预警 %.1f 秒  冷却 %.0f 秒"),
						*CWUIText::FromUtf8(K.DisplayName).ToString(), *Sys->GetSkillDescription(Skill).ToString(), K.Damage,
						*CWUIText::DamageTypeName(K.DmgType).ToString(), K.Radius, K.Delay, K.Cooldown));
				})
				.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnSkill))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Font(CWUI::Font(14, true))
						.ColorAndOpacity(CWUI::TextMain)
						.Text_Lambda([this]()
						{
							const cw::GameData* D = Data();
							const FCWTeamNetState* S = TeamState(MyTeam());
							const int32 Skill = D && S ? D->SkillForAge(S->Age) : -1;
							return Skill >= 0 ? FText::Format(LOCTEXT("SkillLabel", "Q  {0}"), CWUIText::FromUtf8(D->Skills[Skill].DisplayName)) : FText::GetEmpty();
						})
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 4.f)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(15, true))
						.ColorAndOpacity(CWUI::Gold)
						.Text_Lambda([this]()
						{
							const cw::GameData* D = Data();
							const FCWTeamNetState* S = TeamState(MyTeam());
							const int32 Skill = D && S ? D->SkillForAge(S->Age) : -1;
							return Skill >= 0 ? FText::Format(LOCTEXT("SkillCost", "{0} 金"), FText::AsNumber(D->Skills[Skill].Cost)) : FText::GetEmpty();
						})
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Font(CWUI::Font(12))
						.ColorAndOpacity(CWUI::Bad)
						.AutoWrapText(true)
						.Text_Lambda([this]() { FText Reason; CanCastSkill(Reason); return Reason; })
					]
				]
			]
			// 冷却进度沿底边收缩；文字始终可读。
			+ SOverlay::Slot().HAlign(HAlign_Left).VAlign(VAlign_Bottom)
			[
				SNew(SBox)
				.Visibility(EVisibility::HitTestInvisible)
				.HeightOverride(4.f)
				.WidthOverride_Lambda([CooldownRatio]() { return FOptionalSize(144.f * CooldownRatio()); })
				[
					SNew(SImage).Image(CWUI::WhiteBrush()).ColorAndOpacity(CWUI::Gold)
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeEconomyButton()
{
	return SNew(SBox)
		.WidthOverride(204.f)
		.HeightOverride(64.f)
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.IsEnabled_Lambda([this]() { FText Reason; return CanUpgradeEconomy(Reason); })
			.ToolTipText_Lambda([this]()
			{
				const cw::GameData* D = Data();
				const FCWTeamNetState* S = TeamState(MyTeam());
				const ACWGameState* G = GS();
				if (!D || !S || !G || S->Age >= D->Ages.size())
				{
					return FText::GetEmpty();
				}
				const float Base = D->Ages[S->Age].IncomePerSec * CWHud_IncomeFactor(*D, *S, *G);
				const float Now = Base * (1.f + D->Rules.EconomyIncomeBonus * S->EconomyLevel);
				if (S->EconomyLevel >= D->Rules.EconomyMaxLevel)
				{
					return FText::Format(LOCTEXT("EcoMaxTip", "金矿已满级：基础收入 +{0}%（当前 {1}/秒）"),
						FText::AsNumber(FMath::RoundToInt(D->Rules.EconomyIncomeBonus * 100.f * S->EconomyLevel)), CWHud_RateText(Now));
				}
				const int32 Cost = D->Rules.EconomyBaseCost * (S->EconomyLevel + 1);
				const float Gain = Base * D->Rules.EconomyIncomeBonus;
				if (Gain <= KINDA_SMALL_NUMBER)
				{
					return LOCTEXT("EcoNoIncomeTip", "当前阶段金币收入已停止，升级金矿不会产生额外收入。");
				}
				return FText::Format(LOCTEXT("EcoTip", "升级金矿：基础收入再 +{0}%（{1}/秒 → {2}/秒），约 {3} 秒回本。\n经济与军队的取舍：越早投资回报越多，但会暂时减少兵力。"),
					FText::AsNumber(FMath::RoundToInt(D->Rules.EconomyIncomeBonus * 100.f)), CWHud_RateText(Now),
					CWHud_RateText(Now + Gain), FText::AsNumber(FMath::RoundToInt(Cost / FMath::Max(Gain, 0.1f))));
			})
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnUpgradeEconomy))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(14, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([this]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						const cw::GameData* D = Data();
						const int32 Level = S ? S->EconomyLevel : 0;
						return Level > 0 && D ? FText::Format(LOCTEXT("EcoLevelBonus", "E  金矿 {0} 级  +{1}%"), FText::AsNumber(Level),
						                                       FText::AsNumber(FMath::RoundToInt(D->Rules.EconomyIncomeBonus * 100.f * Level)))
						                      : FText::Format(LOCTEXT("EcoLevel", "E  金矿 {0} 级"), FText::AsNumber(Level));
					})
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.ColorAndOpacity(CWUI::Gold)
					.Text_Lambda([this]()
					{
						const cw::GameData* D = Data();
						const FCWTeamNetState* S = TeamState(MyTeam());
						if (!D || !S)
						{
							return FText::GetEmpty();
						}
						if (S->EconomyLevel >= D->Rules.EconomyMaxLevel)
						{
							return LOCTEXT("EcoMax", "已满级");
						}
						return FText::Format(LOCTEXT("EcoCost", "升级 {0} 金"), FText::AsNumber(D->Rules.EconomyBaseCost * (S->EconomyLevel + 1)));
					})
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeStanceButton()
{
	return SNew(SBox)
		.WidthOverride(294.f)
		.HeightOverride(38.f)
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			.IsEnabled_Lambda([this]() { const ACWGameState* G = GS(); return G && G->GetPhase() == ECWMatchPhase::InMatch; })
			.ToolTipText(LOCTEXT("StanceTip", "推进：部队持续向前进攻。\n驻守：部队不越过驻守线，未交战的越线部队后撤，在己方炮塔掩护下集结。\n适合兵力落后或攒钱升级时使用；小地图上的黄线就是驻守线。快捷键 F"))
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnToggleStance))
			[
				SNew(STextBlock)
				.Font(CWUI::Font(13, true))
				.Text_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					return S && S->Stance == 1 ? LOCTEXT("StanceHold", "F  部队驻守 · 点击推进") : LOCTEXT("StanceAdvance", "F  部队推进 · 点击驻守");
				})
				.ColorAndOpacity_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					return FSlateColor(S && S->Stance == 1 ? CWUI::Warning : CWUI::Good);
				})
			]
		];
}

static FLinearColor CWHud_CategoryColor(const FString& Category)
{
	if (Category == TEXT("军事")) return FLinearColor(1.f, 0.48f, 0.38f);
	if (Category == TEXT("经济")) return FLinearColor(1.f, 0.82f, 0.32f);
	if (Category == TEXT("防御")) return FLinearColor(0.45f, 0.75f, 1.f);
	if (Category == TEXT("战术")) return FLinearColor(0.8f, 0.6f, 1.f);
	if (Category == TEXT("统帅")) return FLinearColor(1.f, 0.66f, 0.2f);
	return FLinearColor(0.85f, 0.85f, 0.85f);
}

TSharedRef<SWidget> SCWBattleHud::MakeChampionAbilityButton()
{
	return SNew(SBox)
		.WidthOverride(144.f)
		.HeightOverride(60.f)
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.IsEnabled_Lambda([this]()
			{
				const ACWGameState* G = GS();
				const FCWTeamNetState* S = TeamState(MyTeam());
				return G && S && G->GetPhase() == ECWMatchPhase::InMatch && S->ChampionId >= 0 && S->ChampionCooldown <= 0.f;
			})
			.ToolTipText_Lambda([this]()
			{
				const FCWTeamNetState* S = TeamState(MyTeam());
				const ACWPlayerController* PC = Controller.Get();
				const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
				if (!S || !Sys || S->ChampionDef < 0)
				{
					return FText::GetEmpty();
				}
				return FText::Format(LOCTEXT("ChampionAbilityTip", "{0}（快捷键 R）\n{1}\n\n{2}"), Sys->GetChampionAbilityName(S->ChampionDef),
					Sys->GetChampionAbilityDescription(S->ChampionDef), Sys->GetChampionDescription(S->ChampionDef));
			})
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnChampionAbility))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([this]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						const ACWPlayerController* PC = Controller.Get();
						const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
						return S && Sys && S->ChampionDef >= 0 ? FText::Format(LOCTEXT("ChampionAbilityName", "R  {0}"), Sys->GetChampionAbilityName(S->ChampionDef))
						                                       : LOCTEXT("NoChampionAbility", "统帅技能");
					})
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.Text_Lambda([this]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						if (!S)
						{
							return FText::GetEmpty();
						}
						if (S->ChampionId < 0)
						{
							return FText::Format(LOCTEXT("ChampionRespawning", "阵亡 · {0} 秒"), FText::AsNumber(FMath::CeilToInt(FMath::Max(S->ChampionRespawn, 0.f))));
						}
						return S->ChampionCooldown > 0.f ? FText::Format(LOCTEXT("ChampionCooldown", "冷却 {0} 秒"), FText::AsNumber(FMath::CeilToInt(S->ChampionCooldown)))
						                                 : LOCTEXT("ChampionReady", "就绪");
					})
					.ColorAndOpacity_Lambda([this]()
					{
						const FCWTeamNetState* S = TeamState(MyTeam());
						return FSlateColor(!S || S->ChampionId < 0 ? CWUI::Bad : (S->ChampionCooldown > 0.f ? CWUI::TextDim : CWUI::Good));
					})
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeChampionOrderButton()
{
	return SNew(SBox)
		.WidthOverride(144.f)
		.HeightOverride(34.f)
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.HAlign(HAlign_Center)
			.VAlign(VAlign_Center)
			.IsEnabled_Lambda([this]() { const ACWGameState* G = GS(); return G && G->GetPhase() == ECWMatchPhase::InMatch; })
			.ToolTipText(LOCTEXT("ChampionOrderTip", "随军：统帅跟随己方最前方的部队作战。\n坚守：统帅停在指定位置；在战场上点右键即可让统帅坚守到该处（也能用来撤退回城休整）。\n统帅在城门附近且周围没有敌人时会快速回血。快捷键 G 切换，C 让镜头对准统帅。"))
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnToggleChampionOrder))
			[
				SNew(STextBlock)
				.Font(CWUI::Font(12, true))
				.Text_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					return S && S->ChampionOrder == 1 ? LOCTEXT("ChampionHolding", "G  统帅坚守") : LOCTEXT("ChampionFollowing", "G  统帅随军");
				})
				.ColorAndOpacity_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					return FSlateColor(S && S->ChampionOrder == 1 ? CWUI::Warning : CWUI::Good);
				})
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeDoctrinePanel()
{
	TSharedRef<SHorizontalBox> Options = SNew(SHorizontalBox);
	for (int32 I = 0; I < 3; ++I)
	{
		Options->AddSlot().AutoWidth().Padding(6.f, 0.f)[MakeDoctrineOption(I)];
	}
	return SNew(SCWEpicFrame)
		.BorderImage(CWUI::PanelBrush())
		.Padding(FMargin(14.f, 10.f))
		.Visibility_Lambda([this]()
		{
			const ACWGameState* G = GS();
			const FCWTeamNetState* S = TeamState(MyTeam());
			return G && S && G->GetPhase() == ECWMatchPhase::InMatch && S->Offer.Num() > 0 ? EVisibility::Visible : EVisibility::Collapsed;
		})
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 0.f, 0.f, 8.f)
			[
				SNew(STextBlock)
				.Font(CWUI::Font(18, true, true))
				.ColorAndOpacity(CWUI::Gold)
				.Text_Lambda([this]()
				{
					const FCWTeamNetState* S = TeamState(MyTeam());
					const int32 Number = S ? S->Doctrines.Num() + 1 : 1;
					const int32 Pending = S ? S->PendingPicks : 0;
					return Pending > 1
						? FText::Format(LOCTEXT("DoctrineTitleMulti", "选择国策 · 第 {0} 项（还有 {1} 次选择）— 永久生效，可叠加"), FText::AsNumber(Number), FText::AsNumber(Pending - 1))
						: FText::Format(LOCTEXT("DoctrineTitle", "选择国策 · 第 {0} 项 — 永久生效，可叠加"), FText::AsNumber(Number));
				})
			]
			+ SVerticalBox::Slot().AutoHeight()
			[
				Options
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeDoctrineOption(int32 Index)
{
	auto DoctrineAt = [this, Index]() -> int32
	{
		const FCWTeamNetState* S = TeamState(MyTeam());
		return S && S->Offer.IsValidIndex(Index) ? static_cast<int32>(S->Offer[Index]) : -1;
	};
	auto Sys = [this]() -> const UCWGameDataSubsystem*
	{
		const ACWPlayerController* PC = Controller.Get();
		return PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	};
	return SNew(SBox)
		.WidthOverride(250.f)
		.MinDesiredHeight(188.f)
		.Visibility_Lambda([DoctrineAt]() { return DoctrineAt() >= 0 ? EVisibility::Visible : EVisibility::Collapsed; })
		[
			SNew(SCWCommandButton)
			.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
			.ContentPadding(FMargin(2.f, 4.f))
			.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnChooseDoctrine, Index))
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 2.f)
				[
					SNew(STextBlock)
					.Font(CWUI::Font(19, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Text_Lambda([DoctrineAt, Sys]()
					{
						const UCWGameDataSubsystem* S = Sys();
						return S && DoctrineAt() >= 0 ? S->GetDoctrineName(DoctrineAt()) : FText::GetEmpty();
					})
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock)
						.Font(CWUI::Font(12, true))
						.Text_Lambda([DoctrineAt, Sys]()
						{
							const UCWGameDataSubsystem* S = Sys();
							return S && DoctrineAt() >= 0 ? FText::Format(LOCTEXT("DoctrineCategory", "【{0}】"), S->GetDoctrineCategory(DoctrineAt())) : FText::GetEmpty();
						})
						.ColorAndOpacity_Lambda([DoctrineAt, Sys]()
						{
							const UCWGameDataSubsystem* S = Sys();
							return FSlateColor(S && DoctrineAt() >= 0 ? CWHud_CategoryColor(S->GetDoctrineCategory(DoctrineAt()).ToString()) : FLinearColor::White);
						})
					]
					+ SHorizontalBox::Slot().AutoWidth().Padding(6.f, 0.f, 0.f, 0.f)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(12))
						.ColorAndOpacity(CWUI::TextDim)
						.Text_Lambda([DoctrineAt, Sys]()
						{
							const UCWGameDataSubsystem* S = Sys();
							if (!S || DoctrineAt() < 0)
							{
								return FText::GetEmpty();
							}
							switch (S->GetData().Doctrines[DoctrineAt()].Target)
							{
							case cw::DoctrineTarget::All: return LOCTEXT("TargetAll", "全军");
							case cw::DoctrineTarget::Melee: return LOCTEXT("TargetMelee", "近战");
							case cw::DoctrineTarget::Ranged: return LOCTEXT("TargetRanged", "远程");
							case cw::DoctrineTarget::Heavy: return LOCTEXT("TargetHeavy", "重型");
							default: return FText::GetEmpty();
							}
						})
					]
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(STextBlock)
					.Font(CWUI::Font(13))
					.AutoWrapText(true)
					.WrapTextAt(226.f)
					.ColorAndOpacity(CWUI::TextDim)
					.Text_Lambda([DoctrineAt, Sys]()
					{
						const UCWGameDataSubsystem* S = Sys();
						return S && DoctrineAt() >= 0 ? S->GetDoctrineDescription(DoctrineAt()) : FText::GetEmpty();
					})
				]
			]
		];
}

FReply SCWBattleHud::OnChooseDoctrine(int32 Index)
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestChooseDoctrine(Index);
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnChampionAbility()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestChampionAbility();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnLastStand()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestLastStand();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnToggleChampionOrder()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->ToggleChampionOrder();
	}
	return FReply::Handled();
}

void SCWBattleHud::UpdateNotifications()
{
	const ACWGameState* G = GS();
	const ACWPlayerController* PC = Controller.Get();
	const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
	if (!G || !Sys || G->GetPhase() != ECWMatchPhase::InMatch)
	{
		bTrackerReady = false;
		return;
	}
	for (int32 Team = 0; Team < 2; ++Team)
	{
		const FCWTeamNetState& S = G->GetTeam(Team);
		if (bTrackerReady)
		{
			const bool bMine = Team == MyTeam();
			if (!bMine && S.Doctrines.Num() > SeenDoctrines[Team])
			{
				ShowToast(FText::Format(LOCTEXT("EnemyDoctrine", "敌方采用国策：{0}"), Sys->GetDoctrineName(S.Doctrines.Last())), true);
			}
			if (!SeenLastStand[Team] && S.bLastStandUsed)
			{
				ShowToast(bMine ? LOCTEXT("MyLastStand", "背水一战！民兵出阵，全军鼓舞，炮塔强化") : LOCTEXT("EnemyLastStand", "敌方发动背水一战！小心反扑"), !bMine);
			}
			if (SeenChampionId[Team] >= 0 && S.ChampionId < 0)
			{
				ShowToast(bMine ? FText::Format(LOCTEXT("MyChampionDied", "我方统帅阵亡！{0} 秒后复活"), FText::AsNumber(FMath::CeilToInt(S.ChampionRespawn)))
				                : LOCTEXT("EnemyChampionDied", "击杀敌方统帅！获得赏金"), bMine);
			}
		}
		SeenDoctrines[Team] = S.Doctrines.Num();
		SeenChampionId[Team] = S.ChampionId;
		SeenLastStand[Team] = S.bLastStandUsed;
	}
	bTrackerReady = true;
}

bool SCWBattleHud::CanUpgradeEconomy(FText& OutReason) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(MyTeam());
	const ACWGameState* G = GS();
	if (!D || !S || !G || G->GetPhase() != ECWMatchPhase::InMatch)
	{
		return false;
	}
	if (S->EconomyLevel >= D->Rules.EconomyMaxLevel)
	{
		OutReason = LOCTEXT("EcoMaxReason", "金矿已满级");
		return false;
	}
	const int32 Cost = D->Rules.EconomyBaseCost * (S->EconomyLevel + 1);
	if (S->Gold < Cost)
	{
		OutReason = FText::Format(LOCTEXT("EcoNeedGold", "金币不足 差{0}"), FText::AsNumber(Cost - S->Gold));
		return false;
	}
	return true;
}

FReply SCWBattleHud::OnUpgradeEconomy()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestUpgradeEconomy();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnToggleStance()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->ToggleStance();
	}
	return FReply::Handled();
}

bool SCWBattleHud::IsTurretPhaseAllowed() const
{
	const ACWPlayerController* PC = Controller.Get();
	return PC && PC->CanUseBattleInput();
}

FText SCWBattleHud::TurretPhaseReason() const
{
	const ACWGameState* G = GS();
	if (G && G->GetPhase() == ECWMatchPhase::PostMatch)
		return LOCTEXT("TurretAfterMatch", "对局已结束，无法操作炮塔");
	if (G && G->GetPhase() == ECWMatchPhase::InMatch)
		return LOCTEXT("TurretMenuOpen", "关闭声音与战局菜单后可操作炮塔");
	return LOCTEXT("TurretBeforeMatch", "战斗开始后可建造、升级或出售炮塔");
}

TSharedRef<SWidget> SCWBattleHud::MakeTurretSlot(int32 Slot)
{
	// 炮塔槽状态：0 = 不存在, 1 = 未解锁, 2 = 空, 3 = 已建造
	auto SlotState = [this, Slot]()
	{
		const FCWTeamNetState* S = TeamState(MyTeam());
		if (!S || Slot >= S->Turrets.Num())
		{
			return 0;
		}
		const FCWTurretNetSlot& T = S->Turrets[Slot];
		return !T.bUnlocked ? 1 : (T.Def < 0 ? 2 : 3);
	};
	auto UnlockedCount = [this]()
	{
		const FCWTeamNetState* S = TeamState(MyTeam());
		int32 Count = 0;
		if (S)
		{
			for (const FCWTurretNetSlot& T : S->Turrets)
			{
				Count += T.bUnlocked ? 1 : 0;
			}
		}
		return Count;
	};
	auto SlotCost = [this, UnlockedCount]()
	{
		const cw::GameData* D = Data();
		return D ? D->Rules.TurretSlotCostBase * FMath::Max(UnlockedCount() - D->Rules.InitialTurretSlots + 1, 1) : 0;
	};
	auto UpgradeCost = [this, Slot]()
	{
		const cw::GameData* D = Data();
		const FCWTeamNetState* S = TeamState(MyTeam());
		if (!D || !S || Slot >= S->Turrets.Num() || S->Turrets[Slot].Def < 0)
		{
			return -1;
		}
		const FCWTurretNetSlot& T = S->Turrets[Slot];
		const cw::TurretDef& Def = D->Turrets[T.Def];
		return T.Level >= Def.MaxLevel ? -1 : FMath::RoundToInt(Def.Cost * Def.UpgradeCostRatio * T.Level);
	};

	return SNew(SBox)
		.WidthOverride(92.f)
		.HeightOverride(132.f)
		[
			SNew(SVerticalBox)
			+ SVerticalBox::Slot().FillHeight(1.f)
			[
				SNew(SCWCommandButton)
				.ContentPadding(FMargin(3.f))
				.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
				.HAlign(HAlign_Center)
				.VAlign(VAlign_Center)
				.IsEnabled_Lambda([this, Slot, SlotState, UnlockedCount, SlotCost]()
				{
					if (!IsTurretPhaseAllowed()) return false;
					const int32 State = SlotState();
					const FCWTeamNetState* S = TeamState(MyTeam());
					if (State == 1)
					{
						return Slot == UnlockedCount() && S && S->Gold >= SlotCost();
					}
					return State == 2;
				})
				.ToolTipText_Lambda([this, Slot, SlotState]()
				{
					if (!IsTurretPhaseAllowed()) return TurretPhaseReason();
					const cw::GameData* D = Data();
					const FCWTeamNetState* S = TeamState(MyTeam());
					const ACWPlayerController* PC = Controller.Get();
					const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
					if (SlotState() == 3 && D && S && Sys)
					{
						const FCWTurretNetSlot& T = S->Turrets[Slot];
						return CWUIText::TurretTooltip(D->Turrets[T.Def], Sys->GetTurretDescription(T.Def), T.Level);
					}
					return SlotState() == 1 ? LOCTEXT("SlotTip", "购买新的炮塔槽位（需按顺序解锁）") : LOCTEXT("BuildTip", "选择要建造的炮塔");
				})
				.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnTurretSlotClicked, Slot))
				[
					SNew(STextBlock)
					.Font(CWUI::Font(12, true))
					.ColorAndOpacity(CWUI::TextMain)
					.Justification(ETextJustify::Center)
					.Text_Lambda([this, Slot, SlotState, UnlockedCount, SlotCost]()
					{
						const cw::GameData* D = Data();
						const FCWTeamNetState* S = TeamState(MyTeam());
						if (!D || !S)
						{
							return FText::GetEmpty();
						}
						switch (SlotState())
						{
						case 1:
							return Slot == UnlockedCount() ? FText::Format(LOCTEXT("UnlockSlot", "解锁槽位\n{0} 金"), FText::AsNumber(SlotCost()))
							                               : LOCTEXT("Locked", "未解锁");
						case 2:
							return LOCTEXT("EmptySlot", "建造炮塔");
						case 3:
						{
							const FCWTurretNetSlot& T = S->Turrets[Slot];
							return FText::Format(LOCTEXT("TurretLevel", "{0}\n{1} 级"), CWUIText::FromUtf8(D->Turrets[T.Def].DisplayName), FText::AsNumber(T.Level));
						}
						default:
							return FText::GetEmpty();
						}
					})
				]
			]
			+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f, 0.f, 0.f)
			[
				SNew(SVerticalBox)
				.Visibility_Lambda([SlotState]() { return SlotState() == 3 ? EVisibility::Visible : EVisibility::Collapsed; })
				+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 3.f)
				[
					SNew(SCWCommandButton)
					.ButtonStyle(&CWUI::CompactButtonStyle(CWUI::EButtonKind::Primary))
					.ContentPadding(FMargin(1.f))
					.HAlign(HAlign_Center)
					.IsEnabled_Lambda([this, UpgradeCost]()
					{
						if (!IsTurretPhaseAllowed()) return false;
						const FCWTeamNetState* S = TeamState(MyTeam());
						const int32 Cost = UpgradeCost();
						return S && Cost > 0 && S->Gold >= Cost;
					})
					.ToolTipText_Lambda([this, UpgradeCost]()
					{
						if (!IsTurretPhaseAllowed()) return TurretPhaseReason();
						const int32 Cost = UpgradeCost();
						return Cost > 0 ? FText::Format(LOCTEXT("UpgradeTip", "升级炮塔：花费 {0} 金，伤害 +30%，射程 +8%"), FText::AsNumber(Cost))
							                : LOCTEXT("UpgradeMaxTip", "炮塔已满级");
					})
					.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnTurretUpgrade, Slot))
					[
						SNew(STextBlock)
						.Font(CWUI::Font(11, true))
						.ColorAndOpacity(CWUI::TextMain)
						.Text_Lambda([UpgradeCost]()
						{
							const int32 Cost = UpgradeCost();
							return Cost > 0 ? FText::Format(LOCTEXT("Upgrade", "升级 {0}"), FText::AsNumber(Cost)) : LOCTEXT("MaxLv", "满级");
						})
					]
				]
				+ SVerticalBox::Slot().AutoHeight()
				[
					SNew(SCWCommandButton)
					.ButtonStyle(&CWUI::CompactButtonStyle(CWUI::EButtonKind::Danger))
					.ContentPadding(FMargin(1.f))
					.HAlign(HAlign_Center)
					.IsEnabled_Lambda([this]() { return IsTurretPhaseAllowed(); })
					.ToolTipText_Lambda([this]() { return IsTurretPhaseAllowed() ? LOCTEXT("SellTip", "出售炮塔：返还累计投入的一半金币，槽位保留") : TurretPhaseReason(); })
					.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnTurretSell, Slot))
					[
						SNew(STextBlock)
						.Font(CWUI::Font(11, true))
						.ColorAndOpacity(CWUI::TextMain)
						.Text_Lambda([this, Slot]()
						{
							const cw::GameData* D = Data();
							const FCWTeamNetState* S = TeamState(MyTeam());
							if (!D || !S || Slot >= S->Turrets.Num())
							{
								return FText::GetEmpty();
							}
							return FText::Format(LOCTEXT("Sell", "出售 {0}"), FText::AsNumber(FMath::RoundToInt(S->Turrets[Slot].Invested * D->Rules.SellRefundRatio)));
						})
					]
				]
			]
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeBuildMenu()
{
	TSharedRef<SHorizontalBox> Row = SNew(SHorizontalBox);
	const cw::GameData* D = Data();
	const int32 Count = D ? static_cast<int32>(D->Turrets.size()) : 0;
	for (int32 I = 0; I < Count; ++I)
	{
		Row->AddSlot().AutoWidth().Padding(3.f, 0.f)
		[
			SNew(SBox)
			.WidthOverride(120.f)
			.HeightOverride(64.f)
			// 只列出当前与上一个时代的炮塔，保持菜单紧凑
			.Visibility_Lambda([this, I]()
			{
				const cw::GameData* GD = Data();
				const FCWTeamNetState* S = TeamState(MyTeam());
				return GD && S && GD->Turrets[I].Age <= S->Age && GD->Turrets[I].Age >= S->Age - 1 ? EVisibility::Visible : EVisibility::Collapsed;
			})
			[
				SNew(SCWCommandButton)
				.ButtonStyle(&CWUI::ButtonStyle(CWUI::EButtonKind::Normal))
				.IsEnabled_Lambda([this, I]()
				{
					if (!IsTurretPhaseAllowed()) return false;
					const cw::GameData* GD = Data();
					const FCWTeamNetState* S = TeamState(MyTeam());
					return GD && S && GD->Turrets[I].Age <= S->Age && S->Gold >= GD->Turrets[I].Cost;
				})
				.ToolTipText_Lambda([this, I]()
				{
					if (!IsTurretPhaseAllowed()) return TurretPhaseReason();
					const cw::GameData* GD = Data();
					const ACWPlayerController* PC = Controller.Get();
					const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
					return GD && Sys ? CWUIText::TurretTooltip(GD->Turrets[I], Sys->GetTurretDescription(I), 1) : FText::GetEmpty();
				})
				.OnClicked(FOnClicked::CreateSP(this, &SCWBattleHud::OnBuildTurret, I))
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Font(CWUI::Font(13, true))
						.ColorAndOpacity(CWUI::TextMain)
						.Text_Lambda([this, I]() { const cw::GameData* GD = Data(); return GD ? CWUIText::FromUtf8(GD->Turrets[I].DisplayName) : FText::GetEmpty(); })
					]
					+ SVerticalBox::Slot().AutoHeight()
					[
						SNew(STextBlock)
						.Font(CWUI::Font(12))
						.Text_Lambda([this, I]()
						{
							const cw::GameData* GD = Data();
							const FCWTeamNetState* S = TeamState(MyTeam());
							if (!GD || !S)
							{
								return FText::GetEmpty();
							}
							if (GD->Turrets[I].Age > S->Age)
							{
								return FText::Format(LOCTEXT("NeedAge", "需要{0}"), CWUIText::FromUtf8(GD->Ages[GD->Turrets[I].Age].DisplayName));
							}
							return FText::Format(LOCTEXT("TurretCost", "{0} 金"), FText::AsNumber(GD->Turrets[I].Cost));
						})
						.ColorAndOpacity(CWUI::Gold)
					]
				]
			]
		];
	}
	return SNew(SBorder)
		.BorderImage(CWUI::PanelBrush())
		.Padding(FMargin(8.f))
		.Visibility_Lambda([this]() { return BuildMenuSlot >= 0 ? EVisibility::Visible : EVisibility::Collapsed; })
		[
			Row
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeStatRow(const FText& Label, TFunction<FText(int32 Team)> Value)
{
	return SNew(SHorizontalBox)
		+ SHorizontalBox::Slot().FillWidth(1.f)
		[
			SNew(STextBlock).Text(Label).Font(CWUI::Font(16)).ColorAndOpacity(CWUI::TextDim)
		]
		+ SHorizontalBox::Slot().FillWidth(0.6f).HAlign(HAlign_Right)
		[
			SNew(STextBlock).Font(CWUI::Font(16, true)).ColorAndOpacity(CWUI::TextMain).Text_Lambda([this, Value]() { return Value(MyTeam()); })
		]
		+ SHorizontalBox::Slot().FillWidth(0.6f).HAlign(HAlign_Right)
		[
			SNew(STextBlock).Font(CWUI::Font(16, true)).ColorAndOpacity(CWUI::TextMain).Text_Lambda([this, Value]() { return Value(1 - MyTeam()); })
		];
}

TSharedRef<SWidget> SCWBattleHud::MakeResultPanel()
{
	auto Stat = [this](TFunction<int32(const FCWTeamNetState&)> Getter)
	{
		return [this, Getter](int32 Team)
		{
			const FCWTeamNetState* S = TeamState(Team);
			return S ? FText::AsNumber(Getter(*S)) : FText::GetEmpty();
		};
	};
	return SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		.Visibility_Lambda([this]()
		{
			const ACWGameState* G = GS();
			return G && G->GetPhase() == ECWMatchPhase::PostMatch ? EVisibility::Visible : EVisibility::Collapsed;
		})
		[
			SNew(SBorder)
			.BorderImage(CWUI::PanelBrush())
			.Padding(FMargin(48.f, 32.f))
			[
				SNew(SBox)
				.WidthOverride(560.f)
				[
					SNew(SVerticalBox)
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(64, true, true))
						.Text_Lambda([this]()
						{
							const ACWGameState* G = GS();
							if (G && G->GetWinner() < 0)
							{
								return LOCTEXT("Draw", "平局");
							}
							return G && G->GetWinner() == MyTeam() ? LOCTEXT("Victory", "胜利") : LOCTEXT("Defeat", "失败");
						})
						.ColorAndOpacity_Lambda([this]()
						{
							const ACWGameState* G = GS();
							if (G && G->GetWinner() < 0)
							{
								return FSlateColor(CWUI::TextMain);
							}
							return FSlateColor(G && G->GetWinner() == MyTeam() ? CWUI::Gold : CWUI::Bad);
						})
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 4.f, 0.f, 20.f)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(18))
						.ColorAndOpacity(CWUI::TextDim)
						.Text_Lambda([this]()
						{
							const ACWGameState* G = GS();
							if (!G)
							{
								return FText::GetEmpty();
							}
							const bool bWin = G->GetWinner() == MyTeam();
							if (G->GetEndReason() == ECWEndReason::TimeLimit)
							{
								const FCWTeamNetState& A = G->GetTeam(0);
								const FCWTeamNetState& B = G->GetTeam(1);
								const CWFrontend::ETimeDecision Decision = CWFrontend::TimeDecision(A.BaseHp, A.BaseMaxHp, A.Kills, B.BaseHp, B.BaseMaxHp, B.Kills);
								if (G->GetWinner() < 0) return LOCTEXT("TimeDraw", "时间到：双方基地生命比例与击杀数相同");
								if (Decision == CWFrontend::ETimeDecision::Kills)
									return bWin ? LOCTEXT("TimeKillWin", "时间到：基地生命比例相同，我方击杀数更多") : LOCTEXT("TimeKillLose", "时间到：基地生命比例相同，敌方击杀数更多");
								return bWin ? LOCTEXT("TimeWin", "时间到：我方基地剩余生命比例更高") : LOCTEXT("TimeLose", "时间到：敌方基地剩余生命比例更高");
							}
							if (G->GetEndReason() == ECWEndReason::Forfeit)
							{
								return bWin ? LOCTEXT("OppLeft", "对手离开了对局") : LOCTEXT("YouLeft", "你离开了对局");
							}
							return FText::Format(bWin ? LOCTEXT("WinBase", "摧毁了敌方基地 · 用时 {0}") : LOCTEXT("LoseBase", "我方基地被摧毁 · 用时 {0}"),
								CWUIText::Clock(G->GetMatchTime()));
						})
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 0.f, 0.f, 6.f)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().FillWidth(1.f)[SNew(SSpacer)]
						+ SHorizontalBox::Slot().FillWidth(0.6f).HAlign(HAlign_Right)
						[
							SNew(STextBlock).Text(LOCTEXT("StatMine", "我方")).Font(CWUI::Font(16, true)).ColorAndOpacity_Lambda([this]() { return FSlateColor(CWUI::TeamColor(MyTeam())); })
						]
						+ SHorizontalBox::Slot().FillWidth(0.6f).HAlign(HAlign_Right)
						[
							SNew(STextBlock).Text(LOCTEXT("StatEnemy", "敌方")).Font(CWUI::Font(16, true)).ColorAndOpacity_Lambda([this]() { return FSlateColor(CWUI::TeamColor(1 - MyTeam())); })
						]
					]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatTrained", "训练单位"), Stat([](const FCWTeamNetState& S) { return S.UnitsTrained; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatKills", "击杀"), Stat([](const FCWTeamNetState& S) { return S.Kills; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatLost", "损失"), Stat([](const FCWTeamNetState& S) { return S.UnitsLost; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatGold", "花费金币"), Stat([](const FCWTeamNetState& S) { return S.GoldSpent; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatBase", "对基地伤害"), Stat([](const FCWTeamNetState& S) { return FMath::RoundToInt(S.DamageToBase); }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatPromotions", "老兵晋升"), Stat([](const FCWTeamNetState& S) { return S.Promotions; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)[MakeStatRow(LOCTEXT("StatChampionKills", "击杀统帅"), Stat([](const FCWTeamNetState& S) { return S.ChampionKills; }))]
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 3.f)
					[
						MakeStatRow(LOCTEXT("StatAge", "最终时代"), [this](int32 Team)
						{
							const cw::GameData* D = Data();
							const FCWTeamNetState* S = TeamState(Team);
							return D && S && S->Age < D->Ages.size() ? CWUIText::FromUtf8(D->Ages[S->Age].DisplayName) : FText::GetEmpty();
						})
					]
					// 本局双方的国策路线
					+ SVerticalBox::Slot().AutoHeight().Padding(0.f, 12.f, 0.f, 0.f)
					[
						SNew(STextBlock)
						.Font(CWUI::Font(14))
						.AutoWrapText(true)
						.ColorAndOpacity(FLinearColor(1.f, 0.85f, 0.55f))
						.Text_Lambda([this]()
						{
							const ACWPlayerController* PC = Controller.Get();
							const UCWGameDataSubsystem* Sys = PC && PC->GetGameInstance() ? PC->GetGameInstance()->GetSubsystem<UCWGameDataSubsystem>() : nullptr;
							const FCWTeamNetState* Mine = TeamState(MyTeam());
							const FCWTeamNetState* Theirs = TeamState(1 - MyTeam());
							if (!Sys || !Mine || !Theirs || Sys->GetData().Doctrines.empty())
							{
								return FText::GetEmpty();
							}
							return FText::Format(LOCTEXT("ResultDoctrines", "我方国策：{0}\n敌方国策：{1}"),
								FText::FromString(CWHud_DoctrineNames(*Sys, *Mine)), FText::FromString(CWHud_DoctrineNames(*Sys, *Theirs)));
						})
					]
					+ SVerticalBox::Slot().AutoHeight().HAlign(HAlign_Center).Padding(0.f, 24.f, 0.f, 0.f)
					[
						SNew(SHorizontalBox)
						+ SHorizontalBox::Slot().AutoWidth().Padding(6.f, 0.f)
						[
							SNew(SBox)
							.Visibility_Lambda([this]() { const ACWGameState* G = GS(); return G && G->bSinglePlayer ? EVisibility::Visible : EVisibility::Collapsed; })
							[
								CWUI::MakeButton(LOCTEXT("Rematch", "再来一局"), FOnClicked::CreateSP(this, &SCWBattleHud::OnRematch), CWUI::EButtonKind::Primary, 170.f)
							]
						]
						+ SHorizontalBox::Slot().AutoWidth().Padding(6.f, 0.f)
						[
							SNew(SBox)
							.Visibility_Lambda([this]() { const ACWGameState* G = GS(); return G && !G->bSinglePlayer ? EVisibility::Visible : EVisibility::Collapsed; })
							[
								CWUI::MakeButton(LOCTEXT("BackLobby", "返回房间"), FOnClicked::CreateSP(this, &SCWBattleHud::OnBackToLobby), CWUI::EButtonKind::Primary, 170.f)
							]
						]
						+ SHorizontalBox::Slot().AutoWidth().Padding(6.f, 0.f)
						[
							CWUI::MakeButton(LOCTEXT("MainMenu", "返回主菜单"), FOnClicked::CreateSP(this, &SCWBattleHud::OnMainMenu), CWUI::EButtonKind::Normal, 170.f)
						]
					]
				]
			]
		];
}

// ---------------------------------------------------------------------------
// 可操作性判断（仅界面提示）
// ---------------------------------------------------------------------------
bool SCWBattleHud::CanTrain(int32 Slot, FText& OutReason) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(MyTeam());
	const ACWGameState* G = GS();
	if (!D || !S || !G)
	{
		return false;
	}
	if (G->GetPhase() != ECWMatchPhase::InMatch)
	{
		OutReason = LOCTEXT("NotStarted", "对局未开始");
		return false;
	}
	const int32 Def = UnitDefForSlot(Slot);
	if (Def < 0)
	{
		return false;
	}
	if (S->Queue.Num() >= D->Rules.QueueCapacity)
	{
		OutReason = LOCTEXT("QFull", "队列已满");
		return false;
	}
	const int32 Cost = EffectiveCost(MyTeam(), Def);
	if (S->Gold < Cost)
	{
		OutReason = FText::Format(LOCTEXT("NeedGold", "金币不足 差{0}"), FText::AsNumber(Cost - S->Gold));
		return false;
	}
	return true;
}

bool SCWBattleHud::CanUpgradeAge(FText& OutReason) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(MyTeam());
	const ACWGameState* G = GS();
	if (!D || !S || !G)
	{
		return false;
	}
	if (G->GetPhase() != ECWMatchPhase::InMatch)
	{
		OutReason = LOCTEXT("NotStarted2", "对局未开始");
		return false;
	}
	if (S->bUpgrading)
	{
		OutReason = FText::Format(LOCTEXT("Upgrading", "进化中，剩余 {0} 秒"), FText::AsNumber(FMath::CeilToInt(S->UpgradeTimeLeft)));
		return false;
	}
	const int32 Next = S->Age + 1;
	if (Next >= static_cast<int32>(D->Ages.size()))
	{
		OutReason = LOCTEXT("AgeMaxReason", "已是最高时代");
		return false;
	}
	const cw::AgeDef& A = D->Ages[Next];
	if (!A.Implemented)
	{
		OutReason = LOCTEXT("NotImplemented", "该时代尚未实装（规划中）");
		return false;
	}
	if (S->Xp < A.XpToEnter)
	{
		OutReason = FText::Format(LOCTEXT("NeedXp", "经验不足（差 {0}）"), FText::AsNumber(A.XpToEnter - S->Xp));
		return false;
	}
	if (S->Gold < A.GoldToEnter)
	{
		OutReason = FText::Format(LOCTEXT("NeedGold2", "金币不足（差 {0}）"), FText::AsNumber(A.GoldToEnter - S->Gold));
		return false;
	}
	return true;
}

bool SCWBattleHud::CanCastSkill(FText& OutReason) const
{
	const cw::GameData* D = Data();
	const FCWTeamNetState* S = TeamState(MyTeam());
	const ACWGameState* G = GS();
	if (!D || !S || !G)
	{
		return false;
	}
	if (G->GetPhase() != ECWMatchPhase::InMatch)
	{
		OutReason = LOCTEXT("NotStarted3", "对局未开始");
		return false;
	}
	const int32 Skill = D->SkillForAge(S->Age);
	if (Skill < 0)
	{
		return false;
	}
	if (S->SkillCooldown > 0.f)
	{
		OutReason = FText::Format(LOCTEXT("Cooldown", "冷却中 {0} 秒"), FText::AsNumber(FMath::CeilToInt(S->SkillCooldown)));
		return false;
	}
	if (S->Gold < D->Skills[Skill].Cost)
	{
		OutReason = FText::Format(LOCTEXT("NeedGold3", "金币不足 差{0}"), FText::AsNumber(D->Skills[Skill].Cost - S->Gold));
		return false;
	}
	return true;
}

// ---------------------------------------------------------------------------
// 交互
// ---------------------------------------------------------------------------
void SCWBattleHud::Tick(const FGeometry& AllottedGeometry, const double InCurrentTime, const float InDeltaTime)
{
	SCompoundWidget::Tick(AllottedGeometry, InCurrentTime, InDeltaTime);
	const ACWGameState* G = GS();
	if (BuildMenuSlot >= 0 && (!G || G->GetPhase() != ECWMatchPhase::InMatch))
	{
		BuildMenuSlot = -1;
	}
	UpdateNotifications();
}

void SCWBattleHud::ShowToast(const FText& Message, bool bError)
{
	ToastText = Message;
	ToastColor = bError ? CWUI::Bad : CWUI::Good;
	ToastTime = FPlatformTime::Seconds();
}

EVisibility SCWBattleHud::GetToastVisibility() const
{
	return !ToastText.IsEmpty() && FPlatformTime::Seconds() - ToastTime < 2.2 ? EVisibility::HitTestInvisible : EVisibility::Collapsed;
}

FReply SCWBattleHud::OnTrain(int32 Slot)
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestTrain(Slot);
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnCancelQueue(int32 Index)
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestCancelTrain(Index);
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnUpgradeAge()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestUpgradeAge();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnSkill()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->BeginSkillTargeting();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnTurretSlotClicked(int32 Slot)
{
	if (!IsTurretPhaseAllowed()) { ShowToast(TurretPhaseReason()); return FReply::Handled(); }
	ACWPlayerController* PC = Controller.Get();
	const FCWTeamNetState* S = TeamState(MyTeam());
	if (!PC || !S || !S->Turrets.IsValidIndex(Slot))
	{
		return FReply::Handled();
	}
	const FCWTurretNetSlot& T = S->Turrets[Slot];
	if (!T.bUnlocked)
	{
		PC->RequestBuyTurretSlot();
	}
	else if (T.Def < 0)
	{
		BuildMenuSlot = BuildMenuSlot == Slot ? -1 : Slot;
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnTurretUpgrade(int32 Slot)
{
	if (!IsTurretPhaseAllowed()) { ShowToast(TurretPhaseReason()); return FReply::Handled(); }
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestUpgradeTurret(Slot);
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnTurretSell(int32 Slot)
{
	if (!IsTurretPhaseAllowed()) { ShowToast(TurretPhaseReason()); return FReply::Handled(); }
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->RequestSellTurret(Slot);
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnBuildTurret(int32 TurretDef)
{
	if (!IsTurretPhaseAllowed()) { CloseBuildMenu(); ShowToast(TurretPhaseReason()); return FReply::Handled(); }
	if (ACWPlayerController* PC = Controller.Get())
	{
		if (BuildMenuSlot >= 0)
		{
			PC->RequestBuildTurret(BuildMenuSlot, TurretDef);
		}
	}
	BuildMenuSlot = -1;
	return FReply::Handled();
}

FReply SCWBattleHud::OnLeaveMatch()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		if (ACWHUD* Hud = Cast<ACWHUD>(PC->GetHUD())) Hud->RequestLeaveMatch();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnFrontendMenu()
{
	if (ACWPlayerController* PC = Controller.Get())
		if (ACWHUD* Hud = Cast<ACWHUD>(PC->GetHUD())) Hud->ToggleFrontendMenu();
	return FReply::Handled();
}

FReply SCWBattleHud::OnRematch()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->ServerRestartSingle();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnBackToLobby()
{
	if (ACWPlayerController* PC = Controller.Get())
	{
		PC->ServerReturnToLobby();
	}
	return FReply::Handled();
}

FReply SCWBattleHud::OnMainMenu()
{
	return OnLeaveMatch();
}

#undef LOCTEXT_NAMESPACE
