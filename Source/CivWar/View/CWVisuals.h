// 血战文明 - 表现层公共工具：基础形体、材质、配色
// 第一轮的角色/建筑由程序化部件拼装（明确标记为占位美术），后续替换为正式模型时只需改动 CWModels。
#pragma once

#include "CoreMinimal.h"

class AActor;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class USceneComponent;
class UStaticMesh;
class UStaticMeshComponent;

namespace CWVisual
{
	enum class EShape : uint8
	{
		Cube,
		Sphere,
		Cylinder,
		Cone,
	};

	struct FMaterialParams
	{
		FLinearColor Color = FLinearColor::White;
		float Roughness = 0.7f;
		float Metallic = 0.f;
		float Emissive = 0.f;
	};

	UStaticMesh* GetShape(EShape Shape);
	// 优先使用 Tools/setup_content.py 生成的 /Game/Art/M_CWStylized（带粗糙度/金属度/自发光参数），
	// 不存在时退回引擎 BasicShapeMaterial（仅颜色参数）
	UMaterialInterface* GetSurfaceMaterial();
	// 半透明无光照材质（技能预警圈）；不存在时退回表面材质
	UMaterialInterface* GetWarningMaterial();
	bool HasStylizedMaterial();

	UMaterialInstanceDynamic* MakeMaterial(UObject* Outer, const FMaterialParams& Params);
	// 预警圈材质：有半透明材质时使用（Color + Opacity），否则退回表面材质
	UMaterialInstanceDynamic* MakeWarningMaterial(UObject* Outer, const FLinearColor& Color, float Opacity);
	UMaterialInstanceDynamic* MakeMaterial(UObject* Outer, const FLinearColor& Color, float Roughness = 0.7f, float Metallic = 0.f);
	void SetMaterialColor(UMaterialInstanceDynamic* Material, const FLinearColor& Color);
	void SetMaterialEmissive(UMaterialInstanceDynamic* Material, float Emissive);

	// 在 Parent 下添加一个部件；Size 为厘米尺寸（基础形体为 100cm）
	UStaticMeshComponent* AddPart(AActor* Owner, USceneComponent* Parent, EShape Shape, const FVector& Location, const FVector& Size,
		const FRotator& Rotation, const FMaterialParams& Material, bool bCastShadow = true);
	USceneComponent* AddPivot(AActor* Owner, USceneComponent* Parent, const FVector& Location, const FRotator& Rotation = FRotator::ZeroRotator);

	FLinearColor TeamColor(int32 Team);
	FLinearColor TeamColorDark(int32 Team);
	FMaterialParams Paint(const FLinearColor& Color, float Roughness = 0.75f, float Metallic = 0.f);
	FMaterialParams Metal(const FLinearColor& Color, float Roughness = 0.35f);
}
