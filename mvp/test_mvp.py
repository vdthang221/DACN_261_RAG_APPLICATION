"""Controller-owned acceptance tests. No real Gemini usage in this suite."""
import concurrent.futures
import copy
from datetime import datetime
import http.cookiejar
import hashlib
import io
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
            'ADMIN_TOKEN':'test-only-admin', 'LLM_QUOTA_BUCKET':'test-google-project', 'LLM_RPM':'5',
            'LLM_INPUT_TPM':'250000', 'LLM_RPD':'20', 'LLM_RETRY_LIMIT':'3',
            'LLM_QUEUE_MAX':'20', 'LLM_QUEUE_TIMEOUT_SECONDS':'120'})
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

    def test_bounded_queue_rejects_new_job_with_structured_error(self):
        other=self.login(2)
        with patch.dict(os.environ,{'LLM_QUEUE_MAX':'1'}),patch.object(server.POOL,'submit'):
            self.submit(key='queue-first')
            status,error=self.request(other,'/api/submissions',{
                'problem_id':self.p['id'],'code':self.p['solution'],'request_id':'queue-second'})
        self.assertEqual(status,429)
        self.assertEqual(error['code'],'llm_queue_full')
        self.assertGreater(error['retry_at'],time.time())

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

    def test_three_users_share_one_gemini_bucket(self):
        clients=[self.client,self.login(2),self.login(3)]
        with patch.object(server,'run_judge',self.fake_judge):
            attempts=[self.wait_judge(self.submit(client,key=f'gemini-user-{index}'))
                      for index,client in enumerate(clients)]
        for attempt in attempts:
            attempt['mode']='gemini';server.save_attempt(attempt)
        response=llm.ProviderResponse(llm.demo_result(attempts[0]),100,50,150)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-not-real','LLM_QUOTA_BUCKET':'three-users'}), \
             patch.object(server,'call_gemini',return_value=response) as provider, \
             concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda attempt:server.process_llm(attempt,250000),attempts))
        states=[server.get_attempt(attempt['id'])['state'] for attempt in attempts]
        self.assertEqual(states.count('mcq_ready'),1)
        self.assertEqual(states.count('generate_pending'),2)
        self.assertEqual(provider.call_count,1)

    def test_quota_spacing_tpm_and_daily_budget(self):
        first=server.reserve_budget(1000,'job-1','generate',1,'call-1',100000)
        self.assertTrue(first.granted)
        delayed=server.reserve_budget(1000,'job-2','generate',1,'call-2',100001)
        self.assertFalse(delayed.granted);self.assertGreaterEqual(delayed.wait_until,100012)
        with patch.dict(os.environ,{'LLM_INPUT_TPM':'1200','LLM_QUOTA_BUCKET':'tpm-test'}):
            self.assertTrue(server.reserve_budget(1000,'tpm-1','generate',1,'tpm-call-1',200000).granted)
            limited=server.reserve_budget(1000,'tpm-2','generate',1,'tpm-call-2',200012)
            self.assertFalse(limited.granted);self.assertIn('input_tpm',limited.reason)
            with self.assertRaises(llm.ProviderError) as caught:
                server.reserve_budget(1201,'large','generate',1,'large-call',200020)
            self.assertEqual(caught.exception.code,'local_input_tpm')
        with patch.dict(os.environ,{'LLM_RPD':'1','LLM_RPM':'1000','LLM_QUOTA_BUCKET':'daily-test'}):
            self.assertTrue(server.reserve_budget(100,'daily-1','generate',1,'daily-call-1',300000).granted)
            with self.assertRaises(llm.ProviderError) as caught:
                server.reserve_budget(100,'daily-2','generate',1,'daily-call-2',300001)
            self.assertEqual(caught.exception.code,'local_daily_quota')
        with patch.dict(os.environ,{'LLM_RPD':'20','LLM_RPM':'1000','LLM_QUOTA_BUCKET':'daily-twenty'}):
            for index in range(20):
                self.assertTrue(server.reserve_budget(100,f'day20-{index}','generate',1,
                    f'day20-call-{index}',310000+index*.1).granted)
            with self.assertRaises(llm.ProviderError) as caught:
                server.reserve_budget(100,'day20-21','generate',1,'day20-call-21',310003)
            self.assertEqual(caught.exception.code,'local_daily_quota')

    def test_quota_queue_timeout_is_total_not_per_wait(self):
        with patch.object(server,'run_judge',self.fake_judge):
            attempt=self.wait_judge(self.submit())
        attempt['mode']='gemini';server.save_attempt(attempt)
        def wait_decision(tokens,job_id,stage,attempt_no,call_id,now):
            return server.QuotaDecision(False,call_id,wait_until=now+20,reason='rpm_spacing')
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-not-real','LLM_QUEUE_TIMEOUT_SECONDS':'30'}), \
             patch.object(server,'reserve_budget',side_effect=wait_decision):
            server.process_llm(attempt,100000)
            queued=server.get_attempt(attempt['id'])
            self.assertEqual(queued['state'],'generate_pending')
            server.process_llm(queued,100020)
        stopped=server.get_attempt(attempt['id'])
        self.assertEqual(stopped['state'],'llm_error')
        self.assertEqual(stopped['error_code'],'quota_wait_too_long')

    def test_three_workers_share_atomic_quota_and_sixth_request_waits(self):
        barrier=threading.Barrier(3)
        def reserve(index):
            barrier.wait()
            return server.reserve_budget(100,f'worker-{index}','generate',1,f'worker-call-{index}',500000)
        with patch.dict(os.environ,{'LLM_QUOTA_BUCKET':'workers-test','LLM_RPM':'5'}), \
             concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            decisions=list(pool.map(reserve,range(3)))
        self.assertEqual(sum(d.granted for d in decisions),1)
        self.assertTrue(all(d.granted or d.wait_until>=500012 for d in decisions))
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM llm_calls WHERE bucket='workers-test'").fetchone()[0],1)

        with patch.dict(os.environ,{'LLM_QUOTA_BUCKET':'rpm-test','LLM_RPM':'5'}):
            for index,offset in enumerate([0,12,24,36,48]):
                decision=server.reserve_budget(100,f'rpm-{index}','generate',1,f'rpm-call-{index}',600000+offset)
                self.assertTrue(decision.granted)
            sixth=server.reserve_budget(100,'rpm-5','generate',1,'rpm-call-5',600059)
            self.assertFalse(sixth.granted);self.assertGreaterEqual(sixth.wait_until,600060)

    def test_pacific_daily_reset_handles_dst_and_restart(self):
        start=datetime(2026,3,8,0,30,tzinfo=server.PACIFIC).timestamp()
        day,reset=server.quota_day_window(start)
        self.assertEqual(day,'2026-03-08')
        reset_local=datetime.fromtimestamp(reset,server.PACIFIC)
        self.assertEqual((reset_local.date().isoformat(),reset_local.hour,reset_local.minute),('2026-03-09',0,0))
        with patch.dict(os.environ,{'LLM_QUOTA_BUCKET':'dst-test','LLM_RPD':'1','LLM_RPM':'1000'}):
            self.assertTrue(server.reserve_budget(10,'dst-1','generate',1,'dst-call-1',start).granted)
            server.init_db()
            with self.assertRaises(llm.ProviderError) as caught:
                server.reserve_budget(10,'dst-2','generate',1,'dst-call-2',reset-1)
            self.assertEqual(caught.exception.code,'local_daily_quota')
            self.assertTrue(server.reserve_budget(10,'dst-3','generate',1,'dst-call-3',reset+.1).granted)

    def test_only_one_worker_claims_a_pending_job(self):
        with patch.object(server,'run_judge',self.fake_judge):
            pending=self.wait_judge(self.submit())
        barrier=threading.Barrier(3)
        def claim(_):
            barrier.wait()
            return server.claim_llm_job(700000)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            claimed=list(pool.map(claim,range(3)))
        winners=[a for a in claimed if a]
        self.assertEqual(len(winners),1);self.assertEqual(winners[0]['id'],pending['id'])
        self.assertEqual(server.get_attempt(pending['id'])['state'],'generating')

    def test_daily_quota_midway_never_completes_partial_task(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        a['mode']='gemini';server.save_attempt(a)
        generated=llm.demo_result(a)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-not-real','LLM_QUOTA_BUCKET':'midway-test',
             'LLM_RPD':'1','LLM_RPM':'1000'}),patch.object(server,'call_gemini',return_value=llm.ProviderResponse(generated,100,50,150)) as provider:
            server.process_llm(a,800000)
            ready=server.get_attempt(a['id']);self.assertEqual(ready['state'],'mcq_ready')
            answers=[q['answer'] for q in ready['questions']]
            self.assertEqual(self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':answers})[0],202)
            server.process_llm(server.get_attempt(a['id']),800001)
            stopped=server.get_attempt(a['id'])
        self.assertEqual(provider.call_count,1)
        self.assertEqual((stopped['state'],stopped['stage'],stopped['error_code']),('llm_error','feedback','local_daily_quota'))
        self.assertIn('answers',stopped);self.assertNotIn('feedback',stopped)

    def test_unknown_provider_outcome_is_counted_and_not_auto_retried(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        a['mode']='gemini';server.save_attempt(a)
        unknown=llm.ProviderError('unknown outcome',code='provider_outcome_unknown',request_sent=True)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-not-real','LLM_QUOTA_BUCKET':'timeout-test',
             'LLM_RPM':'1000'}),patch.object(server,'call_gemini',side_effect=unknown) as provider:
            server.process_llm(a,900000)
            failed=server.get_attempt(a['id'])
            server.init_db()
        self.assertEqual(provider.call_count,1);self.assertEqual(failed['state'],'llm_error')
        self.assertEqual(failed['error_code'],'provider_outcome_unknown')
        with server.connect() as db:
            row=db.execute("SELECT status FROM llm_calls WHERE job_id=?",(a['id'],)).fetchone()
            self.assertEqual(row['status'],'ambiguous')
        self.assertEqual(server.get_attempt(a['id'])['state'],'llm_error')

    def test_crash_after_send_becomes_ambiguous_instead_of_requeued(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        a['mode']='gemini';a['state']='generating';a['tries']=1;server.save_attempt(a)
        with patch.dict(os.environ,{'LLM_QUOTA_BUCKET':'restart-sent','LLM_RPM':'1000'}):
            decision=server.reserve_budget(100,a['id'],'generate',1,f"{a['id']}:generate:1",1000000)
            self.assertTrue(decision.granted)
            server.mark_call_sent(a,decision.call_id)
            server.init_db()
        restored=server.get_attempt(a['id'])
        self.assertEqual((restored['state'],restored['error_code']),('llm_error','provider_outcome_unknown'))

    def test_crash_before_send_requeues_reserved_call_without_reusing_it(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        a['mode']='gemini';a['state']='generating';server.save_attempt(a)
        with patch.dict(os.environ,{'LLM_QUOTA_BUCKET':'restart-reserved','LLM_RPM':'1000'}):
            call_id=f"{a['id']}:generate:1"
            self.assertTrue(server.reserve_budget(100,a['id'],'generate',1,call_id,1100000).granted)
            server.init_db()
        restored=server.get_attempt(a['id'])
        self.assertEqual(restored['state'],'generate_pending');self.assertEqual(restored['tries'],1)
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT status FROM llm_calls WHERE call_id=?",(call_id,)).fetchone()['status'],'abandoned')

    def test_provider_minute_429_retries_once_through_same_limiter(self):
        with patch.object(server,'run_judge',self.fake_judge):
            a=self.wait_judge(self.submit())
        a['mode']='gemini';server.save_attempt(a)
        generated=llm.demo_result(a)
        rate=llm.ProviderError('minute quota',True,20,code='provider_minute_quota',request_sent=True)
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test-not-real','LLM_QUOTA_BUCKET':'provider-429',
             'LLM_RPM':'5'}),patch.object(server,'call_gemini',side_effect=[rate,llm.ProviderResponse(generated,100,50,150)]) as provider, \
             patch.object(server.random,'uniform',return_value=0):
            server.process_llm(a,1200000)
            pending=server.get_attempt(a['id'])
            self.assertEqual(pending['state'],'generate_pending');self.assertEqual(pending['next_run'],1200020)
            self.assertIsNone(server.claim_llm_job(1200019))
            claimed=server.claim_llm_job(1200020.1);self.assertIsNotNone(claimed)
            server.process_llm(claimed,1200020.1)
        self.assertEqual(provider.call_count,2)
        self.assertEqual(server.get_attempt(a['id'])['state'],'mcq_ready')
        with server.connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM llm_calls WHERE job_id=?",(a['id'],)).fetchone()[0],2)

    def test_provider_429_classification_is_not_blind(self):
        daily_body=json.dumps({'error':{'details':[{'quotaId':'GenerateRequestsPerDay'}]}}).encode()
        daily=urllib.error.HTTPError('https://example',429,'quota',{},io.BytesIO(daily_body))
        classified=llm._http_error(daily)
        daily.close()
        self.assertEqual(classified.code,'provider_daily_quota');self.assertFalse(classified.retryable)
        unknown=urllib.error.HTTPError('https://example',429,'quota',{},io.BytesIO(b'{}'))
        classified=llm._http_error(unknown)
        unknown.close()
        self.assertEqual(classified.code,'provider_rate_limit_unknown');self.assertFalse(classified.retryable)
        minute=urllib.error.HTTPError('https://example',429,'quota',{'Retry-After':'20'},io.BytesIO(b'{}'))
        classified=llm._http_error(minute)
        minute.close()
        self.assertEqual(classified.code,'provider_minute_quota');self.assertTrue(classified.retryable)
        self.assertEqual(classified.retry_after,20)

    def test_llm_retry_bounded_and_bad_schema_rejected(self):
        with patch.object(server,'run_judge',self.fake_judge):a=self.wait_judge(self.submit())
        a['mode']='gemini'
        failure=llm.ProviderError('provider unavailable',True,0,code='provider_unavailable',request_sent=True)
        with patch.dict(os.environ,{'LLM_MODE':'gemini','GEMINI_API_KEY':'test-not-real','LLM_RPM':'1000',
             'LLM_QUOTA_BUCKET':'retry-test'}),patch.object(server,'call_gemini',side_effect=failure) as provider, \
             patch.object(server.random,'uniform',return_value=0):
            for index in range(3):
                server.process_llm(a,400000+index);a=server.get_attempt(a['id'])
            self.assertEqual(provider.call_count,3);self.assertEqual(a['state'],'llm_error')
            self.assertEqual(a['tries'],3);self.assertEqual(a['error_code'],'provider_unavailable')
        q=llm.demo_result(a);q['questions'][0]['skill']='S9'
        with self.assertRaises(ValueError):llm.validate_result(q,a)

    def test_restart_preserves_answers(self):
        a=self.ready()
        self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':[0,1,2]})
        a=server.get_attempt(a['id']);a['state']='feedback_running';server.save_attempt(a)
        server.init_db();restored=server.get_attempt(a['id'])
        self.assertEqual(restored['state'],'llm_error');self.assertEqual(restored['error_code'],'provider_outcome_unknown')
        self.assertEqual(restored['answers'],[0,1,2])

    def test_csrf_and_invalid_answer_types(self):
        a=self.ready()
        self.assertEqual(self.request(self.client,f"/api/attempts/{a['id']}/answers",{'answers':[True,0,0]})[0],400)
        req=urllib.request.Request(self.base+'/api/login',data=b'{"code":"sv01-demo"}',headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:self.client.open(req)
        self.assertEqual(caught.exception.code,403)
        caught.exception.close()


if __name__=='__main__':
    unittest.main(verbosity=2)
