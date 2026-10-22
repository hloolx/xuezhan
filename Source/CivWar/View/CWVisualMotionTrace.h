#pragma once

#include "CoreMinimal.h"

// Diagnostics only. Authoritative Walking arrives before its buffered visual
// displacement. Check that startup delay separately, then retain every frame
// in a full two-second window, including any later zero-velocity frames.
struct FCWVisualMotionTrace
{
	enum class EStatus : uint8 { Collecting, Complete, StartupFailed };

	bool Advance(bool bWalking, float Dt, float RawSpeed)
	{
		if (Status != EStatus::Collecting || Dt <= 0.f || !FMath::IsFinite(Dt)) return false;
		if (!bWalking)
		{
			*this = FCWVisualMotionTrace{};
			return false;
		}
		if (!bStarted)
		{
			// The first observation establishes the onset timestamp. Its Dt
			// precedes the observation and must not backdate a new Walking state.
			if (bEpisodeObserved) StartupSeconds += Dt;
			bEpisodeObserved = true;
			++StartupFrames;
			StartupFrameSeconds = Dt;
			StartupLimitSeconds = 0.1f + StartupFrameSeconds;
			if (StartupSeconds > StartupLimitSeconds + UE_SMALL_NUMBER)
			{
				Status = EStatus::StartupFailed;
				return true;
			}
			if (RawSpeed < 1.f) return false;
			bStarted = true;
			// Start the window at the first observed displacement, not at
			// the beginning of the preceding (possibly partial-startup) frame.
		}
		else
		{
			DurationSeconds += Dt;
		}
		++Frames;
		if (RawSpeed < 1.f) ++StoppedFrames;
		MinimumSpeed = FMath::Min(MinimumSpeed, RawSpeed);
		MaximumSpeed = FMath::Max(MaximumSpeed, RawSpeed);
		if (DurationSeconds >= 2.f)
		{
			Status = EStatus::Complete;
			return true;
		}
		return false;
	}

	EStatus Status = EStatus::Collecting;
	float StartupSeconds = 0.f;
	float StartupFrameSeconds = 0.f;
	float StartupLimitSeconds = 0.1f;
	int32 StartupFrames = 0;
	float DurationSeconds = 0.f;
	float MinimumSpeed = TNumericLimits<float>::Max();
	float MaximumSpeed = 0.f;
	int32 Frames = 0;
	int32 StoppedFrames = 0;
	bool bStarted = false;

private:
	bool bEpisodeObserved = false;
};
