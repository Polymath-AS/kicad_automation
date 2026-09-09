"""Run inside the optional routing image; exercises real stdio MCP and Rust routing."""
import asyncio
import json
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command=sys.executable,
                                  args=['/opt/krt-adapter/kicad_routing.py', 'mcp'])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            catalog = await session.list_tools()
            tools = {tool.name: tool for tool in catalog.tools}
            assert set(tools) == {'routing_tools_info', 'routing_run_candidate', 'routing_plan_trace', 'routing_job_result'}
            schema = tools['routing_run_candidate'].inputSchema
            assert 'RoutingStep' in json.dumps(schema), schema
            invalid = await session.call_tool('routing_run_candidate', {'plan': {
                'project': 'unused.kicad_pcb', 'steps': [
                    {'operation': 'route', 'nets': ['*'], 'layers': ['F.Cu'], 'overwrite': True}]}})
            assert invalid.isError, invalid
            info = await session.call_tool('routing_tools_info', {})
            assert not info.isError, info
            plan = json.loads(Path('/workspace/routing-plans/smoke.json').read_text())
            response = await session.call_tool('routing_run_candidate', {'plan': plan})
            assert not response.isError, response
            result = json.loads(response.content[0].text)
            assert result['status'] == 'needs_review', result
            assert result['comparison'] == {'new_nonconnectivity_findings': 0,
                                           'unconnected_before': 1, 'unconnected_after': 0,
                                           'regressed': False}, result
            assert result['steps'][-1]['validation']['erc']['count'] == 0, result
            assert result['steps'][-1]['validation']['drc']['by_type'] == {
                'footprint_symbol_mismatch': 2}, result
            assert result['source_unchanged'] and not result['applied'], result
            assert '(segment' in Path(result['candidate']).read_text(), result
            restored = await session.call_tool('routing_job_result', {'job_id': result['job_id']})
            assert json.loads(restored.content[0].text) == result
            bad = await session.call_tool('routing_job_result', {'job_id': '../escape'})
            assert bad.isError, bad
            print(json.dumps({'status': 'pass', 'job_id': result['job_id'],
                              'candidate_status': result['status'],
                              'comparison': result['comparison'], 'tools': list(tools)}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
