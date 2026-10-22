// 血战文明 - 音效播放
// 音效资源由 Tools/gen_sfx.py 程序化合成（原创），经 Tools/Unreal/import_audio.py 导入。
// 资源不存在时静默跳过，不影响游戏运行。
#pragma once

#include "CoreMinimal.h"

class USoundBase;
class USoundWave;

namespace CWAudio
{
	enum class ESound : uint8
	{
		Swing,
		HitFlesh,
		HitMetal,
		Sling,
		Bow,
		Gun,
		MachineGun,
		Cannon,
		Explosion,
		Death,
		BaseHit,
		AgeUp,
		UIClick,
		UIError,
		Train,
		Victory,
		Defeat,
		SkillWarning,
		TurretBuild,
		MeteorFall,
		Laser,
		Rocket,
		Count
	};

	enum class EChannel : uint8 { Master, Battle, Interface, Announcements, Music, Count };
	// 值域 0..1；自动读取 GameUserSettings.ini，影响 Slate 点击和已播放的声音。
	float GetVolume(EChannel Channel);
	void SetVolume(EChannel Channel, float Volume);
	// A shared mute gate preserves every slider value and survives UI recreation.
	bool IsMuted();
	void SetMuted(bool bMuted);
	// 在滑块操作结束或关闭设置面板时保存，避免拖动时每帧写磁盘。
	void SaveSettings();
	// Music uses the same native class mix as effects; playback survives map travel.
	void ConfigureMusic(USoundWave* Wave);

	USoundBase* Get(ESound Sound);
	// 界面与结算音效（不做空间化）
	void Play2D(const UObject* WorldContext, ESound Sound, float Volume = 1.f, float Pitch = 1.f);
	// 战场音效：空间化、材料变体、事件级节流与共享并发上限；纯客户端播放。
	void PlayAt(const UObject* WorldContext, ESound Sound, const FVector& Location, float Volume = 1.f, float Pitch = 1.f);
}
