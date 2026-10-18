# SPDX-License-Identifier: MIT
import unittest
from axr_applications.wechat_database import empty_saved_draft,saved_draft_metadata

class SavedDraft(unittest.TestCase):
    def test_owner_diagnostics_do_not_export_text_or_unknown_field_names(self):
        for value in ('private body','{"private-key":"private body"}','<private-key>private body</private-key>'):
            result=str(saved_draft_metadata({'draft':value,'size':len(value.encode())}))
            self.assertNotIn('private body',result);self.assertNotIn('private-key',result)
    def test_storage_absence(self):
        for value,size in ((None,None),('',0),(b'',0)):
            with self.subTest(value=value):self.assertTrue(empty_saved_draft(value,size))
    def test_content_unknown_markup_entities_and_truncation_are_preserved(self):
        for value,size in ((None,20000),(' ',1),('<msg><text><content/></text></msg>',None),('<msg><content>text</content></msg>',None),
                           ('<msg attachment="x"/>',None),('<msg><image/></msg>',None),
                           ('<!DOCTYPE msg><msg/>',None),('<msg><!--text--></msg>',None),
                           ('<msg>&unknown;</msg>',None),('<msg>',None),(b'\xff',1)):
            if size is None and isinstance(value,str):size=len(value.encode())
            with self.subTest(value=value):self.assertFalse(empty_saved_draft(value,size))
