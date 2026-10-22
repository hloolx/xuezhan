#include "View/CWSmoothUnitAnimInstance.h"

#include "Animation/AnimSingleNodeInstanceProxy.h"

namespace
{
	struct FCWSmoothUnitAnimProxy : public FAnimSingleNodeInstanceProxy
	{
		explicit FCWSmoothUnitAnimProxy(UAnimInstance* Instance) : FAnimSingleNodeInstanceProxy(Instance) {}

		void PrepareBlend(bool bNewPose, float Duration, float Dt)
		{
			if (bNewPose)
			{
				BlendFrom = LastPose;
				BlendDuration = Duration;
				BlendElapsed = 0.f;
			}
			BlendElapsed += FMath::Max(Dt, 0.f);
		}

		virtual bool Evaluate(FPoseContext& Output) override
		{
			const bool bEvaluated = FAnimSingleNodeInstanceProxy::Evaluate(Output);
			if (!bEvaluated) return false;
			const uint16 Serial = Output.Pose.GetBoneContainer().GetSerialNumber();
			const int32 Count = Output.Pose.GetNumBones();
			// Compact indices may change with LOD even when bone count is equal.
			if (Serial != BoneSerial || LastPose.Num() != Count)
			{
				BlendFrom.Reset();
				LastPose.SetNum(Count);
				BoneSerial = Serial;
			}
			const float T = BlendDuration > 0.f ? FMath::Clamp(BlendElapsed / BlendDuration, 0.f, 1.f) : 1.f;
			const float Alpha = T * T * (3.f - 2.f * T);
			for (const FCompactPoseBoneIndex Bone : Output.Pose.ForEachBoneIndex())
			{
				FTransform& Pose = Output.Pose[Bone];
				if (Alpha < 1.f && BlendFrom.Num() == Count)
				{
					const FTransform Target = Pose;
					Pose.Blend(BlendFrom[Bone.GetInt()], Target, Alpha);
					Pose.NormalizeRotation();
				}
				LastPose[Bone.GetInt()] = Pose;
			}
			if (Alpha >= 1.f) BlendFrom.Reset();
			return true;
		}

		TArray<FTransform> LastPose;
		TArray<FTransform> BlendFrom;
		uint16 BoneSerial = 0;
		float BlendElapsed = 0.f;
		float BlendDuration = 0.f;
	};
}

FAnimInstanceProxy* UCWSmoothUnitAnimInstance::CreateAnimInstanceProxy()
{
	return new FCWSmoothUnitAnimProxy(this);
}

void UCWSmoothUnitAnimInstance::PrepareBlend(bool bNewPose, float Duration, float Dt)
{
	GetProxyOnGameThread<FCWSmoothUnitAnimProxy>().PrepareBlend(bNewPose, Duration, Dt);
}
