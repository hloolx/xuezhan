#include "View/CWVisuals.h"

#include "Components/SceneComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"

namespace CWVisual
{
	static UStaticMesh* GShapes[4] = { nullptr, nullptr, nullptr, nullptr };
	static UMaterialInterface* GSurface = nullptr;
	static UMaterialInterface* GWarning = nullptr;
	static bool GStylized = false;
	static bool GLoaded = false;

	static void EnsureLoaded()
	{
		if (GLoaded)
		{
			return;
		}
		GLoaded = true;
		const TCHAR* Paths[4] = {
			TEXT("/Engine/BasicShapes/Cube.Cube"),
			TEXT("/Engine/BasicShapes/Sphere.Sphere"),
			TEXT("/Engine/BasicShapes/Cylinder.Cylinder"),
			TEXT("/Engine/BasicShapes/Cone.Cone"),
		};
		for (int32 I = 0; I < 4; ++I)
		{
			GShapes[I] = LoadObject<UStaticMesh>(nullptr, Paths[I]);
			if (GShapes[I])
			{
				GShapes[I]->AddToRoot(); // 引擎资源常驻，避免被回收
			}
		}
		GSurface = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Art/M_CWStylized.M_CWStylized"));
		GStylized = GSurface != nullptr;
		if (!GSurface)
		{
			GSurface = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
		}
		if (GSurface)
		{
			GSurface->AddToRoot();
		}
		GWarning = LoadObject<UMaterialInterface>(nullptr, TEXT("/Game/Art/M_CWWarning.M_CWWarning"));
		if (GWarning)
		{
			GWarning->AddToRoot();
		}
	}

	UStaticMesh* GetShape(EShape Shape)
	{
		EnsureLoaded();
		return GShapes[static_cast<int32>(Shape)];
	}

	UMaterialInterface* GetSurfaceMaterial()
	{
		EnsureLoaded();
		return GSurface;
	}

	UMaterialInterface* GetWarningMaterial()
	{
		EnsureLoaded();
		return GWarning ? GWarning : GSurface;
	}

	bool HasStylizedMaterial()
	{
		EnsureLoaded();
		return GStylized;
	}

	UMaterialInstanceDynamic* MakeMaterial(UObject* Outer, const FMaterialParams& Params)
	{
		UMaterialInterface* Base = GetSurfaceMaterial();
		if (!Base)
		{
			return nullptr;
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Outer);
		Mid->SetVectorParameterValue(TEXT("Color"), Params.Color);
		if (GStylized)
		{
			Mid->SetScalarParameterValue(TEXT("Roughness"), Params.Roughness);
			Mid->SetScalarParameterValue(TEXT("Metallic"), Params.Metallic);
			Mid->SetScalarParameterValue(TEXT("Emissive"), Params.Emissive);
		}
		return Mid;
	}

	UMaterialInstanceDynamic* MakeWarningMaterial(UObject* Outer, const FLinearColor& Color, float Opacity)
	{
		EnsureLoaded();
		if (!GWarning)
		{
			FMaterialParams Params;
			Params.Color = Color;
			Params.Emissive = 2.f;
			return MakeMaterial(Outer, Params);
		}
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(GWarning, Outer);
		Mid->SetVectorParameterValue(TEXT("Color"), Color);
		Mid->SetScalarParameterValue(TEXT("Opacity"), Opacity);
		return Mid;
	}

	UMaterialInstanceDynamic* MakeMaterial(UObject* Outer, const FLinearColor& Color, float Roughness, float Metallic)
	{
		FMaterialParams Params;
		Params.Color = Color;
		Params.Roughness = Roughness;
		Params.Metallic = Metallic;
		return MakeMaterial(Outer, Params);
	}

	void SetMaterialColor(UMaterialInstanceDynamic* Material, const FLinearColor& Color)
	{
		if (Material)
		{
			Material->SetVectorParameterValue(TEXT("Color"), Color);
		}
	}

	void SetMaterialEmissive(UMaterialInstanceDynamic* Material, float Emissive)
	{
		if (Material && GStylized)
		{
			Material->SetScalarParameterValue(TEXT("Emissive"), Emissive);
		}
	}

	USceneComponent* AddPivot(AActor* Owner, USceneComponent* Parent, const FVector& Location, const FRotator& Rotation)
	{
		USceneComponent* Pivot = NewObject<USceneComponent>(Owner);
		Pivot->SetupAttachment(Parent);
		Pivot->SetRelativeLocationAndRotation(Location, Rotation);
		Pivot->RegisterComponent();
		return Pivot;
	}

	UStaticMeshComponent* AddPart(AActor* Owner, USceneComponent* Parent, EShape Shape, const FVector& Location, const FVector& Size,
		const FRotator& Rotation, const FMaterialParams& Material, bool bCastShadow)
	{
		UStaticMeshComponent* Part = NewObject<UStaticMeshComponent>(Owner);
		Part->SetStaticMesh(GetShape(Shape));
		Part->SetupAttachment(Parent);
		Part->SetRelativeLocationAndRotation(Location, Rotation);
		Part->SetRelativeScale3D(Size / 100.f);
		Part->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Part->SetGenerateOverlapEvents(false);
		Part->SetCastShadow(bCastShadow);
		Part->bReceivesDecals = false;
		Part->SetMaterial(0, MakeMaterial(Part, Material));
		Part->RegisterComponent();
		return Part;
	}

	FLinearColor TeamColor(int32 Team)
	{
		return Team == 0 ? FLinearColor(0.10f, 0.32f, 0.95f) : FLinearColor(0.92f, 0.16f, 0.10f);
	}

	FLinearColor TeamColorDark(int32 Team)
	{
		return Team == 0 ? FLinearColor(0.04f, 0.12f, 0.40f) : FLinearColor(0.40f, 0.05f, 0.04f);
	}

	FMaterialParams Paint(const FLinearColor& Color, float Roughness, float Metallic)
	{
		FMaterialParams P;
		P.Color = Color;
		P.Roughness = Roughness;
		P.Metallic = Metallic;
		return P;
	}

	FMaterialParams Metal(const FLinearColor& Color, float Roughness)
	{
		return Paint(Color, Roughness, 0.9f);
	}
}
