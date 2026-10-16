import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException, UploadFile
from app.main import create_meeting


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_database_failure_removes_unregistered_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.main.UPLOAD_DIR', Path(directory)), patch('app.main.get_conn', side_effect=RuntimeError('offline')):
                tasks=BackgroundTasks()
                with self.assertRaises(HTTPException) as raised:
                    await create_meeting(tasks, UploadFile(filename='meeting.wav', file=io.BytesIO(b'audio')), None)
                self.assertEqual(raised.exception.status_code,503)
                self.assertEqual(list(Path(directory).iterdir()),[])
                self.assertEqual(tasks.tasks,[])

    async def test_upload_limit_is_checked_before_database_and_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('app.main.UPLOAD_DIR',Path(directory)), patch('app.main.MAX_UPLOAD_BYTES',4), patch('app.main.get_conn') as connect:
                with self.assertRaises(HTTPException) as raised:
                    await create_meeting(BackgroundTasks(), UploadFile(filename='large.wav',file=io.BytesIO(b'123456789')),None)
                self.assertEqual(raised.exception.status_code,413)
                connect.assert_not_called()
                self.assertEqual(list(Path(directory).iterdir()),[])

    async def test_success_preserves_audio_and_schedules_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            connection=Mock()
            connection.__enter__=Mock(return_value=connection)
            connection.__exit__=Mock(return_value=False)
            cursor=Mock()
            cursor.__enter__=Mock(return_value=cursor)
            cursor.__exit__=Mock(return_value=False)
            cursor.fetchone.return_value=(42,)
            connection.cursor.return_value=cursor
            with patch('app.main.UPLOAD_DIR',Path(directory)),patch('app.main.get_conn',return_value=connection):
                tasks=BackgroundTasks()
                result=await create_meeting(tasks,UploadFile(filename='meeting.wav',file=io.BytesIO(b'audio')),'Meeting')
                self.assertEqual(result.id,42)
                self.assertEqual(len(tasks.tasks),1)
                self.assertEqual(next(Path(directory).iterdir()).read_bytes(),b'audio')
