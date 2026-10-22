from pathlib import Path
import re
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "Source/CivWar/View/CWPresentationDelayProbe.h").read_text(encoding="utf-8-sig")
SOURCE = (ROOT / "Source/CivWar/View/CWPresentationDelayProbe.cpp").read_text(encoding="utf-8-sig")
VIEW = (ROOT / "Source/CivWar/View/CWBattleView.cpp").read_text(encoding="utf-8-sig")
RUNNER = (ROOT / "Tools/review_stoneaxe_timing.ps1").read_text(encoding="utf-8-sig")


class PresentationDelayContractTests(unittest.TestCase):
    def test_fixed_delay_and_explicit_standalone_triple_gate(self):
        self.assertIn('RequestedDelay == TEXT("450") && bStandalone', SOURCE)
        self.assertIn('FParse::Param(FCommandLine::Get(), TEXT("cwstoneaxepilot"))', SOURCE)
        self.assertIn('FParse::Param(FCommandLine::Get(), TEXT("cwarttiming"))', SOURCE)
        self.assertIn('TEXT("cwartpresentationdelay=")', SOURCE)
        self.assertIn('GetNetMode() == NM_Standalone', VIEW)
        self.assertEqual(.45, float(re.search(r'DelaySeconds = ([0-9.]+);', HEADER).group(1)))

    def test_default_returns_original_reference_before_output_allocation(self):
        resolve = SOURCE.split('FCWPresentationDelayProbe::Resolve(', 1)[1]
        self.assertLess(resolve.index('if (!bEnabled) return OriginalItems;'), resolve.index('FrameItems.Reset('))
        self.assertIn('const TArray<FCWUnitNetItem>& OriginalItems', resolve)
        self.assertIn('const TArray<FCWUnitNetItem>& Resolve(', HEADER)

    def test_complete_payload_comparison_tracks_every_real_item_field(self):
        net = (ROOT / 'Source/CivWar/Net/CWNetTypes.h').read_text(encoding='utf-8-sig')
        structure = net.split('struct FCWUnitNetItem :', 1)[1].split('\n};', 1)[0]
        fields = re.findall(r'UPROPERTY\(\)\s+\w+\s+(\w+)\s*=', structure)
        equality = SOURCE.split('bool FCWPresentationDelayProbe::SameSnapshot(', 1)[1].split('\n}', 1)[0]
        expression = ' '.join(equality.split('return ', 1)[1].split(';', 1)[0].replace('&&', 'and').split())
        actual_fields = re.findall(r'First\.(\w+) == Second\.\1', expression)
        self.assertEqual(sorted(fields), sorted(actual_fields))
        self.assertRegex(expression, r'^[A-Za-z_\s.=&]+$')
        initial = {field: index for index, field in enumerate(fields)}
        first = SimpleNamespace(**initial)
        self.assertTrue(eval(expression, {'__builtins__': {}}, {'First': first, 'Second': SimpleNamespace(**initial)}))
        for field in fields:
            changed = dict(initial)
            changed[field] += 1
            self.assertFalse(eval(expression, {'__builtins__': {}}, {'First': first, 'Second': SimpleNamespace(**changed)}), field)
        self.assertEqual(initial, vars(first))

    def test_snapshot_values_are_copied_not_retimed_or_fabricated(self):
        self.assertIn('Snapshot.Item = Item;', SOURCE)
        self.assertIn('Queue.LastDelivered = Snapshot.Item;', SOURCE)
        self.assertIn('Snapshot.ArrivedAt = LocalNow;', SOURCE)
        self.assertNotRegex(SOURCE, r'(?:Snapshot\.Item|Item|Queue\.LastDelivered)\.\w+\s*=(?!=)')
        self.assertNotIn('CIVWAR_ART_TIMING', SOURCE)
        for forbidden in ('ServerCommand', 'DebugGrant', 'ResolveUnitAttack', 'SetTimeDilation', 'U.AttackSeq'):
            self.assertNotIn(forbidden, SOURCE)

    def test_first_attack_gate_and_normal_controls_remain(self):
        self.assertIn('!SelectedTeam[Item.Team]', SOURCE)
        self.assertIn('(Item.Flags & CWUnitFlags::Champion) == 0', SOURCE)
        self.assertIn('Data.Units[Item.Def].VisualKey == "Unit_StoneAxe"', SOURCE)
        self.assertIn('if (Item.AttackStartServerTime >= 0.f) Queue->bAttackObserved = true;', SOURCE)
        self.assertIn('if (Queue->bAttackObserved && bChanged) Enqueue(', SOURCE)
        self.assertRegex(SOURCE, r'if \(!Queue\)\s*\{\s*FrameItems.Add\(Item\);\s*continue;')

    def test_actual_delay_gate_never_delivers_early_failed_or_empty(self):
        expression = re.search(r'if \((!Queue.bFailed && !Queue.Pending.IsEmpty\(\) && LocalNow[^\n]+)\)', SOURCE).group(1)
        expression = expression.replace('!Queue.bFailed', 'not failed').replace('!Queue.Pending.IsEmpty()', 'not empty')
        expression = expression.replace('LocalNow', 'now').replace('Queue.Pending[0].ArrivedAt', 'arrived').replace('DelaySeconds', 'delay').replace('&&', 'and')
        self.assertRegex(expression, r'^[a-z0-9\s.()>=+]+$')
        for now, failed, empty, expected in ((10.449, False, False, False), (10.45, False, False, True), (11, True, False, False), (11, False, True, False)):
            self.assertEqual(expected, eval(expression, {'__builtins__': {}}, {'now': now, 'arrived': 10, 'delay': .45, 'failed': failed, 'empty': empty}))

    def test_fifo_delivers_once_per_unit_per_frame_and_removal_is_queued(self):
        resolve = SOURCE.split('FCWPresentationDelayProbe::Resolve(', 1)[1]
        self.assertNotIn('while (', resolve)
        self.assertEqual(1, resolve.count('Queue.Pending.RemoveAt(0, 1, EAllowShrinking::No);'))
        self.assertIn('Enqueue(Queue, Queue.LastReceived, LocalNow, ServerNow, true);', resolve)
        self.assertIn('if (Snapshot.bRemoval)', resolve)
        self.assertIn('Queue.bRemovalDelivered = true;', resolve)
        self.assertIn('if (Queue.bHasDelivered && !Queue.bRemovalDelivered) FrameItems.Add(Queue.LastDelivered);', resolve)
        self.assertIn('LocalNow >= Queue.Pending[0].ArrivedAt + DelaySeconds', resolve)

    def test_overflow_is_a_failure_not_silent_drop(self):
        enqueue = SOURCE.split('void FCWPresentationDelayProbe::Enqueue(', 1)[1].split('\nconst TArray', 1)[0]
        self.assertIn('MaximumPending = 64;', HEADER)
        self.assertIn('Queue.bFailed = true;', enqueue)
        self.assertIn('status=failed reason=queue_overflow', enqueue)
        self.assertLess(enqueue.index('Queue.bFailed = true;'), enqueue.index('Queue.Pending.AddDefaulted_GetRef();'))
        self.assertNotIn('Remove', enqueue)

    def test_new_match_replicator_and_shutdown_reset_owned_state(self):
        self.assertEqual(3, VIEW.count('PresentationDelayProbe.Reset();'))
        reset = SOURCE.split('void FCWPresentationDelayProbe::Reset()', 1)[1].split('\nbool FCW', 1)[0]
        for required in ('Queues.Reset();', 'FrameItems.Reset();', 'SelectedTeam[0] = false;', 'SelectedTeam[1] = false;', 'LastLocalNow = -1.0;'):
            self.assertIn(required, reset)

    def test_original_unit_update_loop_still_runs_once_and_clock_is_unmodified(self):
        loop = VIEW.split('for (const FCWUnitNetItem& Item : PresentationItems)', 1)[1].split('\n\tfor (auto It = Units.CreateIterator()', 1)[0]
        self.assertEqual(1, loop.count('Visual->ApplyNetState(Item);'))
        self.assertEqual(1, loop.count('Visual->UpdateVisual(Dt);'))
        self.assertIn('FPlatformTime::Seconds(), State->GetServerWorldTimeSeconds()', VIEW)
        self.assertNotIn('ServerNow - DelaySeconds', SOURCE)

    def test_runner_requires_explicit_test_and_keeps_network_approval_false(self):
        self.assertIn('[switch]$PresentationDelayTest', RUNNER)
        self.assertIn("if ($PresentationDelayTest) { '-cwartpresentationdelay=450' }", RUNNER)
        self.assertIn('network_timing_approved = $false', RUNNER)
        self.assertIn('if ($PresentationDelayTest -and (-not $delayEnabled -or $delayFailure))', RUNNER)
        self.assertIn('not network transmission, late-join, or production approval', RUNNER)


if __name__ == '__main__':
    unittest.main()
