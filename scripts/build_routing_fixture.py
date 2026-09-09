#!/usr/bin/env python3
"""Create the two-terminal integration fixture through the live KiCad MCP server.

Run once from repository root. Refuses to overwrite an existing fixture.
Docker Desktop and the fixture-hosted KiCad MCP service must be running.
"""
import os
import json
import argparse
from pathlib import Path
import subprocess
import time

from kicad_mcp_client import DEFAULT_URL, DEFAULT_TOKEN, request

STEM = 'tests/fixtures/krt-smoke/krt-smoke'


def call(name, arguments=None):
    result = request(DEFAULT_URL, os.environ.get('KICAD_MCP_AUTH_TOKEN', DEFAULT_TOKEN),
                     'tools/call', {'name': name, 'arguments': arguments or {}}, 120)['result']
    if result.get('isError'):
        raise RuntimeError(result)
    message = json.dumps(result)
    if 'Refusing ' in message or 'was not found' in message or 'Failed ' in message:
        raise RuntimeError(message)
    print(name, json.dumps(result.get('structuredContent', result), ensure_ascii=True)[:1500], flush=True)
    return result


def preflight():
    for name in ('kicad_get_server_info', 'kicad_get_project_info', 'pcb_get_board_summary'):
        call(name)


def validate():
    code = subprocess.call(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                            '-File', 'tools/kicad-docker.ps1', 'validate', STEM, '--erc', '--drc'])
    # An intentionally unrouted board has DRC violations. Reports are preserved.
    if code not in (0, 1):
        raise RuntimeError(f'validation invocation failed: {code}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--finish-existing', action='store_true',
                        help='Finish placement of an existing generated test fixture')
    args = parser.parse_args()
    if Path(STEM + '.kicad_pro').exists() and not args.finish_existing:
        raise RuntimeError('fixture exists; refusing to overwrite')
    preflight()
    if not args.finish_existing:
        call('kicad_create_new_project', {'path': '/workspace/tests/fixtures', 'name': 'krt-smoke'})
        validate()
        call('sch_build_circuit', {'auto_layout': True, 'symbols': [
            {'library': 'Connector_Generic', 'symbol_name': 'Conn_01x01', 'reference': ref,
             'value': 'TEST', 'footprint': 'Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical'}
            for ref in ('J1', 'J2')], 'nets': [{'name': 'SIGNAL', 'pins': ['J1.1', 'J2.1']}]})
        validate()
    call('pcb_sync_from_schematic', {'auto_place': False, 'allow_open_board': True})
    validate()
    env = dict(os.environ, KICAD_ENTRYPOINT_PROJECT=STEM+'.kicad_pcb')
    subprocess.run(['docker', 'compose', 'up', '-d', '--force-recreate', 'kicad'], env=env, check=True)
    for attempt in range(90):
        try:
            call('kicad_get_project_info')
            break
        except Exception:
            time.sleep(1)
    preflight()
    for ref, x in (('J1', 30), ('J2', 50)):
        call('pcb_move_footprint', {'reference': ref, 'x_mm': x, 'y_mm': 30})
        call('pcb_save')
        validate()
    call('pcb_set_board_outline', {'origin_x_mm': 20, 'origin_y_mm': 20,
                                   'width_mm': 50, 'height_mm': 30})
    call('pcb_save')
    validate()
    call('pcb_get_board_summary')
    # Release the fixture lock so the batch router can consume the saved project.
    subprocess.run(['docker', 'compose', 'stop', 'kicad'], check=True)


if __name__ == '__main__':
    main()
