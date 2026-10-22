#include "UI/CWUIStyle.h"

#include "Brushes/SlateColorBrush.h"
#include "Brushes/SlateBoxBrush.h"
#include "Brushes/SlateNoResource.h"
#include "Brushes/SlateRoundedBoxBrush.h"
#include "Engine/Texture2D.h"
#include "Fonts/CompositeFont.h"
#include "HAL/FileManager.h"
#include "Misc/Paths.h"
#include "Sound/SlateSound.h"
#include "Sound/SoundBase.h"
#include "Styling/CoreStyle.h"
#include "View/CWAudio.h"

namespace CWUI
{
	const FLinearColor Gold(0.91f, 0.69f, 0.31f);
	const FLinearColor TextMain(0.94f, 0.91f, 0.80f);
	const FLinearColor TextDim(0.68f, 0.74f, 0.66f);
	const FLinearColor TextDisabled(0.56f, 0.61f, 0.55f);
	const FLinearColor Good(0.48f, 0.84f, 0.60f);
	const FLinearColor Bad(1.f, 0.43f, 0.34f);
	const FLinearColor Warning(1.f, 0.73f, 0.31f);

	FLinearColor TeamColor(int32 Team)
	{
		return Team == 0 ? FLinearColor(0.30f, 0.58f, 1.f) : FLinearColor(1.f, 0.36f, 0.30f);
	}

	// 从字体文件创建复合字体（5.8 起不再推荐用文件路径直接构造 FSlateFontInfo）
	static TSharedPtr<const FCompositeFont> MakeFileFont(const FString& Path)
	{
		if (!IFileManager::Get().FileExists(*Path))
		{
			return nullptr;
		}
		// 基于文件的字体不引用 UObject，用普通 FCompositeFont 即可（FStandaloneCompositeFont 带 GC 注册，不适合放在静态变量里）
		return MakeShared<FCompositeFont>(TEXT("Default"), Path, EFontHinting::Default, EFontLoadingPolicy::LazyLoad);
	}

	FSlateFontInfo Font(int32 Size, bool bBold, bool bOutline)
	{
		static const TSharedPtr<const FCompositeFont> Regular = MakeFileFont(FPaths::ProjectContentDir() / TEXT("Fonts/NotoSansSC-Regular.otf"));
		static const TSharedPtr<const FCompositeFont> Bold = MakeFileFont(FPaths::ProjectContentDir() / TEXT("Fonts/NotoSansSC-Bold.otf"));
		const TSharedPtr<const FCompositeFont>& Chosen = bBold && Bold.IsValid() ? Bold : Regular;
		FSlateFontInfo Info = Chosen.IsValid() ? FSlateFontInfo(Chosen, static_cast<float>(Size))
		                                       : FCoreStyle::GetDefaultFontStyle(bBold ? "Bold" : "Regular", Size);
		if (bOutline)
		{
			Info.OutlineSettings.OutlineSize = 1;
			Info.OutlineSettings.OutlineColor = FLinearColor(0.f, 0.f, 0.f, 0.85f);
		}
		return Info;
	}

	const FSlateBrush* PanelBrush()
	{
		static const FSlateRoundedBoxBrush Brush(FLinearColor(0.018f, 0.033f, 0.029f, 0.98f), 4.f, FLinearColor(0.34f, 0.39f, 0.29f), 1.f);
		return &Brush;
	}

	const FSlateBrush* PanelLightBrush()
	{
		static const FSlateRoundedBoxBrush Brush(FLinearColor(0.042f, 0.068f, 0.057f, 1.f), 3.f);
		return &Brush;
	}

	const FSlateBrush* WhiteBrush()
	{
		static const FSlateColorBrush Brush(FLinearColor::White);
		return &Brush;
	}

	const FSlateBrush* RoundedFill()
	{
		static const FSlateRoundedBoxBrush Brush(FLinearColor::White, 4.f);
		return &Brush;
	}

	const FSlateBrush* EpicFrameBrush()
	{
		static const FSlateBrush Brush = []() -> FSlateBrush
		{
			UTexture2D* Texture = LoadObject<UTexture2D>(nullptr, TEXT("/Game/UI/EpicBorders/T_CommandFrame.T_CommandFrame"));
			if (!Texture)
			{
				// Missing optional art must never replace the readable native panel.
				return FSlateNoResource();
			}
			// The static Slate brush is not itself a GC owner. This tiny shared texture
			// lives for the process, like the other shared UI style resources.
			Texture->AddToRoot();
			FSlateBoxBrush Frame(Texture, FMargin(0.25f), FLinearColor(0.64f, 0.46f, 0.21f, 0.92f));
			// The original 48 px source yields 12-unit corners and a 2-unit line.
			Frame.SetImageSize(FVector2f(48.f, 48.f));
			return Frame;
		}();
		return &Brush;
	}

	static FButtonStyle MakeButtonStyle(const FLinearColor& Base, const FLinearColor& Border)
	{
		FButtonStyle Style;
		Style.SetNormal(FSlateRoundedBoxBrush(Base, 3.f, Border, 1.f));
		Style.SetHovered(FSlateRoundedBoxBrush(Base * FLinearColor(1.35f, 1.35f, 1.35f, 1.f) + FLinearColor(0.025f, 0.035f, 0.025f, 0.f), 3.f, Gold, 1.5f));
		Style.SetPressed(FSlateRoundedBoxBrush(Base * FLinearColor(0.7f, 0.7f, 0.7f, 1.f), 3.f, Gold, 1.f));
		Style.SetDisabled(FSlateRoundedBoxBrush(FLinearColor(0.036f, 0.046f, 0.040f, 1.f), 3.f, FLinearColor(0.20f, 0.25f, 0.20f), 1.f));
		Style.SetNormalPadding(FMargin(10.f, 6.f, 10.f, 6.f));
		Style.SetPressedPadding(FMargin(10.f, 7.f, 10.f, 5.f));
		// 按下音效（由 Slate 播放；资源不存在时为空，不影响使用）
		if (USoundBase* Click = CWAudio::Get(CWAudio::ESound::UIClick))
		{
			FSlateSound Sound;
			Sound.SetResourceObject(Click);
			Style.SetPressedSound(Sound);
		}
		return Style;
	}

	const FButtonStyle& ButtonStyle(EButtonKind Kind)
	{
		static const FButtonStyle Normal = MakeButtonStyle(FLinearColor(0.055f, 0.090f, 0.073f), FLinearColor(0.24f, 0.33f, 0.25f));
		static const FButtonStyle Primary = MakeButtonStyle(FLinearColor(0.25f, 0.17f, 0.055f), FLinearColor(0.72f, 0.53f, 0.23f));
		static const FButtonStyle Danger = MakeButtonStyle(FLinearColor(0.26f, 0.052f, 0.039f), FLinearColor(0.66f, 0.24f, 0.17f));
		switch (Kind)
		{
		case EButtonKind::Primary:
			return Primary;
		case EButtonKind::Danger:
			return Danger;
		default:
			return Normal;
		}
	}

	const FButtonStyle& CompactButtonStyle(EButtonKind Kind)
	{
		auto Compact = [](const FButtonStyle& Source)
		{
			FButtonStyle Style = Source;
			Style.SetNormalPadding(FMargin(3.f, 2.f));
			Style.SetPressedPadding(FMargin(3.f, 3.f, 3.f, 1.f));
			return Style;
		};
		static const FButtonStyle Normal = Compact(ButtonStyle(EButtonKind::Normal));
		static const FButtonStyle Primary = Compact(ButtonStyle(EButtonKind::Primary));
		static const FButtonStyle Danger = Compact(ButtonStyle(EButtonKind::Danger));
		switch (Kind)
		{
		case EButtonKind::Primary:
			return Primary;
		case EButtonKind::Danger:
			return Danger;
		default:
			return Normal;
		}
	}

	const FEditableTextBoxStyle& TextBoxStyle()
	{
		static FEditableTextBoxStyle Style = []()
		{
			// 字体在控件上通过 .Font() 设置（样式中的 Font 字段在新版本中已弃用）
			FEditableTextBoxStyle S = FCoreStyle::Get().GetWidgetStyle<FEditableTextBoxStyle>("NormalEditableTextBox");
			const FSlateRoundedBoxBrush Box(FLinearColor(0.025f, 0.043f, 0.035f, 1.f), 3.f, FLinearColor(0.30f, 0.39f, 0.29f), 1.f);
			S.SetBackgroundImageNormal(Box);
			S.SetBackgroundImageHovered(Box);
			S.SetBackgroundImageFocused(FSlateRoundedBoxBrush(FLinearColor(0.042f, 0.068f, 0.057f, 1.f), 3.f, Gold, 1.f));
			S.SetForegroundColor(FSlateColor(FLinearColor::White));
			return S;
		}();
		return Style;
	}
}
