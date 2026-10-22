#pragma once

#include "UI/CWUIStyle.h"
#include "Rendering/DrawElements.h"
#include "Widgets/Layout/SBorder.h"

// A decorative frame over the established panel. Inherits SBorder's complete
// layout and input contract; no extra child can absorb clicks or alter sizing.
// Reserve this treatment for major command/menu frames, never every button.
class SCWEpicFrame : public SBorder
{
public:
	void Construct(const SBorder::FArguments& Args)
	{
		SBorder::Construct(Args);
		Frame = CWUI::EpicFrameBrush();
	}

	virtual int32 OnPaint(const FPaintArgs& Args, const FGeometry& Geometry, const FSlateRect& Clip,
		FSlateWindowElementList& Draw, int32 Layer, const FWidgetStyle& Style, bool bParentEnabled) const override
	{
		const int32 ContentLayer = SBorder::OnPaint(Args, Geometry, Clip, Draw, Layer, Style, bParentEnabled);
		if (Frame && Frame->DrawAs != ESlateBrushDrawType::NoDrawType)
		{
			FSlateDrawElement::MakeBox(Draw, ContentLayer + 1, Geometry.ToPaintGeometry(), Frame,
				ESlateDrawEffect::None, Style.GetColorAndOpacityTint() * Frame->GetTint(Style));
			return ContentLayer + 1;
		}
		return ContentLayer;
	}

private:
	const FSlateBrush* Frame = nullptr;
};
