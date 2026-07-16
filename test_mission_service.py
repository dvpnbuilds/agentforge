import tempfile
import unittest
from pathlib import Path

from mission_service import MissionService


class FakeAdapter:
    def __init__(self):
        self.created = []
        self.task = {'id': 't_real', 'status': 'todo', 'assignee': 'research', 'result': ''}
        self.show_payload = None
        self.runs = []

    def create_task(self, **kwargs):
        self.created.append(kwargs)
        return {'id': 't_real', 'status': 'todo'}

    def show_task(self, task_id):
        return self.show_payload or dict(self.task)

    def task_runs(self, task_id):
        return list(self.runs)

    def comment(self, task_id, text, author='agentforge'):
        return 'ok'


class MissionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / 'board.db'
        self.adapter = FakeAdapter()
        self.service = MissionService(self.db_path, adapter=self.adapter)
        self.service.init_schema()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_create_is_idempotent_and_routes_research_profile(self):
        payload = {
            'desired_outcome': 'Research the current stable Python release.',
            'success_criteria': 'Return version, release date, and two official source URLs.',
            'context': 'Use python.org sources.',
            'idempotency_key': 'reset-b-proof-1',
        }
        first = self.service.create_mission(payload)
        second = self.service.create_mission(payload)
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(len(self.adapter.created), 1)
        self.assertEqual(first['hermes_task_id'], 't_real')
        self.assertEqual(first['profile'], 'research')
        self.assertIn('Return source URLs', self.adapter.created[0]['body'])

    def test_invalid_profile_is_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'research'):
            self.service.create_mission({
                'desired_outcome': 'Do something',
                'success_criteria': 'Return proof',
                'profile': 'dev',
            })
        self.assertEqual(self.adapter.created, [])

    def test_blocked_task_maps_to_needs_input_without_artifact(self):
        mission = self.service.create_mission({
            'desired_outcome': 'Research a private system.',
            'success_criteria': 'Return evidence.',
        })
        self.adapter.show_payload = {
            'task': {'id': 't_real', 'status': 'blocked', 'assignee': 'research'},
            'comments': [{'author': 'research', 'body': 'Need private API access'}],
        }
        synced = self.service.sync_mission(mission['id'])
        self.assertEqual(synced['state'], 'needs_input')
        self.assertEqual(synced['artifacts'], [])
        self.assertIn('Need private API access', synced['operator_message'])

    def test_completed_task_creates_real_artifact_and_review_persists(self):
        mission = self.service.create_mission({
            'desired_outcome': 'Research Python release.',
            'success_criteria': 'Return sourced facts.',
        })
        self.adapter.task = {
            'id': 't_real',
            'status': 'done',
            'assignee': 'research',
            'result': 'Python 3.14.0 was released. Sources: https://python.org/a and https://python.org/b',
        }
        self.adapter.runs = [{'id': 'run_1', 'profile': 'research', 'outcome': 'completed', 'summary': 'Used web search and official pages.'}]
        synced = self.service.sync_mission(mission['id'])
        self.assertEqual(synced['state'], 'needs_review')
        self.assertEqual(len(synced['artifacts']), 1)
        artifact = synced['artifacts'][0]
        self.assertEqual(artifact['hermes_run_id'], 'run_1')
        self.assertEqual(artifact['worker_profile'], 'research')
        self.assertEqual(len(artifact['sources']), 2)
        reviewed = self.service.review_mission(mission['id'], {'action': 'approve', 'note': 'Verified.'})
        self.assertEqual(reviewed['state'], 'completed')
        self.assertEqual(reviewed['artifacts'][0]['review_status'], 'approved')
        self.assertEqual(reviewed['reviews'][0]['action'], 'approve')
        synced_after_review = self.service.sync_mission(mission['id'])
        self.assertEqual(synced_after_review['state'], 'completed')
        self.assertEqual(synced_after_review['artifacts'][0]['review_status'], 'approved')


if __name__ == '__main__':
    unittest.main()
