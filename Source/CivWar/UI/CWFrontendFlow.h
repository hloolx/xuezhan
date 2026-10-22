#pragma once

#include "CoreMinimal.h"
#include "Net/CWNetTypes.h"

// Local presentation decisions only; the authoritative simulation is unchanged.
namespace CWFrontend
{
enum class EBackAction : uint8 { None, CancelSkill, CloseBuildMenu, CloseOverlay, OpenOverlay };

inline EBackAction ResolveBack(bool bSkillTargeting, bool bBuildMenu, bool bOverlay, ECWMatchPhase Phase)
{
	if (bSkillTargeting) return EBackAction::CancelSkill;
	if (bBuildMenu) return EBackAction::CloseBuildMenu;
	if (bOverlay) return EBackAction::CloseOverlay;
	return Phase == ECWMatchPhase::Menu ? EBackAction::None : EBackAction::OpenOverlay;
}

inline bool CanCommand(ECWMatchPhase Phase, bool bOverlay)
{
	return Phase == ECWMatchPhase::InMatch && !bOverlay;
}

inline bool CanMoveCamera(ECWMatchPhase Phase, bool bOverlay)
{
	return !bOverlay && (Phase == ECWMatchPhase::InMatch || Phase == ECWMatchPhase::PostMatch);
}

enum class ETimeDecision : uint8 { BaseHealth, Kills, Draw };
inline ETimeDecision TimeDecision(float Hp0, float MaxHp0, int32 Kills0, float Hp1, float MaxHp1, int32 Kills1)
{
	const float Ratio0 = MaxHp0 > 0.f ? Hp0 / MaxHp0 : 0.f;
	const float Ratio1 = MaxHp1 > 0.f ? Hp1 / MaxHp1 : 0.f;
	if (FMath::Abs(Ratio0 - Ratio1) > 1.0e-4f) return ETimeDecision::BaseHealth;
	return Kills0 != Kills1 ? ETimeDecision::Kills : ETimeDecision::Draw;
}
}
