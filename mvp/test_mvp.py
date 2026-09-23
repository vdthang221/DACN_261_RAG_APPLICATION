"""Controller-owned acceptance tests. No real Gemini usage in this suite."""
import concurrent.futures
import copy
import http.cookiejar
import hashlib
import secrets
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlparse, parse_qs, urlencode
from unittest.mock import patch

import bank
import llm
import server
import google_login


class MVPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        cls.base = 'http://127.0.0.1:' + str(cls.http.server_address[1])
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'DATABASE_PATH':str(Path(self.tmp.name)/'test.db'), 'LLM_MODE':'demo',
            'ADMIN_TOKEN':'test-only-admin', 'LLM_RPM':'4', 'LLM_INPUT_TPM':'20000', 'LLM_RPD':'100'})
        self.env.start()
        server.init_db()
        self.p = next(iter(server.all_problems().values()))
        self.client = self.login(1)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def request(self, client, path, data=None, admin=False):
        headers = {'Content-Type':'application/json', 'X-Requested-With':'CodeLit'}
        if admin:
            headers['X-Admin-Token']='test-only-admin'
        request = urllib.request.Request(self.base+path, data=None if data is None else json.dumps(data).encode(), headers=headers)
        try:
            with client.open(request, timeout=5) as response:
                raw=response.read()
                return response.status, json.loads(raw) if response.headers.get_content_type()=='application/json' else raw.decode()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def login(self, index):
        # Business tests inject a session only in their private temporary DB.
        # Google protocol and identity verification have separate auth tests.
        token=secrets.token_urlsafe(32)
        uid=f'google:test-student-{index}'
        with server.connect() as db:
            db.execute('INSERT OR REPLACE INTO students VALUES (?,?,?)',(uid,f'student{index}@hcmut.edu.vn',f'Student {index}'))
            db.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),uid,time.time()+3600))
        jar=http.cookiejar.CookieJar()
        jar.set_cookie(http.cookiejar.Cookie(version=0,name='session',value=token,port=None,port_specified=False,
            domain='127.0.0.1',domain_specified=False,domain_initial_dot=False,path='/',path_specified=True,
            secure=False,expires=None,discard=True,comment=None,comment_url=None,rest={'HttpOnly':None},rfc2109=False))
        client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        self.assertEqual(self.request(client,'/api/me')[1]['id'],uid)
        return client

    def test_all_school_students_see_all_problems(self):
        for client in [self.client,self.login(4)]:
            status,problems=self.request(client,'/api/problems')
            self.assertEqual(status,200)
            self.assertEqual({p['id'] for p in problems},set(server.all_problems()))
            self.assertTrue(all('solution' not in p for p in problems))
        anonymous=urllib.request.build_opener()
        self.assertEqual(self.request(anonymous,'/api/problems')[0],401)
        self.assertEqual(self.request(anonymous,'/api/login',{'code':'sv01-demo'})[0],404)

    def test_logout_revokes_school_session(self):
        self.assertEqual(self.request(self.client,'/api/logout',{})[0],200)
        self.assertEqual(self.request(self.client,'/api/me')[0],401)

    def test_google_http_callback_headers_and_profile(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                return None
        jar=http.cookiejar.CookieJar()
        browser=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPCookieProcessor(jar))
        def redirect(path):
            try:
                return browser.open(self.base+path)
            except urllib.error.HTTPError as response:
                self.assertEqual(response.code,302)
                return response
        with patch.dict(os.environ,{'GOOGLE_CLIENT_ID':'test-client','GOOGLE_CLIENT_SECRET':'test-secret',
            'GOOGLE_REDIRECT_URI':self.base+'/auth/google/callback','COOKIE_SECURE':'0'}):
            with redirect('/auth/google/start') as response:
                query=parse_qs(urlparse(response.headers['Location']).query)
            claims={'iss':'https://accounts.google.com','aud':'test-client','exp':time.time()+600,
                    'iat':time.time(),'sub':'callback-student','nonce':query['nonce'][0],
                    'email':'callback@hcmut.edu.vn','email_verified':True,'hd':'hcmut.edu.vn','name':'Callback Student'}
            callback='/auth/google/callback?'+urlencode({'state':query['state'][0],'code':'test-code'})
            with patch.object(google_login,'_post_form',return_value={'id_token':'test-token'}), \
                 patch.object(google_login.id_token,'verify_oauth2_token',return_value=claims):
                with redirect(callback) as response:
                    self.assertEqual(response.headers['Location'],'/#problems')
                    cookies=response.headers.get_all('Set-Cookie')
                    self.assertEqual(len(cookies),2)
                    self.assertTrue(any('google_login=;' in c and 'Path=/auth/google' in c for c in cookies))
                self.assertEqual(self.request(browser,'/api/me')[1]['id'],'google:callback-student')
                with redirect(callback) as response:
                    self.assertEqual(response.headers['Location'],'/?login_error=invalid_callback')

    def submit(self, client=None, key='request-123', code=None):
        client=client or self.client
        status,a=self.request(client,'/api/submissions',{'problem_id':self.p['id'],'code':code or self.p['solution'],'request_id':key})
        self.assertIn(status,[200,202],a)
        return a

    def fake_judge(self, code, tests):
        passed = code != 'wrong'
        return {'passed':passed,'compile_error':'','tests':[dict(t,actual=t['expected'] if passed else 'wrong',passed=passed,error='') for t in tests]}

    def wait_judge(self, a):
        for _ in range(100):
            current=server.get_attempt(a['id'])
            if current['state']!='judging':return current
            time.sleep(.01)
        self.fail('Judge did not finish')

    def ready(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        self.assertEqual(a['state'],'generate_pending')
        server.process_llm(a)
        return server.get_attempt(a['id'])

    def test_seed_xml_round_trip(self):
        problems=server.all_problems()
        kind,records=bank.parse_xml(bank.problem_xml(problems.values()),problems)
        self.assertEqual(kind,'problems')
        self.assertEqual(records,list(problems.values()))
        for p in records:bank.validate_problem(p)

    def test_moodle_round_trip_and_reject_invalid(self):
        a=self.ready()
        q=[dict(q,problem_id=self.p['id']) for q in a['questions']]
        xml=bank.moodle_xml(q)
        kind,records=bank.parse_xml(xml,server.all_problems())
        self.assertEqual(kind,'mcqs');self.assertEqual(records,q)
        for invalid in [xml.replace('fraction="100"','fraction="50"'),xml.replace('problem:sum-array','problem:missing'),xml.replace('<single>true','<single>false')]:
            with self.assertRaises(ValueError):bank.parse_xml(invalid,server.all_problems())

    def test_xml_rejects_entities_and_atomic_import(self):
        with self.assertRaises(ValueError):bank.parse_xml('<!DOCTYPE x [<!ENTITY x "bad">]><quiz/>',{})
        p=copy.deepcopy(self.p);p['id']='new-problem'
        xml=bank.problem_xml([p,self.p]).replace('<bloom>APPLY</bloom>','<bloom>INVALID</bloom>',1)
        status,_=self.request(self.client,'/api/admin/import',{'xml':xml},admin=True)
        self.assertEqual(status,400);self.assertNotIn('new-problem',server.all_problems())

    def test_failed_tests_never_unlock_mcq(self):
        with patch.object(server,'run_judge',self.fake_judge):a=self.wait_judge(self.submit(code='wrong'))
        self.assertEqual(a['state'],'failed_tests');self.assertNotIn('questions',a)
        self.assertEqual(self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':[0,0,0]})[0],409)

    def test_judge_failure_never_passes(self):
        with patch.object(server,'run_judge',side_effect=RuntimeError('Docker offline')):a=self.wait_judge(self.submit())
        self.assertEqual(a['state'],'judge_error');self.assertNotIn('questions',a)

    def test_end_to_end_answer_lock_feedback_and_bank(self):
        a=self.ready()
        status,public=self.request(self.client,'/api/attempts/'+a['id'])
        self.assertEqual(status,200);self.assertNotIn('solution',public['problem'])
        self.assertTrue(all('answer' not in q and 'explanation' not in q for q in public['questions']))
        answers=[q['answer'] for q in a['questions']]
        url=f"/api/attempts/{a['id']}/answers"
        status,submitted=self.request(self.client,url,{'answers':answers})
        self.assertEqual(status,202);self.assertEqual(submitted['score'],3)
        self.assertEqual(self.request(self.client,url,{'answers':answers})[0],200)
        changed=answers.copy();changed[0]=(changed[0]+1)%4
        self.assertEqual(self.request(self.client,url,{'answers':changed})[0],409)
        server.process_llm(server.get_attempt(a['id']))
        done=server.get_attempt(a['id']);self.assertEqual(done['state'],'completed')
        self.assertEqual(len(done['feedback']['per_question']),3)
        status,counts=self.request(self.client,'/api/admin/bank',admin=True)
        self.assertEqual(status,200);self.assertEqual(counts['mcqs'],3)

    def test_session_isolation_and_admin_protection(self):
        a=self.ready();other=self.login(2)
        self.assertEqual(self.request(other,'/api/attempts/'+a['id'])[0],404)
        self.assertEqual(self.request(other,f"/api/attempts/{a['id']}/answers",{'answers':[0,0,0]})[0],404)
        self.assertEqual(self.request(other,'/api/attempts')[1],[])
        self.assertEqual(self.request(other,'/api/admin/export')[0],403)

    def test_idempotent_submission_and_immutable_problem(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit());again=self.submit()
        self.assertEqual(a['id'],again['id'])
        self.assertEqual(self.request(self.client,'/api/submissions',{'problem_id':self.p['id'],'code':'other','request_id':'request-123'})[0],409)
        p=copy.deepcopy(self.p);p['title']='Updated title'
        self.request(self.client,'/api/admin/import',{'xml':bank.problem_xml([p])},admin=True)
        self.assertEqual(server.get_attempt(a['id'])['problem']['title'],self.p['title'])

    def test_three_students_concurrent(self):
        clients=[self.client,self.login(2),self.login(3)]
        with patch.object(server,'run_judge',self.fake_judge),concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            results=list(pool.map(lambda pair:self.wait_judge(self.submit(pair[1],key=f'concurrent-{pair[0]}')),enumerate(clients)))
        self.assertEqual(len({a['id'] for a in results}),3)
        for client,a in zip(clients,results):
            server.process_llm(a)
            a=server.get_attempt(a['id'])
            self.assertEqual(a['state'],'mcq_ready')
            self.request(client,f"/api/attempts/{a['id']}/answers",{'answers':[q['answer'] for q in a['questions']]})
            server.process_llm(server.get_attempt(a['id']))
            self.assertEqual(server.get_attempt(a['id'])['state'],'completed')

    def test_quota_spacing_tpm_and_daily_budget(self):
        self.assertEqual(server.reserve_budget(1000,100000),0)
        self.assertGreaterEqual(server.reserve_budget(1000,100001),100015)
        with patch.dict(os.environ,{'LLM_INPUT_TPM':'1200'}):
            self.assertGreaterEqual(server.reserve_budget(1000,100016),100061)
            with self.assertRaises(llm.ProviderError):server.reserve_budget(1201,100016)
        with patch.dict(os.environ,{'LLM_RPD':'1'}):
            self.assertGreaterEqual(server.reserve_budget(100,100100),186401)

    def test_llm_retry_bounded_and_bad_schema_rejected(self):
        with patch.object(server,'run_judge',self.fake_judge):a=self.wait_judge(self.submit())
        a['mode']='gemini'
        with patch.dict(os.environ,{'LLM_MODE':'gemini','GEMINI_API_KEY':'test-not-real'}),patch.object(server,'reserve_budget',return_value=0),patch.object(server,'call_gemini',side_effect=llm.ProviderError('429',True,20)) as provider:
            for index in range(3):
                server.process_llm(a);a=server.get_attempt(a['id'])
            self.assertEqual(provider.call_count,3);self.assertEqual(a['state'],'llm_error')
        q=llm.demo_result(a);q['questions'][0]['skill']='S9'
        with self.assertRaises(ValueError):llm.validate_result(q,a)

    def test_restart_preserves_answers(self):
        a=self.ready()
        self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':[0,1,2]})
        a=server.get_attempt(a['id']);a['state']='feedback_running';server.save_attempt(a)
        server.init_db();restored=server.get_attempt(a['id'])
        self.assertEqual(restored['state'],'feedback_pending');self.assertEqual(restored['answers'],[0,1,2])

    def test_csrf_and_invalid_answer_types(self):
        a=self.ready()
        self.assertEqual(self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':[True,0,0]})[0],400)
        req=urllib.request.Request(self.base+'/api/login',data=b'{"code":"sv01-demo"}',headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:self.client.open(req)
        self.assertEqual(caught.exception.code,403)
        caught.exception.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
