#include "Misc/AutomationTest.h"
#include "View/CWVisualMotion.h"
#include "View/CWVisualMotionTrace.h"

#if WITH_DEV_AUTOMATION_TESTS

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWUnitMotionSnapshotsTest, "CivWar.Art.UnitPresentation.SnapshotMotion",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWUnitMotionSnapshotsTest::RunTest(const FString& Parameters)
{
	// Feed the real presentation helper at the supported 20 Hz snapshot cadence,
	// including render rates which are not an integer multiple of that cadence.
	for (const int32 Fps : {30, 60, 144})
	{
		FCWVisualMotion Motion;
		Motion.Reset(0.f);
		int32 PreviousPacket = 0;
		float LatestX = 0.f;
		float PreviousX = 0.f;
		for (int32 Frame = 0; Frame < Fps * 3; ++Frame)
		{
			const float Time = static_cast<float>(Frame) / Fps;
			const int32 Packet = FMath::FloorToInt(Time * 20.f + 0.001f);
			if (Packet != PreviousPacket)
			{
				LatestX = Packet * 0.05f * 160.f;
				PreviousPacket = Packet;
			}
			Motion.Observe(LatestX); // Same snapshot repeats on intervening frames.
			Motion.Advance(1.f / Fps);
			TestTrue(TEXT("Interpolation never exceeds an observed position"), Motion.Position <= LatestX + 0.001f);
			TestTrue(TEXT("Forward samples cannot make the visual move backwards"), Motion.Position >= PreviousX);
			if (Time > 0.4f)
			{
				TestTrue(FString::Printf(TEXT("%d fps: no stop/start gait holes"), Fps), Motion.Speed > 100.f);
				TestTrue(TEXT("No 1.6x chase bursts"), Motion.Speed < 210.f);
			}
			PreviousX = Motion.Position;
		}
		for (int32 Frame = 0; Frame < Fps; ++Frame)
		{
			Motion.Observe(LatestX);
			Motion.Advance(1.f / Fps);
		}
		TestTrue(TEXT("Stopped unit reaches exactly the last server position"), FMath::IsNearlyEqual(Motion.Position, LatestX));
		TestEqual(TEXT("Stopped animation speed settles to zero"), Motion.Speed, 0.f);
		const float StoppedX = Motion.Position;
		Motion.Observe(StoppedX + 8.f);
		Motion.Advance(1.f / Fps);
		TestEqual(TEXT("Resuming after idle does not interpolate across the whole idle time"), Motion.Position, StoppedX);
		for (int32 Frame = 0; Frame < Fps / 3; ++Frame) Motion.Advance(1.f / Fps);
		TestTrue(TEXT("Resume step is delivered within the buffer"), FMath::IsNearlyEqual(Motion.Position, StoppedX + 8.f));

		Motion.Observe(5000.f);
		TestEqual(TEXT("Teleport aligns to the authoritative location"), Motion.Position, 5000.f);
		Motion.Advance(1.f / Fps);
		TestEqual(TEXT("Teleport does not spin the walk cycle"), Motion.Speed, 0.f);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWUnitMotionPacketGapTest, "CivWar.Art.UnitPresentation.PacketGap",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWUnitMotionPacketGapTest::RunTest(const FString& Parameters)
{
	FCWVisualMotion Motion;
	Motion.Reset(100.f);
	float Latest = 100.f;
	for (int32 Frame = 0; Frame < 180; ++Frame)
	{
		// Retreat with one missing packet: no speculation into unseen positions.
		if (Frame % 3 == 0 && Frame != 60) Latest = 100.f - Frame / 60.f * 160.f;
		Motion.Observe(Latest);
		Motion.Advance(1.f / 60.f);
		TestTrue(TEXT("Retreat stays behind the last authoritative position"), Motion.Position >= Latest - 0.001f);
		if (Frame > 30) TestTrue(TEXT("A missed packet does not switch the gait to idle"), Motion.Speed > 50.f);
		TestTrue(TEXT("Retreat never moves forward"), Motion.Velocity <= 0.001f);
	}
	for (int32 Frame = 0; Frame < 120; ++Frame) Motion.Advance(1.f / 60.f);
	TestEqual(TEXT("Packet outage holds last known location"), Motion.Position, Latest);
	TestEqual(TEXT("Packet outage eventually becomes idle"), Motion.Speed, 0.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWUnitMotionFrameHitchTest, "CivWar.Art.UnitPresentation.FrameHitch",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWUnitMotionFrameHitchTest::RunTest(const FString& Parameters)
{
	// Replay the real helper with the observed loading/screenshot hitch lengths,
	// all three packet phases, and a longer stall where Sim caps catch-up at .25s.
	// Assert raw rendered displacement: smoothing gait speed cannot hide a stop.
	for (const int32 Fps : {30, 60, 144})
	for (const float Hitch : {0.1293f, 0.1623f, 0.2353f, 0.5f})
	for (const int32 Phase : {0, 1, 2})
	for (const float Direction : {-1.f, 1.f})
	{
		FCWVisualMotion Motion;
		Motion.Reset(0.f);
		double Accumulator = 0.;
		int32 Steps = 0;
		float LatestX = 0.f;
		float PreviousX = 0.f;
		float MinimumSpeed = TNumericLimits<float>::Max();
		float MaximumSpeed = 0.f;
		bool bObservedBounds = true;
		bool bMonotone = true;
		for (int32 Frame = 0; Frame < Fps * 3; ++Frame)
		{
			const float Dt = Frame == Fps + Phase ? Hitch : 1.f / Fps;
			Accumulator += FMath::Min(Dt, 0.25f);
			while (Accumulator >= 0.05)
			{
				++Steps;
				Accumulator -= 0.05;
			}
			LatestX = Direction * Steps * 0.05f * 180.f;
			Motion.Observe(LatestX);
			Motion.Advance(Dt);
			bObservedBounds &= Direction * (LatestX - Motion.Position) >= -0.001f;
			bMonotone &= Direction * (Motion.Position - PreviousX) >= -0.001f;
			if (Frame > Fps / 2)
			{
				MinimumSpeed = FMath::Min(MinimumSpeed, FMath::Abs(Motion.Velocity));
				MaximumSpeed = FMath::Max(MaximumSpeed, FMath::Abs(Motion.Velocity));
			}
			PreviousX = Motion.Position;
		}
		const FString Case = FString::Printf(TEXT("%dfps hitch=%.4f phase=%d dir=%.0f"),
			Fps, Hitch, Phase, Direction);
		TestTrue(Case + TEXT(": never extrapolates beyond received positions"), bObservedBounds);
		TestTrue(Case + TEXT(": no reversal while source advances"), bMonotone);
		TestTrue(Case + TEXT(": no stopped rendered frames after a hitch"), MinimumSpeed > 1.f);
		TestTrue(Case + TEXT(": no compressed-step catch-up burst"), MaximumSpeed < 225.f);

		// A genuine outage must still finish at the last known position.
		for (int32 Frame = 0; Frame < Fps * 2; ++Frame) Motion.Advance(1.f / Fps);
		TestEqual(Case + TEXT(": outage holds authoritative endpoint"), Motion.Position, LatestX);
		TestEqual(Case + TEXT(": outage settles animation"), Motion.Speed, 0.f);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWUnitMotionTraceStartupTest, "CivWar.Art.UnitPresentation.MotionTraceStartup",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWUnitMotionTraceStartupTest::RunTest(const FString& Parameters)
{
	for (const int32 Fps : {30, 60, 144})
	for (const float Direction : {-1.f, 1.f})
	{
		const float Dt = 1.f / Fps;
		FCWVisualMotion Motion;
		FCWVisualMotionTrace Trace;
		Motion.Reset(0.f);
		for (int32 Frame = 0; Frame < Fps; ++Frame)
		{
			Motion.Observe(0.f);
			Motion.Advance(Dt);
			Trace.Advance(false, Dt, FMath::Abs(Motion.Velocity));
		}
		bool bSawBufferedStart = false;
		bool bReported = false;
		int32 StartFrame = INDEX_NONE;
		int32 EndFrame = INDEX_NONE;
		for (int32 Frame = 0; Frame < Fps * 3; ++Frame)
		{
			const int32 Packet = 1 + FMath::FloorToInt(Frame * 20.f / Fps + 0.001f);
			Motion.Observe(Direction * Packet * 0.05f * 240.f);
			Motion.Advance(Dt);
			bSawBufferedStart |= !Trace.bStarted && FMath::Abs(Motion.Velocity) < 1.f;
			const bool bWasStarted = Trace.bStarted;
			bReported = Trace.Advance(true, Dt, FMath::Abs(Motion.Velocity));
			if (!bWasStarted && Trace.bStarted) StartFrame = Frame;
			if (bReported) { EndFrame = Frame; break; }
		}
		const FString Case = FString::Printf(TEXT("%dfps dir=%.0f"), Fps, Direction);
		TestTrue(Case + TEXT(": exercises a real idle-to-walking buffered start"), bSawBufferedStart);
		TestTrue(Case + TEXT(": reports a completed continuous window"), bReported &&
			Trace.Status == FCWVisualMotionTrace::EStatus::Complete);
		TestTrue(Case + TEXT(": startup is bounded by buffer plus one frame"),
			Trace.StartupSeconds <= 0.1f + Dt + UE_SMALL_NUMBER);
		TestTrue(Case + TEXT(": takes a full two seconds after first displacement"),
			StartFrame != INDEX_NONE && (EndFrame - StartFrame) * Dt >= 2.f - UE_SMALL_NUMBER);
		TestEqual(Case + TEXT(": startup delay is not a mid-walk stop"), Trace.StoppedFrames, 0);

		// A Walking state with no displacement must fail promptly; it cannot
		// wait indefinitely for a convenient positive-velocity starting frame.
		FCWVisualMotionTrace NeverStarts;
		for (int32 Frame = 0; Frame < Fps; ++Frame)
		{
			if (NeverStarts.Advance(true, Dt, 0.f)) break;
		}
		TestTrue(Case + TEXT(": stalled startup is an explicit failure"),
			NeverStarts.Status == FCWVisualMotionTrace::EStatus::StartupFailed);
		TestTrue(Case + TEXT(": failed startup never claims a continuous window"),
			!NeverStarts.bStarted && NeverStarts.Frames == 0 && NeverStarts.DurationSeconds == 0.f);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FCWUnitMotionTraceOutageTest, "CivWar.Art.UnitPresentation.MotionTraceOutage",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FCWUnitMotionTraceOutageTest::RunTest(const FString& Parameters)
{
	for (const int32 Fps : {30, 60, 144})
	{
		const float Dt = 1.f / Fps;
		FCWVisualMotion Motion;
		FCWVisualMotionTrace Trace;
		Motion.Reset(0.f);
		float LatestX = 0.f;
		int32 StartFrame = INDEX_NONE;
		int32 EndFrame = INDEX_NONE;
		for (int32 Frame = 0; Frame < Fps * 4; ++Frame)
		{
			// Drop multiple snapshots after a full second of actual motion.
			// State still says Walking, so zeros from the exhausted buffer
			// must remain in the same diagnostic window after packets resume.
			if (Frame < Fps || Frame >= Fps * 3 / 2)
			{
				const int32 Packet = 1 + FMath::FloorToInt(Frame * 20.f / Fps + 0.001f);
				LatestX = Packet * 0.05f * 200.f;
			}
			Motion.Observe(LatestX);
			Motion.Advance(Dt);
			const bool bWasStarted = Trace.bStarted;
			const bool bReported = Trace.Advance(true, Dt, FMath::Abs(Motion.Velocity));
			if (!bWasStarted && Trace.bStarted) StartFrame = Frame;
			if (bReported) { EndFrame = Frame; break; }
		}
		const FString Case = FString::Printf(TEXT("%dfps outage"), Fps);
		TestTrue(Case + TEXT(": completes the original window"),
			Trace.Status == FCWVisualMotionTrace::EStatus::Complete && StartFrame != INDEX_NONE);
		TestTrue(Case + TEXT(": mid-walk stop remains a strict failure"),
			Trace.StoppedFrames > 0 && Trace.MinimumSpeed < 1.f);
		TestTrue(Case + TEXT(": receiving packets again does not restart the window"),
			EndFrame != INDEX_NONE && (EndFrame - StartFrame) * Dt <= 2.f + 2.f * Dt);
	}
	return true;
}

#endif
