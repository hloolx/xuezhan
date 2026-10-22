#include "Misc/AutomationTest.h"
#include "UI/CWFrontendFlow.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWFrontendNavigationTest, "CivWar.Frontend.NavigationAndInput",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWFrontendNavigationTest::RunTest(const FString& Parameters)
{
	using namespace CWFrontend;
	TestTrue(TEXT("Escape first cancels targeting without opening a menu"),
		ResolveBack(true, true, false, ECWMatchPhase::InMatch) == EBackAction::CancelSkill);
	TestTrue(TEXT("Escape dismisses a turret picker before opening settings"),
		ResolveBack(false, true, false, ECWMatchPhase::InMatch) == EBackAction::CloseBuildMenu);
	TestTrue(TEXT("Escape exits settings and exit confirmation to the live view"),
		ResolveBack(false, false, true, ECWMatchPhase::InMatch) == EBackAction::CloseOverlay);
	TestTrue(TEXT("Escape from live play opens its menu"),
		ResolveBack(false, false, false, ECWMatchPhase::InMatch) == EBackAction::OpenOverlay);
	TestTrue(TEXT("Lobby exposes the same audio menu"),
		ResolveBack(false, false, false, ECWMatchPhase::Lobby) == EBackAction::OpenOverlay);
	TestTrue(TEXT("Main-menu navigation remains owned by the main-menu widget"),
		ResolveBack(false, false, false, ECWMatchPhase::Menu) == EBackAction::None);
	for (const ECWMatchPhase Phase : { ECWMatchPhase::Menu, ECWMatchPhase::Lobby, ECWMatchPhase::Countdown,
		ECWMatchPhase::InMatch, ECWMatchPhase::PostMatch })
	{
		TestFalse(TEXT("Modal blocks combat requests in every phase"), CanCommand(Phase, true));
		TestFalse(TEXT("Modal blocks keyboard, edge-pan and zoom in every phase"), CanMoveCamera(Phase, true));
		if (Phase != ECWMatchPhase::InMatch)
			TestFalse(TEXT("Countdown, lobby and results never enable turret commands"), CanCommand(Phase, false));
	}
	TestTrue(TEXT("Closing settings restores combat requests"), CanCommand(ECWMatchPhase::InMatch, false));
	TestTrue(TEXT("Closing settings restores the battle camera"), CanMoveCamera(ECWMatchPhase::InMatch, false));
	TestFalse(TEXT("The menu composition cannot be moved by camera shortcuts"), CanMoveCamera(ECWMatchPhase::Menu, false));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWFrontendTimeReasonTest, "CivWar.Frontend.TimeLimitReason",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWFrontendTimeReasonTest::RunTest(const FString& Parameters)
{
	using namespace CWFrontend;
	TestTrue(TEXT("Equal base percentages use kills, even when maximum HP differs"),
		TimeDecision(500.f, 1000.f, 20, 1000.f, 2000.f, 18) == ETimeDecision::Kills);
	TestTrue(TEXT("A difference inside the server's 1e-4 tolerance still uses kills"),
		TimeDecision(500.05f, 1000.f, 18, 500.f, 1000.f, 20) == ETimeDecision::Kills);
	TestTrue(TEXT("A difference outside tolerance uses health even if kills favor the other side"),
		TimeDecision(500.2f, 1000.f, 18, 500.f, 1000.f, 20) == ETimeDecision::BaseHealth);
	TestTrue(TEXT("Equal health ratios and kills report the actual tie"),
		TimeDecision(500.f, 1000.f, 20, 1000.f, 2000.f, 20) == ETimeDecision::Draw);
	TestTrue(TEXT("Zero maximum health is safe and matches the simulation's zero ratio"),
		TimeDecision(0.f, 0.f, 0, 0.f, 0.f, 0) == ETimeDecision::Draw);
	return true;
}

#endif
