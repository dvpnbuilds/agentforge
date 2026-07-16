import json
import subprocess
import unittest
from unittest.mock import Mock

from hermes_kanban_adapter import HermesKanbanAdapter, KanbanCommandError


class HermesKanbanAdapterTests(unittest.TestCase):
    def make_adapter(self, result=None, side_effect=None):
        runner = Mock()
        if side_effect:
            runner.side_effect = side_effect
        else:
            runner.return_value = result or subprocess.CompletedProcess([], 0, stdout='{}', stderr='')
        return HermesKanbanAdapter(runner=runner, timeout=7), runner

    def test_create_uses_safe_argument_array_and_idempotency(self):
        adapter, runner = self.make_adapter(subprocess.CompletedProcess([], 0, stdout=json.dumps({'id': 't_1'}), stderr=''))
        task = adapter.create_task(
            title='Research current Python release',
            body='Use a real web source and return URLs.',
            assignee='research',
            idempotency_key='agentforge:m1:research:1',
        )
        self.assertEqual(task['id'], 't_1')
        args = runner.call_args.args[0]
        self.assertEqual(args[:4], ['hermes', 'kanban', '--board', 'agentforge'])
        self.assertIn('--json', args)
        self.assertEqual(args[args.index('--assignee') + 1], 'research')
        self.assertEqual(args[args.index('--idempotency-key') + 1], 'agentforge:m1:research:1')
        self.assertNotIn('shell', runner.call_args.kwargs)
        self.assertEqual(runner.call_args.kwargs['timeout'], 7)

    def test_body_size_is_limited(self):
        adapter, _ = self.make_adapter()
        with self.assertRaisesRegex(ValueError, 'body exceeds'):
            adapter.create_task(title='x', body='a' * 20001, assignee='research', idempotency_key='k')

    def test_non_zero_exit_is_readable(self):
        adapter, _ = self.make_adapter(subprocess.CompletedProcess([], 2, stdout='', stderr='profile not found'))
        with self.assertRaisesRegex(KanbanCommandError, 'profile not found'):
            adapter.list_tasks()

    def test_timeout_is_wrapped(self):
        adapter, _ = self.make_adapter(side_effect=subprocess.TimeoutExpired(['hermes'], 7))
        with self.assertRaisesRegex(KanbanCommandError, 'timed out'):
            adapter.list_tasks()

    def test_malformed_json_is_rejected(self):
        adapter, _ = self.make_adapter(subprocess.CompletedProcess([], 0, stdout='not-json', stderr=''))
        with self.assertRaisesRegex(KanbanCommandError, 'malformed JSON'):
            adapter.list_tasks()

    def test_show_runs_block_and_archive_commands_are_allowlisted(self):
        adapter, runner = self.make_adapter(subprocess.CompletedProcess([], 0, stdout=json.dumps({'id': 't_1'}), stderr=''))
        adapter.show_task('t_1')
        adapter.task_runs('t_1')
        adapter.block_task('t_1', 'Need API access')
        adapter.archive_task('t_1')
        commands = [call.args[0][4] for call in runner.call_args_list]
        self.assertEqual(commands, ['show', 'runs', 'block', 'archive'])


if __name__ == '__main__':
    unittest.main()
