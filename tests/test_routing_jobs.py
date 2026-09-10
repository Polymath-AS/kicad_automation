import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('routing', Path(__file__).parents[1] / 'scripts/kicad_routing.py')
routing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(routing)


def plan():
    return {'project': 'board/demo.kicad_pcb', 'steps': [
        {'operation': 'route', 'nets': ['*'], 'layers': ['BL_F_Cu']}], 'timeout_seconds': 10}


def clean():
    return {k: {'count': 0, 'findings': [], 'by_type': {}} for k in ('erc', 'drc')}


class RoutingTests(unittest.TestCase):
    def test_rejects_injected_arguments_and_invalid_numeric_constraints(self):
        for change in ({'nets': ['--overwrite']}, {'unknown': True},
                       {'grid_step': float('nan')}, {'via_size': .2, 'via_drill': .3},
                       {'layers': ['Edge.Cuts']}, {'layers': [42]}):
            p = plan()
            p['steps'][0].update(change)
            with self.assertRaises(ValueError):
                routing.validate_plan(p)

    def test_command_preserves_patterns_and_normalizes_layers(self):
        p = routing.validate_plan(plan())
        args = routing.command(Path('/router'), p['steps'][0], Path('/in'), Path('/out'))
        self.assertEqual(args[-4:], ['--nets', '*', '--layers', 'F.Cu'])
        self.assertNotIn('--overwrite', args)

    def test_placement_uses_conservative_defaults_and_safe_arguments(self):
        p = plan()
        p['placement'] = {'lock': ['J*', 'H*'], 'ignore_nets': ['GND'],
                          'max_displacement': 2, 'no_rotate': True}
        placement = routing.validate_plan(p)['placement']
        self.assertEqual(placement['crossing_penalty'], 30)
        self.assertEqual(placement['length_weight'], 0.3)
        args = routing.placement_command(
            Path('/router'), placement, Path('/project/demo.kicad_pcb'), Path('/out'))
        self.assertEqual(args[0], routing.sys.executable)
        self.assertEqual(Path(args[1]).name, 'place_optimize.py')
        self.assertEqual(Path(args[2]).name, 'demo.kicad_pcb')
        self.assertEqual(Path(args[3]).name, 'out')
        self.assertIn('--max-displacement', args)
        self.assertIn('--lock', args)
        self.assertIn('--ignore-nets', args)
        self.assertIn('--no-rotate', args)

    def test_placement_rejects_unsafe_or_inconsistent_options(self):
        for placement in ({'unknown': True}, {'max_displacement': float('nan')},
                          {'max_displacement': 2, 'swap_max_displacement': 3},
                          {'lock': ['--help']}, {'intent': '../outside.json'},
                          {'mode': 'reseat', 'move_refs': ['U3']},
                          {'mode': 'reseat', 'move_refs': ['U3'], 'intent': 'floorplan.json',
                           'no_swap': True}):
            p = plan()
            p['placement'] = placement
            with self.assertRaises(ValueError):
                routing.validate_plan(p)

    def test_optimize_move_refs_lock_every_other_footprint(self):
        p = plan()
        p['placement'] = {'move_refs': ['R12', 'C7'], 'lock': ['J*']}
        placement = routing.validate_plan(p)['placement']
        with patch.object(routing, '_footprint_references',
                          return_value={'U3', 'R12', 'R13', 'C7', 'J1'}):
            args = routing.placement_command(
                Path('/router'), placement, Path('/project/demo.kicad_pcb'), Path('/out'))
        lock_at = args.index('--lock')
        ignore_at = args.index('--max-displacement')
        locks = args[lock_at + 1:ignore_at] if lock_at < ignore_at else args[lock_at + 1:]
        self.assertIn('J*', locks)
        self.assertIn('U3', locks)
        self.assertIn('R13', locks)
        self.assertNotIn('R12', locks)
        self.assertNotIn('C7', locks)

    def test_reseat_selected_components_uses_intent_and_zero_eviction(self):
        with tempfile.TemporaryDirectory() as temp:
            board = Path(temp) / 'demo.kicad_pcb'
            board.write_text('board')
            (Path(temp) / 'floorplan.json').write_text('{}')
            p = plan()
            p['placement'] = {'mode': 'reseat', 'move_refs': ['U3', 'R12'],
                              'intent': 'floorplan.json'}
            placement = routing.validate_plan(p)['placement']
            args = routing.placement_command(Path('/router'), placement, board, Path('/out'))
        self.assertEqual(Path(args[1]).name, 'place_seed.py')
        self.assertEqual(args[args.index('--reseat') + 1:args.index('--evict-depth')], ['U3', 'R12'])
        self.assertEqual(args[args.index('--evict-depth') + 1], '0')

    def test_schema_v2_has_safe_fabrication_defaults_and_policy_arguments(self):
        p = plan()
        p['schema_version'] = 2
        p['steps'][0].update({
            'max_iterations': 5000, 'max_probe_iterations': 1000,
            'fab_tier': 'standard', 'escalation': 'off',
            'strict_sizes': True, 'no_fix_drc_settings': True,
            'board_edge_clearance': 0.25,
        })
        normalized = routing.validate_plan(p)
        self.assertTrue(normalized['steps'][0]['strict_sizes'])
        args = routing.command(Path('/router'), normalized['steps'][0], Path('/in'), Path('/out'))
        self.assertIn('--max-iterations', args)
        self.assertIn('--strict-sizes', args)
        self.assertIn('--board-edge-clearance', args)

    def test_schema_v2_rejects_conflicting_or_bad_policy_values(self):
        p = plan()
        p['schema_version'] = 2
        p['steps'][0].update({'force_reroute': True, 'keep_input_copper': True})
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            routing.validate_plan(p)
        p = plan()
        p['schema_version'] = 2
        p['steps'][0]['max_probe_iterations'] = 2.5
        with self.assertRaisesRegex(ValueError, 'integer'):
            routing.validate_plan(p)

    def test_differential_and_plane_controls_are_typed_and_dispatched(self):
        diff = plan()
        diff['steps'][0].update({
            'operation': 'diff', 'diff_pair_gap': 0.2, 'impedance': 90,
            'diff_pair_intra_match': True,
        })
        normalized = routing.validate_plan(diff)
        args = routing.command(Path('/router'), normalized['steps'][0], Path('/in'), Path('/out'))
        self.assertIn('--diff-pair-gap', args)
        self.assertIn('--impedance', args)
        self.assertIn('--diff-pair-intra-match', args)
        plane = plan()
        plane['steps'][0].update({
            'operation': 'planes', 'power_nets': ['VCC'], 'power_nets_widths': [0.5],
            'zone_clearance': 0.3, 'stitch_vias': True,
        })
        normalized = routing.validate_plan(plane)
        args = routing.command(Path('/router'), normalized['steps'][0], Path('/in'), Path('/out'))
        self.assertIn('--power-nets', args)
        self.assertIn('--power-nets-widths', args)
        self.assertIn('--zone-clearance', args)
        self.assertIn('--stitch-vias', args)

    def test_electrical_controls_cannot_leak_between_operations(self):
        p = plan()
        p['steps'][0].update({'operation': 'route', 'diff_pair_gap': 0.2})
        with self.assertRaisesRegex(ValueError, 'differential controls'):
            routing.validate_plan(p)

    def test_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                routing.contained(Path(temp), '../outside')

    def test_regressions_not_hidden_by_equal_counts(self):
        before, after = clean(), clean()
        before['drc']['findings'] = [{'type': 'clearance', 'items': [{'uuid': 'a'}]}]
        after['drc']['findings'] = [{'type': 'clearance', 'items': [{'uuid': 'b'}]}]
        self.assertTrue(routing.regression(before, after)['regressed'])

    def test_placement_comparison_ignores_positions_but_not_native_identity(self):
        before, after = clean(), clean()
        finding = {'type': 'clearance', 'description': 'same', 'uuid': 'derived-a',
                   'uuid_source': 'derived', 'items': [{'uuid': 'native-a', 'pos': {'x': 1, 'y': 2}}]}
        before['drc']['findings'] = [finding]
        moved = json.loads(json.dumps(finding))
        moved['uuid'] = 'derived-b'
        moved['items'][0]['pos'] = {'x': 3, 'y': 4}
        after['drc']['findings'] = [moved]
        self.assertFalse(routing.regression(before, after, ignore_positions=True)['regressed'])
        moved['items'][0]['uuid'] = 'native-b'
        self.assertTrue(routing.regression(before, after, ignore_positions=True)['regressed'])

    def test_candidate_rule_edits_restored_and_source_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'workspace/board'
            source.mkdir(parents=True)
            for suffix in ('.kicad_pcb', '.kicad_sch', '.kicad_pro'):
                (source / ('demo' + suffix)).write_text('original')
            def fake_run(args, log, timeout, cwd):
                Path(args[3]).write_text('routed')
                Path(args[3]).with_suffix('.kicad_pro').write_text('weakened')
                Path(args[2]).with_suffix('.kicad_pro').write_text('input weakened too')
                return 0
            with patch.object(routing, 'doctor', return_value={}), \
                 patch.object(routing, 'validate', return_value=clean()), \
                 patch.object(routing, 'run_process', side_effect=fake_run):
                result = routing.run_job(plan(), root/'workspace', root/'jobs', root/'krt')
            self.assertEqual(result['status'], 'candidate_clean')
            self.assertFalse(result['applied'])
            self.assertEqual(Path(result['candidate']).with_suffix('.kicad_pro').read_text(), 'original')
            self.assertTrue(all(p.read_text() == 'original' for p in source.iterdir()))

    def test_placement_runs_before_routing_on_isolated_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'workspace/board'
            source.mkdir(parents=True)
            for suffix in ('.kicad_pcb', '.kicad_sch', '.kicad_pro'):
                (source / ('demo' + suffix)).write_text('original')
            p = plan()
            p['placement'] = {'max_displacement': 2, 'lock': ['J*']}
            commands = []
            def fake_run(args, log, timeout, cwd):
                commands.append(Path(args[1]).name)
                Path(args[3]).write_text('candidate')
                return 0
            with patch.object(routing, 'doctor', return_value={}), \
                 patch.object(routing, 'validate', return_value=clean()), \
                 patch.object(routing, 'run_process', side_effect=fake_run):
                result = routing.run_job(p, root/'workspace', root/'jobs', root/'krt')
            self.assertEqual(commands, ['place_optimize.py', 'route.py'])
            self.assertEqual([step['operation'] for step in result['steps']], ['place', 'route'])
            self.assertTrue(result['source_unchanged'])

    def test_missing_output_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'workspace/board'
            source.mkdir(parents=True)
            for suffix in ('.kicad_pcb', '.kicad_sch', '.kicad_pro'):
                (source / ('demo' + suffix)).write_text('original')
            with patch.object(routing, 'doctor', return_value={}), \
                 patch.object(routing, 'validate', return_value=clean()), \
                 patch.object(routing, 'run_process', return_value=0):
                result = routing.run_job(plan(), root/'workspace', root/'jobs', root/'krt')
            self.assertEqual(result['status'], 'error')
            self.assertIn('did not produce', result['error'])
            self.assertTrue(result['source_unchanged'])

    def test_contract_hashes_detect_schematic_changes_and_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            board = root / 'demo.kicad_pcb'
            sch = root / 'demo.kicad_sch'
            board.write_text('board')
            sch.write_text('original')
            original = routing.contract_hashes(root)
            sch.write_text('changed')
            self.assertNotEqual(original, routing.contract_hashes(root))
            board.unlink()
            self.assertNotIn(board.name, routing.contract_hashes(root))

    def test_locked_source_rejected_before_job_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'workspace/board'
            source.mkdir(parents=True)
            for suffix in ('.kicad_pcb', '.kicad_sch', '.kicad_pro'):
                (source / ('demo' + suffix)).write_text('original')
            (source / '~demo.kicad_pcb.lck').write_text('locked')
            with patch.object(routing, 'doctor', return_value={}):
                with self.assertRaisesRegex(ValueError, 'locked'):
                    routing.run_job(plan(), root/'workspace', root/'jobs', root/'krt')
            self.assertFalse((root/'jobs').exists())


if __name__ == '__main__':
    unittest.main()
