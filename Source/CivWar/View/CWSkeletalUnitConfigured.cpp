#include "View/CWSkeletalUnitPresentation.h"

#include "Animation/AnimSequence.h"
#include "Components/SkeletalMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/StaticMesh.h"
#include "GameFramework/Actor.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "View/CWSmoothUnitAnimInstance.h"
#include "View/CWEraArt.h"
#include "Sim/SimTypes.h"

namespace
{
	bool Approved(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		bool Value = false;
		return Object->TryGetBoolField(Field, Value) && Value;
	}

	bool IsArtPath(const FString& Path)
	{
		return Path.StartsWith(TEXT("/Game/ArtPilot/")) && !Path.Contains(TEXT(".."));
	}

	bool ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object->TryGetArrayField(Field, Values)) return !Object->HasField(Field);
		if (Values->Num() != 3) return false;
		double Coordinates[3];
		for (int32 I = 0; I < 3; ++I)
			if (!(*Values)[I]->TryGetNumber(Coordinates[I]) || !FMath::IsFinite(Coordinates[I])) return false;
		Out = FVector(Coordinates[0], Coordinates[1], Coordinates[2]);
		return true;
	}

	bool ReadTransform(const TSharedPtr<FJsonObject>& Object, FTransform& Out)
	{
		FVector Translation = FVector::ZeroVector;
		FVector Rotation = FVector::ZeroVector;
		double Scale = 1.0;
		if (Object->HasField(TEXT("uniform_scale")) && !Object->TryGetNumberField(TEXT("uniform_scale"), Scale)) return false;
		if (!FMath::IsFinite(Scale) || Scale <= 0.0 || Scale > 10.0 ||
			!ReadVector(Object, TEXT("translation_cm"), Translation) ||
			!ReadVector(Object, TEXT("rotation_degrees"), Rotation)) return false;
		Out = FTransform(FRotator(Rotation.X, Rotation.Y, Rotation.Z), Translation, FVector(Scale));
		return true;
	}

	bool HasSocketOrBone(const USkeletalMesh* Mesh, FName Name)
	{
		return !Name.IsNone() && (Mesh->FindSocket(Name) || Mesh->GetRefSkeleton().FindBoneIndex(Name) != INDEX_NONE);
	}

	struct FLoadedPart
	{
		FString Id;
		USkeletalMesh* Mesh = nullptr;
		TMap<FName, TObjectPtr<UAnimSequence>> Clips;
		TMap<int32, UMaterialInterface*> TeamMaterials;
		int32 Parent = INDEX_NONE;
		FName ParentSocket;
		FTransform Transform = FTransform::Identity;
	};

	struct FLoadedAttachment
	{
		UStaticMesh* Mesh = nullptr;
		TMap<int32, UMaterialInterface*> TeamMaterials;
		int32 Parent = INDEX_NONE;
		FName Socket;
		FTransform Transform = FTransform::Identity;
	};
}

UCWSkeletalUnitPresentation* UCWSkeletalUnitPresentation::TryCreateConfigured(AActor* Owner, USceneComponent* Parent, FName VisualKey, int32 Team)
{
	// Preserve StoneEra's existing activation gates. Later eras use the explicit
	// EraArt enable flags; both routes still validate actual loaded assets.
	if (!Owner || !Parent || FParse::Param(FCommandLine::Get(), TEXT("cwlegacyart"))) return nullptr;
	const bool bStone = VisualKey == FName(TEXT("Unit_StoneSlinger")) || VisualKey == FName(TEXT("Unit_BeastRider")) ||
		VisualKey == FName(TEXT("Champion_Stone"));
	const bool bPreview = FParse::Param(FCommandLine::Get(), bStone ? TEXT("cwstoneerapreview") : TEXT("cwerapreview"));
	TSharedPtr<FJsonObject> Config;
	const cw::UnitDef* Definition = nullptr;
	if (!bStone)
	{
		Definition = CWEraArt::FindUnit(Owner, VisualKey);
		if (!Definition || Definition->Age <= 0) return nullptr;
		Config = CWEraArt::LoadEntry(VisualKey, TEXT("skeletal_unit"));
		if (!Config) return nullptr;
	}
	else
	{
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (!FFileHelper::LoadFileToString(Text, *(FPaths::ProjectContentDir() / TEXT("Data/StoneEraArt.json"))) ||
			!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid()) return nullptr;
		const TSharedPtr<FJsonObject>* Assets = nullptr;
		const TSharedPtr<FJsonObject>* Entry = nullptr;
		if (!Root->TryGetObjectField(TEXT("assets"), Assets) ||
			!(*Assets)->TryGetObjectField(VisualKey.ToString(), Entry)) return nullptr;
		Config = *Entry;
		const bool bDefault = Approved(Config, TEXT("default_runtime_enabled")) && Approved(Config, TEXT("gameplay_visual_review_approved"));
		if (!Approved(Config, TEXT("enabled")) || !(bDefault || (bPreview && Approved(Config, TEXT("preview_enabled")))) ||
			!Approved(Config, TEXT("ue_structural_approved")) || !Approved(Config, TEXT("animation_contract_verified"))) return nullptr;
	}
	FString AssetId;
	FString Style;
	double Height = 0.0, MoveSpeed = 0.0, Contact = 0.0;
	if (!Config->TryGetStringField(TEXT("asset_id"), AssetId) || AssetId != VisualKey.ToString() ||
		!Config->TryGetStringField(TEXT("attack_style"), Style) ||
		!Config->TryGetNumberField(TEXT("height_cm"), Height) || !FMath::IsFinite(Height) || Height <= 0.0 ||
		!Config->TryGetNumberField(TEXT("reference_move_speed"), MoveSpeed) || !FMath::IsFinite(MoveSpeed) || MoveSpeed <= 0.0 ||
		!Config->TryGetNumberField(TEXT("contact_time"), Contact) || !FMath::IsFinite(Contact) || Contact <= 0.0) return nullptr;
	ECWAttackStyle AttackStyleValue;
	if (Style == TEXT("Chop")) AttackStyleValue = ECWAttackStyle::Chop;
	else if (Style == TEXT("Thrust")) AttackStyleValue = ECWAttackStyle::Thrust;
	else if (Style == TEXT("Throw")) AttackStyleValue = ECWAttackStyle::Throw;
	else if (Style == TEXT("Shoot")) AttackStyleValue = ECWAttackStyle::Shoot;
	else if (Style == TEXT("Burst")) AttackStyleValue = ECWAttackStyle::Burst;
	else if (Style == TEXT("Cannon")) AttackStyleValue = ECWAttackStyle::Cannon;
	else return nullptr;
	if (Definition && FMath::Abs(Contact - Definition->AttackWindup) > 0.001) return nullptr;
	const TArray<TSharedPtr<FJsonValue>>* PartConfigs = nullptr;
	if (!Config->TryGetArrayField(TEXT("parts"), PartConfigs) || PartConfigs->IsEmpty() || PartConfigs->Num() > 8) return nullptr;
	TArray<FLoadedPart> LoadedParts;
	TMap<FString, int32> PartIds;
	for (const TSharedPtr<FJsonValue>& Value : *PartConfigs)
	{
		const TSharedPtr<FJsonObject>* PartConfig = nullptr;
		if (!Value->TryGetObject(PartConfig)) return nullptr;
		FLoadedPart Part;
		FString Path, ParentId, ParentSocket;
		const TSharedPtr<FJsonObject>* Animations = nullptr;
		if (!(*PartConfig)->TryGetStringField(TEXT("id"), Part.Id) || Part.Id.IsEmpty() || PartIds.Contains(Part.Id) ||
			!(*PartConfig)->TryGetStringField(TEXT("skeletal_mesh"), Path) || !IsArtPath(Path) ||
			!ReadTransform(*PartConfig, Part.Transform) ||
			!(*PartConfig)->TryGetObjectField(TEXT("animations"), Animations)) return nullptr;
		Part.Mesh = LoadObject<USkeletalMesh>(nullptr, *Path);
		if (!Part.Mesh || !Part.Mesh->GetSkeleton()) return nullptr;
		if ((*PartConfig)->TryGetStringField(TEXT("parent_part"), ParentId) && !ParentId.IsEmpty())
		{
			const int32* ParentIndex = PartIds.Find(ParentId);
			if (!ParentIndex || !(*PartConfig)->TryGetStringField(TEXT("parent_socket"), ParentSocket)) return nullptr;
			Part.Parent = *ParentIndex;
			Part.ParentSocket = FName(*ParentSocket);
			if (!HasSocketOrBone(LoadedParts[Part.Parent].Mesh, Part.ParentSocket)) return nullptr;
		}
		for (const TCHAR* Name : { TEXT("Idle"), TEXT("Move"), TEXT("Attack"), TEXT("Hit"), TEXT("Death") })
		{
			if (!(*Animations)->TryGetStringField(Name, Path) || !IsArtPath(Path)) return nullptr;
			UAnimSequence* Clip = LoadObject<UAnimSequence>(nullptr, *Path);
			if (!Clip || Clip->GetSkeleton() != Part.Mesh->GetSkeleton() || Clip->GetPlayLength() <= 0.f || Clip->bEnableRootMotion) return nullptr;
			Part.Clips.Add(FName(Name), Clip);
		}
		const float AttackLength = Part.Clips.FindChecked(TEXT("Attack"))->GetPlayLength();
		if (AttackLength <= Contact || (!LoadedParts.IsEmpty() &&
			FMath::Abs(AttackLength - LoadedParts[0].Clips.FindChecked(TEXT("Attack"))->GetPlayLength()) > 0.01f)) return nullptr;
		const TArray<TSharedPtr<FJsonValue>>* TeamMaterials = nullptr;
		if ((*PartConfig)->TryGetArrayField(TEXT("team_materials"), TeamMaterials))
		{
			if (bStone && !TeamMaterials->IsEmpty() && !Approved(Config, TEXT("team_material_structural_verified"))) return nullptr;
			for (const TSharedPtr<FJsonValue>& MaterialValue : *TeamMaterials)
			{
				const TSharedPtr<FJsonObject>* MaterialConfig = nullptr;
				int32 Slot;
				if (!MaterialValue->TryGetObject(MaterialConfig) ||
					!(*MaterialConfig)->TryGetNumberField(TEXT("slot"), Slot) || Slot < 0 || Slot >= Part.Mesh->GetMaterials().Num() ||
					Part.TeamMaterials.Contains(Slot) || !(*MaterialConfig)->TryGetStringField(TEXT("path"), Path) || !IsArtPath(Path)) return nullptr;
				FString RedPath;
				if ((*MaterialConfig)->TryGetStringField(TEXT("red_path"), RedPath))
				{
					if (!IsArtPath(RedPath)) return nullptr;
					if (Team == 1) Path = RedPath;
				}
				UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *Path);
				if (!Material) return nullptr;
				Part.TeamMaterials.Add(Slot, Material);
			}
		}
		PartIds.Add(Part.Id, LoadedParts.Num());
		LoadedParts.Add(MoveTemp(Part));
	}
	TArray<FLoadedAttachment> LoadedAttachments;
	const TArray<TSharedPtr<FJsonValue>>* AttachmentConfigs = nullptr;
	if (Config->TryGetArrayField(TEXT("attachments"), AttachmentConfigs))
	{
		for (const TSharedPtr<FJsonValue>& Value : *AttachmentConfigs)
		{
			const TSharedPtr<FJsonObject>* AttachmentConfig = nullptr;
			FLoadedAttachment Attachment;
			FString Path, ParentId, Socket;
			if (!Value->TryGetObject(AttachmentConfig) ||
				!(*AttachmentConfig)->TryGetStringField(TEXT("static_mesh"), Path) || !IsArtPath(Path) ||
				!(*AttachmentConfig)->TryGetStringField(TEXT("parent_part"), ParentId) ||
				!(*AttachmentConfig)->TryGetStringField(TEXT("socket"), Socket) ||
				!ReadTransform(*AttachmentConfig, Attachment.Transform)) return nullptr;
			const int32* ParentIndex = PartIds.Find(ParentId);
			if (!ParentIndex) return nullptr;
			Attachment.Parent = *ParentIndex;
			Attachment.Socket = FName(*Socket);
			Attachment.Mesh = LoadObject<UStaticMesh>(nullptr, *Path);
			if (!Attachment.Mesh || !HasSocketOrBone(LoadedParts[Attachment.Parent].Mesh, Attachment.Socket)) return nullptr;
			const TArray<TSharedPtr<FJsonValue>>* TeamMaterials = nullptr;
			if ((*AttachmentConfig)->TryGetArrayField(TEXT("team_materials"), TeamMaterials))
			{
				for (const TSharedPtr<FJsonValue>& MaterialValue : *TeamMaterials)
				{
					const TSharedPtr<FJsonObject>* MaterialConfig = nullptr;
					int32 Slot = INDEX_NONE;
					if (!MaterialValue->TryGetObject(MaterialConfig) ||
						!(*MaterialConfig)->TryGetNumberField(TEXT("slot"), Slot) || Slot < 0 || Slot >= Attachment.Mesh->GetStaticMaterials().Num() ||
						Attachment.TeamMaterials.Contains(Slot) || !(*MaterialConfig)->TryGetStringField(TEXT("path"), Path) || !IsArtPath(Path)) return nullptr;
					FString RedPath;
					if ((*MaterialConfig)->TryGetStringField(TEXT("red_path"), RedPath))
					{
						if (!IsArtPath(RedPath)) return nullptr;
						if (Team == 1) Path = RedPath;
					}
					UMaterialInterface* Material = LoadObject<UMaterialInterface>(nullptr, *Path);
					if (!Material) return nullptr;
					Attachment.TeamMaterials.Add(Slot, Material);
				}
			}
			LoadedAttachments.Add(MoveTemp(Attachment));
		}
	}
	int32 MuzzlePartIndex = INDEX_NONE;
	FString MuzzlePartId, MuzzleSocketName;
	if (Config->TryGetStringField(TEXT("muzzle_part"), MuzzlePartId))
	{
		const int32* Index = PartIds.Find(MuzzlePartId);
		if (!Index || !Config->TryGetStringField(TEXT("muzzle_socket"), MuzzleSocketName) ||
			!HasSocketOrBone(LoadedParts[*Index].Mesh, FName(*MuzzleSocketName))) return nullptr;
		MuzzlePartIndex = *Index;
	}
	if ((AttackStyleValue == ECWAttackStyle::Throw || AttackStyleValue == ECWAttackStyle::Shoot ||
		AttackStyleValue == ECWAttackStyle::Burst || AttackStyleValue == ECWAttackStyle::Cannon ||
		(Definition && Definition->ProjectileSpeed > 0.f)) && MuzzlePartIndex == INDEX_NONE) return nullptr;

	// All paths, clips, positive transforms and parent sockets are valid before
	// creating components; a failed configuration cleanly retains prototype art.
	auto* Presentation = NewObject<UCWSkeletalUnitPresentation>(Owner);
	Presentation->AssetKey = VisualKey;
	Presentation->VisualHeight = static_cast<float>(Height);
	Presentation->AttackStyle = AttackStyleValue;
	Presentation->ReferenceMoveSpeed = static_cast<float>(MoveSpeed);
	Presentation->ContactTime = static_cast<float>(Contact);
	Config->TryGetBoolField(TEXT("vehicle"), Presentation->bVehicle);
	Config->TryGetBoolField(TEXT("quadruped"), Presentation->bQuadruped);
	Presentation->StrideLength = static_cast<float>(MoveSpeed) * LoadedParts[0].Clips.FindChecked(TEXT("Move"))->GetPlayLength();
	TArray<USkeletalMeshComponent*> Components;
	for (int32 Index = 0; Index < LoadedParts.Num(); ++Index)
	{
		FLoadedPart& Part = LoadedParts[Index];
		auto* Component = NewObject<USkeletalMeshComponent>(Owner);
		Owner->AddInstanceComponent(Component);
		Component->SetupAttachment(Part.Parent == INDEX_NONE ? Parent : Components[Part.Parent], Part.ParentSocket);
		Component->SetRelativeTransform(Part.Transform);
		Component->SetSkeletalMesh(Part.Mesh);
		Component->SetAnimInstanceClass(UCWSmoothUnitAnimInstance::StaticClass());
		Component->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
		Component->bEnableUpdateRateOptimizations = false;
		Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Component->SetGenerateOverlapEvents(false);
		Component->bSuppressNotifyEventDispatch = true;
		Component->RegisterComponent();
		Component->SetComponentTickEnabled(false);
		for (const TPair<int32, UMaterialInterface*>& Material : Part.TeamMaterials)
		{
			if (UMaterialInstanceDynamic* Instance = Component->CreateDynamicMaterialInstance(Material.Key, Material.Value))
			{
				Instance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
				Instance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
			}
		}
		Components.Add(Component);
		if (Index == 0)
		{
			Presentation->Body = Component;
			Presentation->Clips = MoveTemp(Part.Clips);
		}
		else
		{
			FCWSkeletalArtPart RuntimePart;
			RuntimePart.Component = Component;
			RuntimePart.Clips = MoveTemp(Part.Clips);
			Presentation->AdditionalParts.Add(MoveTemp(RuntimePart));
		}
	}
	for (const FLoadedAttachment& Attachment : LoadedAttachments)
	{
		auto* Component = NewObject<UStaticMeshComponent>(Owner);
		Owner->AddInstanceComponent(Component);
		Component->SetupAttachment(Components[Attachment.Parent], Attachment.Socket);
		Component->SetRelativeTransform(Attachment.Transform);
		Component->SetStaticMesh(Attachment.Mesh);
		Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Component->SetGenerateOverlapEvents(false);
		Component->RegisterComponent();
		for (const TPair<int32, UMaterialInterface*>& Material : Attachment.TeamMaterials)
		{
			if (UMaterialInstanceDynamic* Instance = Component->CreateDynamicMaterialInstance(Material.Key, Material.Value))
			{
				Instance->SetVectorParameterValue(TEXT("TeamColor"), CWVisual::TeamColor(Team));
				Instance->SetScalarParameterValue(TEXT("TeamColorStrength"), 1.f);
			}
		}
		Presentation->Attachments.Add(Component);
	}
	if (MuzzlePartIndex != INDEX_NONE)
	{
		Presentation->MuzzlePart = Components[MuzzlePartIndex];
		Presentation->MuzzleSocket = FName(*MuzzleSocketName);
		Presentation->MuzzleAnchor = NewObject<USceneComponent>(Owner);
		Owner->AddInstanceComponent(Presentation->MuzzleAnchor);
		Presentation->MuzzleAnchor->SetupAttachment(Presentation->MuzzlePart, Presentation->MuzzleSocket);
		Presentation->MuzzleAnchor->RegisterComponent();
	}
	Presentation->Sample(TEXT("Idle"), 0.f);
	UE_LOG(LogTemp, Display, TEXT("%s asset=%s team=%d parts=%d attachments=%d height=%.2f contact=%.3f activation=%s damage_authority=server_only production_approved=false"),
		bStone ? TEXT("CIVWAR_STONE_ERA_ART") : TEXT("CIVWAR_ERA_ART"), *VisualKey.ToString(), Team, Components.Num(), LoadedAttachments.Num(), Height, Contact,
		bPreview ? TEXT("explicit_preview") : (bStone ? TEXT("reviewed_default") : TEXT("default_runtime")));
	return Presentation;
}
