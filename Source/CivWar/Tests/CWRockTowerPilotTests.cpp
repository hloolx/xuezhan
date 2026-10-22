#include "Misc/AutomationTest.h"
#include "View/CWStaticTurretPilot.h"

#include <limits>

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWRockTowerTimelineTest, "CivWar.Art.RockTowerTimeline", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWRockTowerTimelineTest::RunTest(const FString& Parameters)
{
	const float Times[] = {-1.f, 0.f, 0.08f, 0.16f, 0.30f, 0.625f, 0.95f, 1.20f, 1.30f, 1.70f, 2.10f, 5.f};
	const float Pitches[] = {35.f, 35.f, -2.5f, -40.f, -40.f, 12.5f, 65.f, 65.f, 65.f, 50.f, 35.f, 35.f};
	for (int32 Index = 0; Index < UE_ARRAY_COUNT(Times); ++Index)
	{
		const CWStaticTurretPilot::FRockTowerPose Pose = CWStaticTurretPilot::SamplePose(Times[Index]);
		TestTrue(FString::Printf(TEXT("Actual pose at %.3fs"), Times[Index]), FMath::IsNearlyEqual(Pose.Pitch, Pitches[Index], 0.0001f));
		TestEqual(FString::Printf(TEXT("Loaded stone at %.3fs"), Times[Index]), Pose.bStoneVisible, Times[Index] < 0.f || Times[Index] >= 1.2f);
	}
	for (int32 Frame = 0; Frame <= 144; ++Frame)
	{
		const CWStaticTurretPilot::FRockTowerPose Pose = CWStaticTurretPilot::SamplePose(Frame / 60.f);
		TestTrue(TEXT("All cycle samples stay within the approved sweep"), Pose.Pitch >= -40.f && Pose.Pitch <= 65.f);
	}
	const CWStaticTurretPilot::FRockTowerPose InvalidPose = CWStaticTurretPilot::SamplePose(std::numeric_limits<float>::quiet_NaN());
	TestTrue(TEXT("Invalid elapsed time remains finite and ready"), InvalidPose.Pitch == 35.f && InvalidPose.bStoneVisible);
	const FVector Pivot(-4.f, 0.f, 51.f);
	const FVector LocalRelease(3.5f, 0.f, 57.f);
	const FVector ReadyRelease = Pivot + FRotator(35.f, 0.f, 0.f).RotateVector(LocalRelease);
	TestTrue(TEXT("Actual UE rotation has correct opposite Blender Y sign"), ReadyRelease.Equals(FVector(-33.826825f, 0.f, 99.699187f), 0.0001));
	const FTransform Blue(FRotator::ZeroRotator, FVector::ZeroVector, FVector::OneVector);
	const FTransform Red(FRotator(0.f, 180.f, 0.f), FVector(6000.f, 0.f, 0.f), FVector::OneVector);
	TestTrue(TEXT("Opposite team rotates the same release point without reflection"), FMath::IsNearlyEqual(Blue.TransformPosition(ReadyRelease).X + Red.TransformPosition(ReadyRelease).X, 6000.0, 0.0001));
	TestTrue(TEXT("Both team transforms have positive unit scale"), Blue.GetScale3D() == FVector::OneVector && Red.GetScale3D() == FVector::OneVector);
	return true;
}

#endif
