# SPDX-License-Identifier: MIT
import unittest
from axr_applications.wechat_burst import BurstBuffer
from axr_applications.wechat_database import actor_records

def row(n,outgoing=False):return {'reference':str(n),'text':'Synthetic '+str(n),'outgoing':outgoing,'created':100+n,'local_id':n}

class BurstTests(unittest.TestCase):
    def test_waiting_sources_and_reserved_budget_do_not_consume_unhandled_messages(self):
        b=BurstBuffer();b.add('peer',[row(1)],False,0);b.add('other',[row(2)],False,0)
        self.assertEqual(b.ready(5,limit=0),[]);self.assertEqual(len(b.pending),2)
        batch=b.ready(5,limit=1,blocked={'peer'});self.assertEqual(batch[0][0],'other')
        self.assertIn('peer',b.pending);self.assertEqual(b.ready(6)[0][0],'peer')
    def test_waits_for_quiet_then_one_combined_reply_with_source_local_context(self):
        b=BurstBuffer();b.add('peer',[row(1,True)],False,0);b.add('other',[row(9)],False,0)
        b.add('peer',[row(2)],False,1);self.assertEqual(b.ready(2),[])
        b.add('peer',[row(3)],False,2);ready=b.ready(5)
        peer=next(v for v in ready if v[0]=='peer')
        self.assertEqual([r['reference'] for r in peer[1]],['1','2','3'])
        self.assertEqual([r['reference'] for r in peer[2]],['2','3'])
        self.assertEqual(b.ready(6),[])
        records=actor_records({'messages':peer[1]},include_outgoing=True)
        self.assertEqual(records[0]['direction'],'outgoing-context')
        self.assertNotIn('direction',records[1])
        self.assertEqual(len(actor_records({'messages':peer[1]})),2)
    def test_page_drain_and_bounded_batches_without_replay(self):
        b=BurstBuffer();b.add('peer',[row(i) for i in range(1,7)],True,0)
        self.assertEqual(b.ready(20),[])
        b.add('peer',[row(7)],False,20)
        first=b.ready(21);self.assertEqual(len(first),1);self.assertEqual(len(first[0][2]),6)
        second=b.ready(25);self.assertEqual(len(second[0][1]),6);self.assertEqual(second[0][2],[row(7)])
        self.assertEqual(b.ready(40),[])
    def test_stop_clears_pending_context_and_expired_messages_are_not_replied(self):
        b=BurstBuffer();b.add('peer',[row(1)],False,0);b.clear()
        self.assertEqual(b.ready(10),[]);self.assertEqual(b.context,{})
        b.add('peer',[row(1)],False,0);self.assertEqual(b.ready(901),[])
    def test_sustained_burst_has_maximum_wait_and_six_record_budget(self):
        b=BurstBuffer()
        for n in range(1,8):b.add('peer',[row(n)],False,n*2)
        batch=b.ready(14)
        self.assertEqual(len(batch),1);self.assertEqual(len(batch[0][1]),6)
    def test_capacity_rejection_never_appends_beyond_budget(self):
        from axr.aet import AXRError
        b=BurstBuffer()
        for start in range(0,96,6):b.add('peer',[row(i) for i in range(start,start+6)],True,start)
        with self.assertRaisesRegex(AXRError,'burst_capacity'):b.add('peer',[row(96)],False,97)
        self.assertEqual(len(b.pending['peer']['rows']),96)
        b.clear();self.assertEqual(b.ready(100),[])
