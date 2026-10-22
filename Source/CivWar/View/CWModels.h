// 血战文明 - 程序化占位模型（角色、坐骑、载具、基地、炮塔、弹体）
// 【占位美术】这些模型由基础形体拼装，用于打通玩法与动画时序；正式美术替换方案见 Docs/ASSETS.md。
#pragma once

#include "CoreMinimal.h"
#include "View/CWVisuals.h"
#include "View/CWEraArt.h"

class AActor;
class UMaterialInstanceDynamic;
class USceneComponent;

enum class ECWAttackStyle : uint8
{
	Chop,   // 劈砍（斧、剑、工兵铲）
	Thrust, // 冲刺（骑枪、长矛、猛兽冲撞）
	Throw,  // 投掷（投石索）
	Shoot,  // 射击（弩、步枪）
	Burst,  // 连射（机枪）
	Cannon, // 炮击（坦克、机甲）：炮塔明显后坐
};

struct FCWUnitRig
{
	USceneComponent* Body = nullptr;  // 上下起伏/前后倾斜的主枢轴
	USceneComponent* ArmL = nullptr;
	USceneComponent* ArmR = nullptr;
	USceneComponent* LegL = nullptr;
	USceneComponent* LegR = nullptr;
	USceneComponent* Muzzle = nullptr; // 投射物出手点 / 枪口
	USceneComponent* Turret = nullptr; // 载具炮塔 / 机甲武器组
	FVector TurretRest = FVector::ZeroVector; // 炮塔静止位置（后坐动画的基准）
	TArray<USceneComponent*> MountLegs; // 坐骑四条腿：前左、前右、后左、后右
	TArray<USceneComponent*> Wheels;
	TArray<UMaterialInstanceDynamic*> Materials; // 受击闪白
	TArray<FLinearColor> BaseColors;
	ECWAttackStyle Style = ECWAttackStyle::Chop;
	float Height = 180.f;
	float ArmRestPitch = 0.f;    // 武器手的待机角度
	float StrideLength = 60.f;   // 步幅：决定行走动画频率
	bool bQuadruped = false;
	bool bVehicle = false;
};

struct FCWBaseRig
{
	bool bTripoBasePilot = false;
	bool bHasMeasuredGate = false;
	FVector MeasuredGate = FVector::ZeroVector;
	TArray<FVector> TurretMounts; // 局部坐标
	TArray<UMaterialInstanceDynamic*> Materials;
	TArray<FLinearColor> BaseColors;
	float Height = 300.f;
};

struct FCWTurretRig
{
	bool bEraArt = false;
	float EraFireElapsed = -1.f;
	float EraFireDuration = 0.f;
	float EraReadyElapsed = 0.f;
	TArray<FCWEraMotionChannel> EraChannels;
	TArray<FCWEraSkeletalPart> EraSkeletalParts;
	UStaticMeshComponent* LoadedStone = nullptr;
	bool bRockTowerPilot = false;
	float PilotFireElapsed = -1.f;
	USceneComponent* Root = nullptr;
	USceneComponent* Aim = nullptr;   // 俯仰枢轴
	USceneComponent* Muzzle = nullptr;
};

namespace CWModels
{
	void BuildUnit(AActor* Owner, USceneComponent* Root, FName VisualKey, int32 Team, FCWUnitRig& Rig);
	void BuildBase(AActor* Owner, USceneComponent* Root, int32 Age, int32 Team, FCWBaseRig& Rig);
	void BuildTurret(AActor* Owner, USceneComponent* Mount, FName VisualKey, int32 Team, FCWTurretRig& Rig);

	struct FProjectileLook
	{
		CWVisual::EShape Shape = CWVisual::EShape::Sphere;
		FVector Size = FVector(10.f);
		FLinearColor Color = FLinearColor::Gray;
		float Emissive = 0.f;
		float ArcHeight = 0.f;  // 抛物线高度
		bool bAlignToVelocity = false;
	};
	FProjectileLook GetProjectileLook(FName VisualKey);
}
