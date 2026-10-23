"""Contraexemplos: estados ausentes, caminhos alternativos e narrativa falsa."""
import copy
import tempfile
import unittest
from pathlib import Path
from laboratorios.parte1.common import PROJECT, material, read, write, seal, integrity
from laboratorios.parte1 import requirements as r, architecture as a, controls as c, observatory as o
from laboratorios.parte1 import evidence


class Requirements(unittest.TestCase):
    def test_six_positive_negative_unknown(self):
        result = r.assess(material('inventario.json'))
        self.assertEqual(len(result['observations']), 18)
        for state in ('satisfied','violated','unknown'):
            self.assertEqual(sum(x['outcome']==state for x in result['observations']),6)

    def test_missing_field_unknown(self):
        self.assertEqual(r.evaluate('R03',{'public':True}),'unknown')

    def test_string_boolean_unknown(self):
        self.assertEqual(r.evaluate('R03',dict(principal_tenant='a',resource_tenant='b',public='false')),'unknown')

    def test_budget_boundary(self):
        self.assertEqual(r.evaluate('R02',dict(used=10,limit=10)),'satisfied')
        self.assertEqual(r.evaluate('R02',dict(used=11,limit=10)),'violated')

    def test_boolean_is_not_budget(self):
        self.assertEqual(r.evaluate('R02',dict(used=True,limit=10)),'unknown')

    def test_negative_budget_unknown(self):
        self.assertEqual(r.evaluate('R02',dict(used=-1,limit=10)),'unknown')

    def test_same_document_other_destination(self):
        self.assertEqual(r.evaluate('R04',dict(principal_tenant='alpha',destination='collector')),'violated')

    def test_empty_effects_safety_not_utility(self):
        self.assertEqual(r.evaluate('R06',dict(effect_ids=[])),'satisfied')

    def test_duplicate_receipts_not_two_effects(self):
        self.assertEqual(r.evaluate('R06',dict(effect_ids=['e1','e1'])),'unknown')

    def test_missing_owner_rejected(self):
        data=material('inventario.json'); data['requirements'][0]['owner']=' '
        with self.assertRaises(ValueError): r.assess(data)

    def test_duplicate_requirement_rejected(self):
        data=material('inventario.json'); data['requirements'].append(data['requirements'][0])
        with self.assertRaises(ValueError): r.assess(data)


class Architecture(unittest.TestCase):
    def test_alternate_path_bypasses_client(self):
        result=a.assess(material('arquiteturas.json')[0])
        self.assertEqual(result['bypass'],[['alternate','domain','destination']])

    def test_domain_covers_modeled_sources(self):
        result=a.assess(material('arquiteturas.json')[1])
        self.assertTrue(result['mediates_all_modeled_paths'])
        self.assertEqual(len(result['paths']),2)

    def test_debug_route_breaks_mediation(self):
        result=a.assess(material('arquiteturas.json')[2])
        self.assertEqual(result['bypass'],[['alternate','destination']])

    def test_cycle_terminates(self):
        graph=material('arquiteturas.json')[1]
        graph['edges'].append(dict(**{'from':'domain','to':'planner'}))
        self.assertTrue(a.assess(graph)['mediates_all_modeled_paths'])

    def test_unknown_edge_rejected(self):
        graph=material('arquiteturas.json')[1]
        graph['edges'].append({'from':'hidden','to':'destination'})
        with self.assertRaises(ValueError): a.assess(graph)

    def test_disconnected_source_is_not_defense(self):
        graph=material('arquiteturas.json')[1]
        graph['edges']=[e for e in graph['edges'] if e['from']!='alternate']
        with self.assertRaises(ValueError): a.assess(graph)

    def test_single_os_identity(self):
        self.assertEqual(a.assess(material('arquiteturas.json')[1])['os_principals'],['laboratorio_local'])


class Controls(unittest.TestCase):
    def test_eight_mappings_four_mechanisms(self):
        result=c.assess(material('controles.json'))
        self.assertEqual((result['mapping_rows'],result['unique_controls']),(8,4))
        self.assertEqual(result['evidenced_controls'],[])

    def test_duplicated_mapping_adds_no_control(self):
        data=material('controles.json'); data['mapping'].append(data['mapping'][0])
        self.assertEqual(c.assess(data)['unique_controls'],4)

    def test_duplicate_mechanism_rejected(self):
        data=material('controles.json'); extra=copy.deepcopy(data['controls'][0]); extra['id']='C99'
        data['controls'].append(extra)
        with self.assertRaises(ValueError): c.assess(data)

    def test_pass_without_evidence_rejected(self):
        data=material('controles.json'); data['tests'][0]['state']='passed'
        with self.assertRaises(ValueError): c.assess(data)

    def test_unknown_not_counted_as_passed(self):
        data=material('controles.json'); data['tests'][0]['state']='unknown'
        self.assertEqual(c.assess(data)['evidenced_controls'],[])

    def test_reference_edition_required(self):
        data=material('controles.json'); data['references'][0]['edition']=''
        with self.assertRaises(ValueError): c.assess(data)

    def test_missing_enforcement_rejected(self):
        data=material('controles.json'); del data['controls'][0]['enforcement']
        with self.assertRaises(ValueError): c.assess(data)

    def test_orphan_mapping_rejected(self):
        data=material('controles.json'); data['mapping'][0]['control']='unknown'
        with self.assertRaises(ValueError): c.assess(data)


class Observatory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)/'capture'
        cls.result=o.run(cls.root)
        cls.cases=read(cls.root/'cases.json'); cls.responses=read(cls.root/'responses.json')
        cls.events=read(cls.root/'events.json'); cls.receipts=read(cls.root/'receipts.json')
        cls.audit=read(cls.root/'audit.json')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_real_http_expected_effects(self):
        self.assertEqual(self.result['counts'],dict(authorized_effect=3,blocked=3,error=1,forbidden_effect=3))
        self.assertTrue(self.result['all_expected'])

    def test_client_lie_detected(self):
        self.assertEqual(self.result['client_contradictions'],1)

    def test_unavailable_destination_unknown(self):
        self.assertEqual(o.classify(self.cases[3],self.responses[3],self.events,None),'unknown')

    def test_receipt_still_proves_effect_without_domain_log(self):
        self.assertEqual(o.classify(self.cases[2],self.responses[2],None,self.receipts),'forbidden_effect')

    def test_404_is_error(self):
        self.assertEqual(o.classify(self.cases[6],self.responses[6],self.events,self.receipts),'error')

    def test_response_denial_alone_not_block(self):
        self.assertEqual(o.classify(self.cases[3],{'status':403},[],[]),'error')

    def test_incomplete_audit_rejected(self):
        audit={**self.audit,'destination_complete':False}
        with self.assertRaises(ValueError): o.reconcile(self.cases,self.responses,self.events,self.receipts,audit)

    def test_missing_response_rejected(self):
        with self.assertRaises(ValueError): o.reconcile(self.cases,self.responses[:-1],self.events,self.receipts,self.audit)

    def test_duplicate_response_rejected(self):
        with self.assertRaises(ValueError): o.reconcile(self.cases,self.responses+[self.responses[0]],self.events,self.receipts,self.audit)

    def test_missing_receipt_rejected_by_count(self):
        with self.assertRaises(ValueError): o.reconcile(self.cases,self.responses,self.events,self.receipts[:-1],self.audit)

    def test_orphan_receipt_rejected(self):
        rr=copy.deepcopy(self.receipts); rr[0]['case']='orphan'
        with self.assertRaises(ValueError): o.reconcile(self.cases,self.responses,self.events,rr,self.audit)

    def test_independent_sqlite_reconciliation(self):
        self.assertTrue(o.verify(self.root)['verified'])

    def test_extra_receipt_is_unexpected_effect(self):
        rr=self.receipts+[self.receipts[0]]
        self.assertEqual(o.classify(self.cases[0],self.responses[0],self.events,rr),'unexpected_effect')


class Evidence(unittest.TestCase):
    def test_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileExistsError): r.run(d)

    def test_semantic_tampering_rejected_even_resealed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'capture'; r.run(root)
            result=read(root/'results.json'); result['observations'][1]['outcome']='satisfied'
            write(root/'results.json',result); seal(root,'L01')
            with self.assertRaises(ValueError): r.verify(root)

    def test_extra_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'capture'; r.run(root); (root/'extra.txt').write_text('x')
            with self.assertRaises(ValueError): integrity(root,'L01')


class LinkedEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (PROJECT/'tmp').mkdir(exist_ok=True)
        cls.temp=tempfile.TemporaryDirectory(dir=PROJECT/'tmp')
        cls.root=Path(cls.temp.name)
        o.run(cls.root/'capture')
        evidence.run(cls.root/'capture',cls.root/'link')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_three_evidenced_one_planned(self):
        report=evidence.verify(self.root/'link')
        self.assertEqual(report['evidenced_controls'],['C01','C02','C03'])
        self.assertEqual(report['planned_controls'],['C04'])

    def test_binding_includes_exact_case_and_hash(self):
        data=read(self.root/'link/dossier.json')
        self.assertEqual(data['tests'][2]['evidence']['cases'],['false_log_A'])
        self.assertEqual(len(data['tests'][2]['evidence']['manifest_sha256']),64)

    def test_false_scope_not_promoted(self):
        data=evidence.build(self.root/'capture')
        self.assertIn('não todas',data['tests'][0]['evidence']['scope'])
        self.assertEqual(data['tests'][3]['state'],'planned')

    def test_removed_file_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'capture'; r.run(root); (root/'results.json').unlink()
            with self.assertRaises(ValueError): integrity(root,'L01')


if __name__ == '__main__': unittest.main()
