"""Offline coverage, layout and artifact lineage checks; no paid requests."""
import contextlib
import copy
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image
import campaign as c
import workflow as w


def fixture(root, count=4):
    root.mkdir()
    source=root/'source.png'
    Image.new('RGB',(1200,1600),'#478f62').save(source)
    artwork={f'{a}x{b}':str(source) for a,b in c.SIZES}
    designs=[dict(id=f'{i+1:02}',name=f'Design {i+1}',short_name='Winter\nCabin',
                  artwork=artwork.copy(),front=str(source),detail=str(source)) for i in range(count)]
    copies={key:dict(headline='A blanket for home',subline='A closer look at the printed front.',alt='Printed blanket',claims=[]) for key in c.MODULES}
    copies['hero'].update(headline='Bring the\nseasons\nhome.',subline='Four prints.\nFour sizes.\nYour favorite spot.')
    copies['details'].update(labels=['Polyester flannel','Original printed design'])
    copies['lifestyle'].update(labels=['A little reading time','A layer for your bed'])
    copies['sizes'].update(footer='Every print is available in all four sizes.')
    copies['care'].update(headline='Simple care.\nEveryday\ncomfort.',labels=['Machine\nwashable','Follow the\ncare label'])
    copies['gift'].update(headline='A thoughtful\ngift for\ntheir home.',subline='Pick a print\nthey will love.')
    brief=dict(schema_version=2,profile='parent-seven',layout='legacy',name='Offline test',brand='Test',parent_key='offline',
        product_mode='finished',sizes=c.SIZES,style='Daylight',designs=designs,copy=copies,
        facts={},palette=dict(ink='#203D36',accent='#47746A',paper='#F7F9F8'),
        detail_design_id='01',size_design_id='01',
        scenes={key:dict(design_id='01',shown_size=[50,60],references=[str(source)],
                         prompt='Retain exact product print. Offline fixture only.') for key in c.SCENES})
    return brief


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.brief=fixture(self.root/'inputs')
        self.project=self.root/'project'
        self.silence=contextlib.redirect_stdout(io.StringIO())
        self.silence.__enter__()

    def tearDown(self):
        self.silence.__exit__(None,None,None)
        self.temp.cleanup()

    def prepare(self):
        path=self.root/'inputs/brief.json'; w.write(path,self.brief)
        c.prepare(path,self.project,restore_legacy_layout=self.brief.get('layout') in ('legacy','lean-v3'))
        raw=self.project/'generation/raw'; raw.mkdir(exist_ok=True)
        state={}
        for name in c.SCENES:
            path=raw/f'{name}.png'
            Image.new('RGB',(1600,1000),'#b5c9bd').save(path)
            state[name]={'status':'completed','sha256':w.digest(path)}
        w.write(self.project/'generation/generation-state.json',state)

    def test_complete_delivery_and_physical_size_scale(self):
        self.prepare()
        result=c.render(self.project)
        self.assertEqual(result['errors'],[])
        self.assertEqual(result['status'],'design_draft')
        manifest=w.read(self.project/'render-manifest.json')
        boxes=manifest['modules']['sizes']['geometry']['rectangles']
        for record in boxes:
            a,b=record['size']; x,y,width,height=record['box']
            self.assertAlmostEqual(width/a,height/b,delta=.04)
            self.assertEqual(y+height,495)
        c.package(self.project)
        with zipfile.ZipFile(self.project/'aplus-seven-design-draft.zip') as z:
            self.assertIsNone(z.testzip())
            self.assertEqual(len([f for f in z.namelist() if f.startswith('assets/')]),7)

    def test_internal_brand_is_not_rendered_or_sent_as_brand_instruction(self):
        self.brief['brand']='InternalBrandOnly123'
        self.prepare()
        jobs=(self.project/'generation/jobs.jsonl').read_text(encoding='utf-8')
        self.assertNotIn('InternalBrandOnly123',jobs)
        project=c.load(self.project)
        for module in ('hero','gift'):
            project['brief']['copy'][module].update(headline='Printed\nblankets',subline='Four prints.')
        for layout in ('legacy','lean-v3'):
            project['brief']['layout']=layout
            for module in ('hero','gift'):
                before,_=c.compose(self.project,project,module)
                project['brief']['brand']='AnotherInternalBrand'
                after,_=c.compose(self.project,project,module)
                self.assertEqual(before.tobytes(),after.tobytes())
        self.brief['copy']['hero']['headline']='InternalBrandOnly123 blankets'
        with self.assertRaisesRegex(ValueError,'brand names'):
            c.validate(self.brief,self.root)

    def test_six_and_ten_designs_are_not_truncated(self):
        self.prepare(); base=c.load(self.project)
        for count in (6,10):
            project=copy.deepcopy(base)
            design=project['brief']['designs'][0]
            project['brief']['designs']=[dict(design,id=f'{i+1:02}') for i in range(count)]
            image,geometry=c.compose(self.project,project,'designs')
            self.assertEqual(image.size,(970,600))
            self.assertEqual(len(set(geometry['design_ids'])),count)
            for cell in geometry['cells']:
                x,y,width,height=cell['image_box']
                self.assertLessEqual(x+width,970)
                self.assertLessEqual(y+height,600)

    def test_missing_size_duplicate_design_and_unconfirmed_fact(self):
        for mutation in ('size','duplicate','claim'):
            b=copy.deepcopy(self.brief)
            if mutation=='size': del b['designs'][0]['artwork']['30x40']
            elif mutation=='duplicate': b['designs'][1]['id']='01'
            else: b['copy']['care']['claims']=['never_fades']
            with self.assertRaises(ValueError): c.validate(b,self.root)

    def test_scene_and_final_changes_are_detected(self):
        self.prepare(); c.render(self.project)
        raw=self.project/'generation/raw/hero.png'
        Image.new('RGB',(1600,1000),'red').save(raw)
        state=w.read(self.project/'generation/generation-state.json')
        state['hero']['sha256']=w.digest(raw)
        w.write(self.project/'generation/generation-state.json',state)
        self.assertTrue(any('scene changed' in e for e in c.check(self.project)['errors']))
        c.render(self.project)
        Image.new('RGB',(970,600),'black').save(self.project/'assets/01-hero.png')
        self.assertTrue(c.check(self.project)['errors'])

    def test_source_tampering_and_text_overflow_stop(self):
        self.prepare(); project=c.load(self.project)
        project['brief']['copy']['hero']['headline']='A very long headline '*30
        with self.assertRaises(ValueError): c.compose(self.project,project,'hero')
        source=self.project/next(iter(project['sources'].values()))['file']
        source.write_bytes(b'changed')
        with self.assertRaises(ValueError): c.load(self.project)

    def test_wrong_scene_reference_and_missing_labels_fail_before_generation(self):
        b=copy.deepcopy(self.brief)
        b['copy']['lifestyle']['labels']=[]
        with self.assertRaises(ValueError): c.validate(b,self.root)
        b=copy.deepcopy(self.brief)
        other=self.root/'inputs/other.png'
        Image.new('RGB',(1200,1600),'red').save(other)
        b['scenes']['hero']['references']=[str(other)]
        with self.assertRaises(ValueError): c.validate(b,self.root)

    def test_lean_export_only_seven_and_review_required(self):
        self.brief['layout']='lean-v3'
        self.brief['copy']['hero'].update(headline='Printed\nFlannel\nBlankets',subline='Four sizes.')
        self.brief['copy']['care'].update(headline='Machine\nwashable.',subline='Follow the\ncare label.')
        self.brief['copy']['lifestyle']['labels']=['Reading time','Bed layer']
        self.prepare()
        result=c.render(self.project)
        self.assertFalse(result['errors'])
        self.assertFalse((self.project/'preview.html').exists())
        self.assertFalse((self.project/'english-copy.md').exists())
        delivery=self.root/'delivery'
        with self.assertRaises(ValueError): c.export(self.project,delivery)
        manifest=w.read(self.project/'render-manifest.json')
        w.write(self.project/'review.json',dict(project_fingerprint=manifest['fingerprint'],modules={
            k:dict(sha256=v['sha256'],identity=True,scale=True,text=True,claims=True,notes='Synthetic fixture review only')
            for k,v in manifest['modules'].items()}))
        c.export(self.project,delivery)
        self.assertEqual({p.name for p in delivery.iterdir()},set(c.FILES.values()))
        with self.assertRaises(ValueError): c.export(self.project,delivery)

    def test_reuse_preserves_result_but_rejects_changed_prompt(self):
        self.prepare()
        self.brief['scenes']['hero']['reuse_from']=str(self.project)
        path=self.root/'inputs/reuse.json'; w.write(path,self.brief)
        c.prepare(path,self.root/'revision',restore_legacy_layout=True)
        state=w.read(self.root/'revision/generation/generation-state.json')
        self.assertEqual(state['hero']['sha256'],w.digest(self.project/'generation/raw/hero.png'))
        self.brief['scenes']['hero']['prompt']='A changed request must not reuse'
        w.write(path,self.brief)
        with self.assertRaises(ValueError): c.prepare(path,self.root/'changed',restore_legacy_layout=True)

    def configure_custom(self):
        self.brief.update(product_mode='custom',layout='lean-v3',customization={
            'confirmed':True,'photo_counts':list(range(1,11)),
            'source':'Synthetic offline fixture; not product evidence.',
            'instruction_scope':'selection-only','workflow_verified':False,
            'example_disclosure':'Example photos shown.'})
        source=self.brief['designs'][0]
        self.brief['designs']=[dict(source,id=f'{n:02}',photo_count=n) for n in range(1,11)]
        self.brief['copy']['hero'].update(headline='Custom\nPhoto\nBlankets',subline='Your photos.')
        self.brief['copy']['details'].update(headline='Made with your photos.',
            labels=['Example photos shown.','Polyester flannel'],
            selection_labels=['Choose a layout','Pick your photos','Choose a size'])
        self.brief['copy']['lifestyle']['labels']=['Reading time','Bed layer']
        self.brief['copy']['care'].update(headline='Machine\nwashable.',subline='Follow the\ncare label.')
        self.brief['copy']['gift'].update(headline='A personal\ngift.',subline='Their memories.')

    def test_custom_mode_and_all_photo_counts_reach_generation_and_gallery(self):
        self.configure_custom(); self.prepare()
        child=w.read(self.project/'scene-brief.json')
        self.assertEqual(child['product_mode'],'custom')
        self.assertEqual(child['customization']['photo_counts'],list(range(1,11)))
        jobs=(self.project/'generation/jobs.jsonl').read_text(encoding='utf-8')
        self.assertIn('demonstration customer photos',jobs)
        self.assertNotIn('replace fixed artwork',jobs)
        result=c.render(self.project)
        self.assertEqual(result['errors'],[])
        self.assertTrue(any('customization UI not verified' in p for p in result['pending']))
        manifest=w.read(self.project/'render-manifest.json')
        self.assertEqual(manifest['modules']['designs']['geometry']['photo_counts'],list(range(1,11)))
        self.assertEqual(manifest['modules']['details']['geometry']['instruction_scope'],'selection-only')

    def test_custom_missing_evidence_counts_and_upload_ui_are_rejected(self):
        self.configure_custom()
        for mutation in ('confirmation','coverage','count','ui','disclosure'):
            b=copy.deepcopy(self.brief)
            if mutation=='confirmation': b['customization']['confirmed']=False
            elif mutation=='coverage': b['designs'].pop()
            elif mutation=='count': b['designs'][0]['photo_count']=11
            elif mutation=='ui': b['copy']['details']['selection_labels'][1]='Click Upload Now'
            else: b['customization']['example_disclosure']='Real customer orders'
            with self.assertRaises(ValueError): c.validate(b,self.root)

    def configure_visual(self):
        self.brief['layout']='visual-v4'
        custom=self.brief['product_mode']=='custom'
        self.brief['copy']['hero'].update(headline='Custom photo\nblankets.' if custom else 'Printed flannel\nblankets.',subline='Four sizes.')
        self.brief['copy']['details'].update(headline='Choose your layout.' if custom else 'The print,\nup close.',labels=['Printed front','Polyester flannel'])
        self.brief['copy']['designs'].update(headline='Choose your layout.' if custom else 'Find your favorite print.',subline='Four sizes for each.')
        self.brief['copy']['lifestyle'].update(headline='At home, your way.',labels=['Reading time','Bed layer'])
        self.brief['copy']['sizes']['headline']='Choose your size.'
        self.brief['copy']['care'].update(headline='Machine\nwashable.',subline='Follow the care label.')
        self.brief['copy']['gift'].update(headline='A gift for\ntheir home.',subline='Choose a favorite print.')

    def test_visual_is_default_and_old_layout_needs_explicit_restore(self):
        path=self.root/'inputs/brief.json'; w.write(path,self.brief)
        with self.assertRaisesRegex(ValueError,'visual-v4'):
            c.prepare(path,self.project)
        self.configure_visual(); del self.brief['layout']
        self.prepare()
        project=c.load(self.project)
        self.assertEqual(project['brief']['layout'],'visual-v4')
        self.assertIn('continuous full photographic scene',project['brief']['scenes']['hero']['prompt'])
        self.assertFalse(c.render(self.project)['errors'])

    def test_visual_finished_and_custom_cover_every_count_and_no_sidebar(self):
        self.configure_visual(); self.prepare(); base=c.load(self.project)
        for custom in (False,True):
            for count in range(1,11):
                project=copy.deepcopy(base); b=project['brief']; design=b['designs'][0]
                b['designs']=[dict(design,id=f'{i+1:02}',photo_count=i+1) for i in range(count)]
                if custom:
                    b['product_mode']='custom'
                    b['customization']={'example_disclosure':'Example photos shown.'}
                image,geo=c.compose(self.project,project,'designs')
                self.assertEqual(image.size,(970,600))
                self.assertEqual(geo['design_ids'],[d['id'] for d in b['designs']])
                for cell in geo['cells']:
                    x,y,width,height=cell['image_box']
                    self.assertTrue(0<=x<x+width<=970 and 0<=y<y+height<=600)
                if custom:
                    self.assertEqual(geo['photo_counts'],list(range(1,count+1)))
        for module in ('hero','care','gift'):
            image,geo=c.compose(self.project,base,module)
            self.assertEqual(image.getpixel((10,590)),(181,201,189))
            self.assertTrue(geo['full_bleed'])

    def test_visual_preflight_rejects_bad_copy_crop_and_evidence_before_generation(self):
        self.configure_visual()
        for change in ('copy','crop','evidence','region'):
            b=copy.deepcopy(self.brief)
            if change=='copy': b['copy']['hero']['headline']='unreadable text '*30
            elif change=='crop': b['detail_crop']=[.8,.5,.2,1]
            elif change=='evidence': b['detail_photo']={'path':b['designs'][0]['front'],'confirmed':False}
            else: b['text_layout']={'hero':{'box':[950,0,200,200]}}
            with self.assertRaises(ValueError): c.validate(b,self.root)

    def test_visual_custom_complete_and_duplicate_layout_labels(self):
        self.configure_custom(); self.configure_visual(); self.prepare()
        self.assertFalse(c.render(self.project)['errors'])
        project=c.load(self.project)
        project['brief']['designs'][1]['photo_count']=1
        _,geo=c.compose(self.project,project,'designs')
        labels=[b['text'] for b in geo['text_boxes']]
        self.assertIn('Layout A',labels); self.assertIn('Layout B',labels)
        self.assertIn('Example photos shown.',labels)

    def test_visual_export_review_and_renderer_lineage(self):
        self.configure_visual(); self.prepare(); self.assertFalse(c.render(self.project)['errors'])
        with self.assertRaises(ValueError): c.export(self.project,self.root/'unchecked')
        manifest=w.read(self.project/'render-manifest.json')
        self.assertEqual(manifest['visual_renderer_sha256'],w.digest(Path(c.visual.__file__)))
        w.write(self.project/'review.json',dict(project_fingerprint=manifest['fingerprint'],modules={
            k:dict(sha256=v['sha256'],identity=True,scale=True,text=True,claims=True,notes='Synthetic fixture only')
            for k,v in manifest['modules'].items()}))
        c.export(self.project,self.root/'delivery')
        self.assertEqual(len(list((self.root/'delivery').glob('*.png'))),7)
        manifest['visual_renderer_sha256']='changed'
        w.write(self.project/'render-manifest.json',manifest)
        self.assertIn('Visual renderer changed; render and review again',c.check(self.project)['errors'])

    def test_visual_reuse_is_idempotent_and_text_region_changes_reject_reuse(self):
        self.configure_visual(); self.prepare()
        b=copy.deepcopy(c.load(self.project)['brief'])
        b['scenes']['hero']['reuse_from']=str(self.project)
        path=self.root/'inputs/reuse-v4.json'; w.write(path,b)
        c.prepare(path,self.root/'reused-v4')
        result=c.load(self.root/'reused-v4')
        self.assertEqual(result['brief']['scenes']['hero']['prompt'],b['scenes']['hero']['prompt'])
        b['text_layout']={'hero':{'box':[90,25,345,170]}}
        w.write(path,b)
        with self.assertRaisesRegex(ValueError,'changed prompt'):
            c.prepare(path,self.root/'changed-region')


if __name__=='__main__':
    unittest.main()
