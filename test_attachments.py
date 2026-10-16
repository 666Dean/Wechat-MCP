# SPDX-License-Identifier: MIT
import hashlib
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
try:
    from axr.aet import AXRError
except ModuleNotFoundError:raise unittest.SkipTest('AXR optional')
from adapters.attachments import file_metadata,AttachmentResolver,extract_text,MAX_FILE


def xml(name='notes.txt',content=b'work notes'):
    return '<msg><appmsg><title>'+name+'</title><type>6</type><appattach><totallen>'+str(len(content))+'</totallen><md5>'+hashlib.md5(content).hexdigest()+'</md5></appattach></appmsg></msg>'


class Attachments(unittest.TestCase):
    def test_source_hash_local_cache_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();path=root/'cache.bin';path.write_bytes(b'work notes')
            resolver=AttachmentResolver({'enabled':True,'cache_roots':[str(root)]})
            meta=file_metadata(xml());result=resolver.resolve(meta)
            self.assertEqual(extract_text(result['content'],meta['filename'])['text'],'work notes')
            path.write_bytes(b'fake notes')
            with self.assertRaisesRegex(AXRError,'not_cached'):resolver.resolve(meta)
    def test_sensitive_filename_is_masked_without_losing_parser_format(self):
        metadata=file_metadata(xml('password=fixture-secret.docx'))
        self.assertNotIn('fixture-secret',str(metadata))
        self.assertTrue(metadata['filename'].endswith('.docx'))
    def test_xml_entity_and_path_injection_rejected(self):
        for body in [xml('../outside.txt'),xml('a/b.txt'),xml('a\\b.txt'),
            '<!DOCTYPE msg [<!ENTITY x SYSTEM "file:///private/secret">]><msg><appmsg><type>6</type><title>&x;</title></appmsg></msg>']:
            with self.assertRaises(AXRError):file_metadata(body)
        self.assertIsNone(file_metadata('<msg><appmsg><type>5</type></appmsg></msg>'))
    def test_docx_text_and_zip_bomb_refused(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Meeting at 3</w:t></w:r></w:p></w:document>')
        self.assertEqual(extract_text(buf.getvalue(),'agenda.docx')['text'],'Meeting at 3')
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('word/document.xml','a'*1000000)
        with self.assertRaisesRegex(AXRError,'archive_budget'):extract_text(buf.getvalue(),'bad.docx')
    def test_executable_encrypted_unknown_and_output_budgets(self):
        for name in ['run.exe','macro.docm','image.png']:
            with self.assertRaisesRegex(AXRError,'unsupported'):extract_text(b'anything',name)
        script=extract_text(b'print(123)','run.py')
        self.assertEqual(script['content_kind'],'code-as-data');self.assertFalse(script['execution_allowed'])
        with self.assertRaises(AXRError):extract_text(b'x'*(MAX_FILE+1),'big.txt')
        self.assertTrue(extract_text(b'x'*30000,'normal.txt')['truncated'])
    @unittest.skipIf(os.name=='nt','Windows unprivileged symlink unavailable')
    def test_cache_links_cannot_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();cache=root/'cache';cache.mkdir();(root/'secret').write_bytes(b'work notes')
            (cache/'link').symlink_to(root/'secret')
            with self.assertRaisesRegex(AXRError,'not_cached'):
                AttachmentResolver({'enabled':True,'cache_roots':[str(cache)]}).resolve(file_metadata(xml()))

class AttachmentPDF(unittest.TestCase):
    def test_real_pdf_text_and_encrypted_document_refused(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter();page=writer.add_blank_page(width=300,height=200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 20 120 Td (Fixture meeting agenda) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(content)
        stream=io.BytesIO();writer.write(stream)
        self.assertIn('Fixture meeting agenda',extract_text(stream.getvalue(),'agenda.pdf')['text'])
        writer.encrypt('fixture-only');stream=io.BytesIO();writer.write(stream)
        with self.assertRaisesRegex(AXRError,'encrypted'):extract_text(stream.getvalue(),'encrypted.pdf')

class CompoundFileMessages(unittest.TestCase):
    def test_wcdb_compound_file_kind_preserves_sender_and_source(self):
        import sqlite3
        import test_axr
        fixture=test_axr.DatabasePages();fixture.setUp()
        try:
            fixture.adapter.config['attachments_enabled']=True
            db=sqlite3.connect(fixture.paths[0])
            try:
                with db:
                    db.execute(f'INSERT INTO "{fixture.table}" VALUES(?,?,?,?,?,?)',
                        (31,41,(6<<32)|49,105,19,xml('agenda.txt')))
            finally:db.close()
            page=fixture.adapter.search(fixture.chat,attachments_only=True,limit=6)
            self.assertEqual(len(page['messages']),1)
            message=page['messages'][0]
            self.assertEqual(message['attachment']['filename'],'agenda.txt')
            self.assertEqual(message['sender'],fixture.chat);self.assertFalse(message['outgoing'])
            self.assertTrue(message['reference']);self.assertNotIn('<appmsg>',message['text'])
            fixture.adapter.config['attachments_enabled']=False
            self.assertEqual(fixture.adapter.search(fixture.chat,attachments_only=True)['messages'],[])
        finally:fixture.tearDown()
