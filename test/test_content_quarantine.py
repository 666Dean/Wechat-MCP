# SPDX-License-Identifier: MIT
"""Real isolated parsing plus adversarial type/archive/metadata fixtures."""
import base64,io,json,os,socket,sys,tempfile,unittest,zipfile
from pathlib import Path
from types import SimpleNamespace
from axr.aet import AXRError
from axr.storage import Vault
from axr.host import Supervisor,Sandbox
from axr.quarantine import ContentQuarantine
from axr.quarantine_parser import extract_safe_text,ContentError

class StaticContent(unittest.TestCase):
    def zip(self,items):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as archive:
            for name,body in items:archive.writestr(name,body)
        return b.getvalue()
    def test_executable_type_spoofing_and_archive_escapes_are_quarantined(self):
        for body,name in [(b'MZfixture','notes.txt'),(b'\x7fELFfixture','notes.md'),(b'PK\x03\x04fixture','notes.txt'),(b'not pdf','notes.pdf')]:
            with self.subTest(name=name),self.assertRaises(ContentError):extract_safe_text(body,name)
        for name in ('../outside.txt','/absolute.txt','C:payload.txt','nested\\outside.txt'):
            with self.subTest(name=name),self.assertRaises(ContentError):extract_safe_text(self.zip([(name,b'fixture')]),'archive.zip')
    def test_macros_refused_external_relationships_never_fetched(self):
        xml=b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>fixture</w:t></w:r></w:p></w:document>'
        for extra in ('word/vbaProject.bin','word/embeddings/object.bin','word/activeX/control.xml'):
            with self.assertRaises(ContentError):extract_safe_text(self.zip([('word/document.xml',xml),(extra,b'fixture')]),'notes.docx')
        safe=extract_safe_text(self.zip([('word/document.xml',xml),('word/_rels/document.xml.rels',b'<Relationship Target="https://not-fetched.invalid" TargetMode="External"/>')]),'notes.docx')
        self.assertEqual(safe['text'],'fixture');self.assertFalse(safe['remote_resources_loaded'])
    def test_archive_depth_and_duplicate_members_are_bounded(self):
        content=b'fixture';name='notes.txt'
        for _ in range(5):content=self.zip([(name,content)]);name='nested.zip'
        with self.assertRaises(ContentError):extract_safe_text(content,name)
        with self.assertWarns(UserWarning):content=self.zip([('same.txt',b'one'),('same.txt',b'two')])
        with self.assertRaises(ContentError):extract_safe_text(content,'notes.zip')
    def test_scripts_are_data_and_never_execution_authority(self):
        for name in ('notes.py','notes.sh','notes.ps1','notes.js'):
            result=extract_safe_text(b'fixture commands are text',name)
            self.assertEqual(result['content_kind'],'code-as-data');self.assertFalse(result['execution_allowed'])

class RuntimeLayout(unittest.TestCase):
    def test_framework_uses_real_interpreter_and_pins_its_linked_library(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();launcher=base/'bin/python';library=base/'Python';binary=base/'Resources/Python.app/Contents/MacOS/Python'
            for path in (launcher,library,binary):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic runtime')
            with patch.object(sys,'executable',str(launcher)),patch.object(sys,'base_prefix',str(base)),patch('axr.quarantine.sysconfig.get_config_var',return_value='Python'):
                executable,roots,pins=ContentQuarantine._mac_runtime()
            self.assertEqual(executable,binary);self.assertIn(str(library),roots);self.assertIn(library,pins);self.assertIn(binary,pins)
            self.assertNotIn(str(base),roots)

class IsolatedContent(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='AXR 隔离 fixture ');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve();self.store=SimpleNamespace(directory=self.root,vault=Vault(b'v'*32))
    def test_real_parser_isolated_cache_and_changed_policy(self):
        if sys.platform not in ('darwin','win32'):self.skipTest('native platform sandbox required')
        launcher=os.environ.get('AXR_TEST_WINDOWS_LAUNCHER')
        if sys.platform=='win32' and not launcher:self.skipTest('native Windows launcher not provided')
        q=ContentQuarantine(self.store,windows_launcher=launcher)
        first=q.inspect(b'fixture text','notes.txt',source='task:one',policy_version=1,check=lambda:None)
        self.assertEqual(first['text'],'fixture text');self.assertTrue(first['sandbox_enforced'])
        second=q.inspect(b'fixture text','notes.txt',source='task:one',policy_version=2,check=lambda:None)
        self.assertEqual(second['policy_version'],2)
        self.assertEqual(len(list(q.directory.glob('*.sealed'))),2)
        self.assertNotIn(b'fixture text',next(q.directory.glob('*.sealed')).read_bytes())
        with self.assertRaises(AXRError):q.inspect(b'MZfixture','notes.txt',source='task:one',policy_version=2,check=lambda:None)
    @unittest.skipUnless(sys.platform=='darwin','real macOS OS sandbox')
    def test_same_profile_denies_private_file_loopback_and_other_executable(self):
        q=ContentQuarantine(self.store);command,sandbox=q._invocation()
        private=self.root/'private.txt';private.write_text('synthetic secret')
        code='''import json,socket,subprocess
r={}
try:open(PATH).read();r['file']=True
except OSError:r['file']=False
s=socket.socket();s.settimeout(.5)
try:s.connect(('127.0.0.1',PORT));r['network']=True
except OSError:r['network']=False
try:subprocess.run(['/bin/echo','fixture'],check=True,capture_output=True);r['exec']=True
except OSError:r['exec']=False
print(json.dumps(r))'''
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1)
            code=code.replace('PATH',repr(str(private))).replace('PORT',str(listener.getsockname()[1]))
            result=Supervisor(timeout=5).invoke([command[0],'-I','-S','-c',code],{},sandbox=sandbox)['result']
        self.assertEqual(result,{'file':False,'network':False,'exec':False})
