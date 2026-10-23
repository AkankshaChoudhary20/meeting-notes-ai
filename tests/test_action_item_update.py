import unittest

from pydantic import ValidationError
from app.schemas import ActionItemUpdate


class ActionItemUpdateTests(unittest.TestCase):
    def test_omitted_fields_stay_omitted(self):
        self.assertEqual(ActionItemUpdate().model_dump(exclude_unset=True), {})
        self.assertEqual(ActionItemUpdate(done=False).model_dump(exclude_unset=True), {'done': False})

    def test_nonnullable_database_fields_reject_explicit_null(self):
        for field in ('done', 'description'):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                ActionItemUpdate(**{field: None})

    def test_owner_can_be_cleared(self):
        self.assertEqual(ActionItemUpdate(owner=None).model_dump(exclude_unset=True), {'owner': None})

    def test_valid_description_is_preserved(self):
        self.assertEqual(ActionItemUpdate(description='Follow up').description, 'Follow up')
