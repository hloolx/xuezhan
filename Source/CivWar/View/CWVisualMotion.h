#pragma once

#include "CoreMinimal.h"

// Presentation-only snapshot buffer. A fast chase reaches each 20 Hz sample early
// and then reports zero velocity until the next packet; that is not a walk cycle.
// Never extrapolate: the visual remains between positions actually received.
struct FCWVisualMotion
{
	void Reset(float X)
	{
		Samples.Reset();
		Samples.Add({Clock, X});
		Position = X;
		Speed = 0.f;
		Velocity = 0.f;
		bHasPendingPosition = false;
	}

	void Observe(float X)
	{
		if (!FMath::IsFinite(X)) return;
		if (Samples.IsEmpty() || FMath::Abs(X - Position) > 400.f)
		{
			Reset(X);
			return;
		}
		// ApplyNetState runs before UpdateVisual. Defer the timestamp until this
		// frame's elapsed time is known, otherwise a hitch dates a new position
		// before the hitch and immediately consumes the whole render buffer.
		PendingPosition = X;
		bHasPendingPosition = true;
	}

	void Advance(float Dt)
	{
		if (Dt <= 0.f || !FMath::IsFinite(Dt) || Samples.IsEmpty()) return;
		Clock += Dt;
		if (bHasPendingPosition)
		{
			bHasPendingPosition = false;
			if (PendingPosition != Samples.Last().X) // Repeated snapshots are not new samples.
			{
				// The simulation moves at 20 Hz. The update immediately after a
				// hitch can arrive only one render frame later; keep those two
				// source steps at least one simulation tick apart instead of
				// compressing their travel into a 16 ms catch-up burst.
				const float SampleTime = FMath::Max(Clock, Samples.Last().Time + 0.05f);
				if (Clock - Samples.Last().Time > 0.25f && Speed < 1.f)
				{
					// Reconnect after an actual settled idle/outage. A long
					// rendering frame while moving must not invent an idle span.
					Samples.Add({SampleTime - 0.05f, Samples.Last().X});
				}
				Samples.Add({SampleTime, PendingPosition});
			}
		}
		const float RenderTime = Clock - 0.1f;
		while (Samples.Num() > 2 && Samples[1].Time <= RenderTime)
		{
			Samples.RemoveAt(0, 1, EAllowShrinking::No);
		}
		const float Previous = Position;
		if (Samples.Num() == 1 || RenderTime >= Samples.Last().Time) Position = Samples.Last().X;
		else if (RenderTime <= Samples[0].Time) Position = Samples[0].X;
		else
		{
			const FSample& A = Samples[0];
			const FSample& B = Samples[1];
			Position = FMath::Lerp(A.X, B.X, FMath::Clamp((RenderTime - A.Time) / (B.Time - A.Time), 0.f, 1.f));
		}
		Velocity = (Position - Previous) / Dt;
		// Smooth quantization and jitter without restarting the gait at every packet.
		Speed = FMath::Lerp(Speed, FMath::Abs(Velocity), 1.f - FMath::Exp(-Dt / 0.06f));
		if (Speed < 0.1f) Speed = 0.f;
	}

	float Position = 0.f;
	float Speed = 0.f;
	float Velocity = 0.f;

private:
	struct FSample { float Time; float X; };
	TArray<FSample> Samples;
	float Clock = 0.f;
	float PendingPosition = 0.f;
	bool bHasPendingPosition = false;
};
