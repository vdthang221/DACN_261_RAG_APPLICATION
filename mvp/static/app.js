'use strict';
const $ = (selector) => document.querySelector(selector);
const app = $('#app');
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let user, config, problems = [], history = [], topic = '', search = '', poll, routeVersion = 0;
const selections = new Map();
const labels = {judging:'Đang chấm C++',failed_tests:'Chưa pass testcase',judge_error:'Judge chưa sẵn sàng',generate_pending:'Đang xếp hàng MCQ',generating:'Đang sinh MCQ',mcq_ready:'Chờ làm MCQ',feedback_pending:'Đang xếp hàng feedback',feedback_running:'Đang viết feedback',completed:'Hoàn thành',llm_error:'Cần thử lại LLM'};
const active = ['judging','generate_pending','generating','feedback_pending','feedback_running'];
const skills = {S1:'Cấu trúc mã',S2:'Vai trò biến & hàm',S3:'Lần theo thực thi',S4:'Trừu tượng hóa',S5:'Logic & tác động',S6:'Dự đoán kết quả',S7:'Giải thích ý định',S8:'Mô phỏng',S9:'Cú pháp & ngữ nghĩa'};

async function api(url, data, adminToken) {
  const options = {headers:{}};
  if (data !== undefined) { options.method='POST'; options.headers['Content-Type']='application/json'; options.headers['X-Requested-With']='CodeLit'; options.body=JSON.stringify(data); }
  if (adminToken) options.headers['X-Admin-Token']=adminToken;
  const response = await fetch(url, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Không kết nối được server.');
  return result;
}
let toastTimer;
function toast(message) { $('#toast').textContent=message; $('#toast').classList.remove('hidden'); clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),6000); }
function go(path) { if(location.hash === '#'+path) route(); else location.hash=path; }
function flow(step=1) { return `<div class="flow">${['Viết code','Làm MCQ','Nhận feedback'].map((s,i)=>`<span class="${i+1===step?'current':''}"><b>${i+1}</b>${s}</span>${i<2?'<span>→</span>':''}`).join('')}</div>`; }
function tags(p) {return `<span class="badge ${p.difficulty==='Dễ'?'easy':'medium'}">${esc(p.difficulty)}</span> <span class="tag">${esc(p.topic)}</span> <span class="tag">${esc(p.bloom)}</span>`;}
function draftKey(p) {return `codelit:${user.id}:${p.id}`;}
function draft(p) {try{return localStorage.getItem(draftKey(p)) ?? p.starter;}catch{return p.starter;}}
function saveDraft(p,v) {try{localStorage.setItem(draftKey(p),v);}catch{}}
function header() {$('#identity').textContent=user ? user.email : ''; $('#identity').title=user ? user.email : ''; $('#logout').classList.toggle('hidden',!user); $('#provider').textContent=config?.mode==='demo'?'DEMO • Không gọi LLM':`${config?.model || 'Gemini'} • C++17`;}
async function refresh() {[problems,history]=await Promise.all([api('/api/problems'),api('/api/attempts')]);}
function login() {
  const messages={not_configured:'Đăng nhập Google chưa được cấu hình. Vui lòng liên hệ giảng viên.',invalid_callback:'Phiên đăng nhập không hợp lệ. Vui lòng thử lại.',invalid_state:'Phiên đăng nhập đã hết hạn hoặc đã được sử dụng. Vui lòng thử lại.',cancelled:'Bạn đã hủy đăng nhập. Có thể thử lại khi sẵn sàng.',token_exchange_failed:'Chưa kết nối được Google. Vui lòng thử lại.',invalid_identity:'Không xác minh được tài khoản Google. Vui lòng thử lại.',email_unverified:'Google chưa xác minh email này. Hãy dùng tài khoản trường.',email_domain:'Chỉ tài khoản Google của trường với email @hcmut.edu.vn được truy cập.',login_failed:'Đăng nhập chưa thành công. Vui lòng thử lại.'};
  const key=new URLSearchParams(location.search).get('login_error');
  const message=Object.hasOwn(messages,key)?messages[key]:'';
  if(location.search)window.history.replaceState(null,'',location.pathname+location.hash);
  app.innerHTML=`<section class="panel login"><p class="eyebrow">KHÔNG GIAN SINH VIÊN HCMUT</p><h1>Bắt đầu từ một bài code.</h1><p class="muted">Đăng nhập bằng tài khoản Google của trường có email <strong>@hcmut.edu.vn</strong>.</p>${message?`<p class="inline-error" role="alert">${esc(message)}</p>`:''}${config.google_configured?'<a class="google-signin" href="/auth/google/start">Đăng nhập bằng Google</a>':'<div class="note warning" role="status">Đăng nhập Google chưa sẵn sàng. Vui lòng liên hệ giảng viên để kích hoạt.</div>'}<p class="muted">Sau khi đăng nhập, bạn có thể xem và làm tất cả bài mẫu. Kết quả luyện tập được lưu riêng theo tài khoản.</p></section>`;
}
function library() {
  const completed = new Set(history.filter(a=>a.state==='completed').map(a=>a.problem_id));
  const pending = history.filter(a=>a.state==='mcq_ready').length;
  app.innerHTML=`<section class="intro"><div><p class="eyebrow">LUYỆN TẬP CÓ ĐỊNH HƯỚNG</p><h1>Code đúng. Hiểu điều mình viết.</h1><p>Chọn một bài toán và bắt đầu hành trình của bạn.</p></div>${flow()}</section>
  <section class="stats" aria-label="Tiến độ"><div class="stat"><div class="stat-icon">&lt;/&gt;</div><div><strong>${problems.length}</strong><small>Bài toán để khám phá</small></div></div><div class="stat"><div class="stat-icon">✓</div><div><strong>${completed.size}<span class="muted"> / ${problems.length}</span></strong><small>Bài đã hoàn thành</small></div></div><div class="stat"><div class="stat-icon">?</div><div><strong>${pending}</strong><small>Bộ MCQ đang chờ bạn</small></div></div></section>
  <section class="library"><aside class="topics" aria-label="Chủ đề"><h3>Chủ đề luyện tập</h3>${['',...new Set(problems.map(p=>p.topic))].map(t=>`<button class="topic ${topic===t?'active':''}" data-topic="${esc(t)}">${esc(t||'Tất cả bài tập')}<span>${problems.filter(p=>!t||p.topic===t).length}</span></button>`).join('')}</aside>
  <div><div class="panel"><div class="panel-head"><h2>Danh sách bài tập</h2><input id="search" class="search" type="search" aria-label="Tìm bài tập" placeholder="Tìm theo tên bài…" value="${esc(search)}"></div><div id="problem-list"></div></div><div class="note">Pass toàn bộ testcase mẫu để mở MCQ. Câu hỏi được sinh từ chính lời giải của bạn, theo kỹ năng và mức độ của từng bài.</div>${config.mode==='demo'?'<div class="note warning">Chế độ DEMO: MCQ và feedback là dữ liệu mô phỏng, không phải kết quả Gemini.</div>':!config.llm_configured?'<div class="note warning">Chưa cấu hình Gemini API key. Bạn vẫn có thể viết và nộp code; phần MCQ sẽ chờ cấu hình từ giảng viên.</div>':''}</div></section>`;
  document.querySelectorAll('[data-topic]').forEach(b=>b.onclick=()=>{topic=b.dataset.topic;library();});
  $('#search').oninput=e=>{search=e.target.value;rows(completed);}; rows(completed);
}
function rows(completed) {
  const filtered=problems.filter(p=>(!topic||p.topic===topic)&&p.title.toLocaleLowerCase('vi').includes(search.toLocaleLowerCase('vi')));
  $('#problem-list').innerHTML=filtered.length?filtered.map(p=>`<article class="problem-row"><span class="number ${completed.has(p.id)?'pass':''}">${completed.has(p.id)?'✓':String(problems.indexOf(p)+1).padStart(2,'0')}</span><div><a href="#problem/${esc(p.id)}" class="problem-title">${esc(p.title)}</a><div class="problem-meta"><span>${esc(p.topic)}</span><span>·</span><span>${p.tests.length} testcase</span><span class="tag">${esc(p.bloom)}</span></div></div><span class="badge ${p.difficulty==='Dễ'?'easy':'medium'}">${esc(p.difficulty)}</span><button data-problem="${esc(p.id)}" class="secondary">Làm bài ↗</button></article>`).join(''):'<div class="empty">Không tìm thấy bài phù hợp. Thử từ khóa hoặc chủ đề khác.</div>';
  document.querySelectorAll('[data-problem]').forEach(b=>b.onclick=()=>go('problem/'+b.dataset.problem));
}
function problemPage(p) {
  if(!p) throw new Error('Bài toán không tồn tại.');
  app.innerHTML=`<a href="#problems" class="back">← Danh sách bài tập</a><div class="workspace-head"><h1>${esc(p.title)}</h1>${flow(1)}</div><div class="workspace"><section class="description"><h3>Đề bài</h3><div>${tags(p)}</div><p class="prose">${esc(p.description)}</p><h3>Testcase mẫu <span class="muted">(${p.tests.length})</span></h3>${p.tests.map((t,i)=>`<div class="example"><div class="example-label">TEST ${i+1} · INPUT</div><pre>${esc(t.input)||'(rỗng)'}</pre><div class="example-label">OUTPUT</div><pre>${esc(t.expected)||'(rỗng)'}</pre></div>`).join('')}<p class="muted">Kỹ năng: ${p.skills.map(s=>esc(skills[s]||s)).join(' · ')}</p></section><section class="code-side" aria-label="Trình soạn thảo"><div class="editor-top"><span>main.cpp &nbsp; / &nbsp; C++17</span><button id="reset-code">Khôi phục code mẫu</button></div><textarea id="editor" class="editor" aria-label="Mã nguồn C++17" spellcheck="false" autocapitalize="off" autocomplete="off">${esc(draft(p))}</textarea><div class="editor-bottom"><span>2 giây/test · 512 MB<br>Bản nháp lưu trên thiết bị này</span><button id="submit-code" class="primary">▷ Nộp & chấm bài</button></div></section></div><div id="submit-message" role="status"></div>`;
  const editor=$('#editor');editor.oninput=()=>saveDraft(p,editor.value);
  editor.onkeydown=e=>{if(e.key==='Tab'){e.preventDefault();const start=editor.selectionStart,end=editor.selectionEnd;editor.setRangeText('    ',start,end,'end');saveDraft(p,editor.value);}};
  $('#reset-code').onclick=()=>{if(confirm('Thay bản nháp hiện tại bằng code khởi đầu?')){editor.value=p.starter;saveDraft(p,editor.value);}};
  let requestId=crypto.randomUUID(), submittedCode=null;
  $('#submit-code').onclick=async()=>{const b=$('#submit-code');b.disabled=true;if(submittedCode!==editor.value){requestId=crypto.randomUUID();submittedCode=editor.value;}try{const a=await api('/api/submissions',{problem_id:p.id,code:editor.value,request_id:requestId});go('attempt/'+a.id);}catch(e){$('#submit-message').innerHTML=`<p class="note error">${esc(e.message)}</p>`;}finally{b.disabled=false;}};
}
function judgeResults(a) {
  if(!a.judge) return '';
  const j=a.judge;
  return `<section class="test-results"><h3 class="${j.passed?'pass':'fail'}">${j.passed?'✓ Pass toàn bộ testcase':'Chưa đạt testcase'} <span class="muted">${j.tests.filter(t=>t.passed).length}/${a.problem.tests.length}</span></h3>${j.compile_error?`<pre class="note error prose">${esc(j.compile_error)}</pre>`:''}<div class="test-grid">${j.tests.map((t,i)=>`<div class="test-item"><strong class="${t.passed?'pass':'fail'}">${t.passed?'✓':'×'} Test ${i+1}</strong>${!t.passed?`<pre>Input: ${esc(t.input)}\nMong đợi: ${esc(t.expected)}\nThực tế: ${esc(t.actual)}\n${esc(t.error)}</pre>`:''}</div>`).join('')}</div></section>`;
}
function attemptPage(a) {
  const isQuiz=['mcq_ready','feedback_pending','feedback_running','completed'].includes(a.state)||(a.state==='llm_error'&&a.stage==='feedback');
  app.innerHTML=`<a class="back" href="#dashboard">← Kết quả của tôi</a><div class="workspace-head"><div><p class="eyebrow">${isQuiz?'KIỂM TRA MỨC ĐỘ HIỂU BÀI':'KẾT QUẢ NỘP CODE'}</p><h1>${esc(a.problem.title)}</h1></div>${flow(a.state==='completed'?3:isQuiz?2:1)}</div>${a.mode==='demo'?'<div class="note warning">DEMO — Câu hỏi/feedback mô phỏng, không phải Gemini.</div>':''}<div id="attempt-content"></div>`;
  const container=$('#attempt-content');
  if (isQuiz) {
    const answered=Array.isArray(a.answers);
    const chosen=answered?a.answers:(selections.get(a.id)||[-1,-1,-1]);selections.set(a.id,chosen);
    container.innerHTML=`${a.state==='completed'?`<div class="score-banner"><div class="score">${a.score}<small> / 3</small></div><div><h2>Đã hoàn thành bài luyện tập</h2><p>${esc(a.feedback.summary)}</p></div></div><div class="feedback-columns"><section class="panel"><h3>Điểm làm tốt</h3><ul>${a.feedback.strengths.map(s=>`<li>${esc(s)}</li>`).join('')}</ul></section><section class="panel"><h3>Gợi ý luyện tập tiếp</h3><ul>${a.feedback.improvements.map(s=>`<li>${esc(s)}</li>`).join('')}</ul></section></div>`:''}<div class="quiz-layout"><div>${a.questions.map((q,i)=>`<section class="panel quiz-card"><div class="question-count">CÂU ${i+1} / 3 <span class="tag">${esc(skills[q.skill]||q.skill)}</span><span class="tag">${esc(q.bloom)}</span></div><h3>${esc(q.question)}</h3>${q.options.map((v,n)=>`<label class="option ${answered&&n===q.answer?'correct':''} ${answered&&chosen[i]===n&&n!==q.answer?'wrong':''}"><input type="radio" name="q${i}" value="${n}" data-q="${i}" ${chosen[i]===n?'checked':''} ${answered?'disabled':''}><span><b>${String.fromCharCode(65+n)}.</b> ${esc(v)}${answered&&n===q.answer?' ✓':''}</span></label>`).join('')}${answered?`<div class="feedback">${esc(a.feedback?.per_question[i]||q.explanation)}</div>`:''}</section>`).join('')}</div><aside class="panel quiz-summary"><h3>${answered?'Đã lưu câu trả lời':'Bài kiểm tra của bạn'}</h3><p class="muted">3 câu hỏi, mỗi câu chọn một đáp án. Câu trả lời được khóa sau khi nộp.</p><div id="dots" class="question-dots"></div>${answered?`<h2>${a.score}/3 câu đúng</h2><p class="muted">${a.state==='completed'?'Feedback đã sẵn sàng.':'Gemini sẽ giải thích và gợi ý cách cải thiện.'}</p>`:'<button id="submit-answers" class="primary">Nộp câu trả lời →</button>'}<div id="quiz-error" class="inline-error" role="alert"></div><div class="note">✓ Code đã pass ${a.problem.tests.length}/${a.problem.tests.length} testcase mẫu.</div></aside></div>`;
    const dots=()=>{$('#dots').innerHTML=chosen.map((n,i)=>`<span class="dot ${n>=0?'done':''}">${i+1}</span>`).join('');};dots();
    document.querySelectorAll('[data-q]').forEach(input=>input.onchange=()=>{chosen[Number(input.dataset.q)]=Number(input.value);dots();});
    if(!answered) $('#submit-answers').onclick=async()=>{if(chosen.some(n=>n<0)){toast('Bạn cần trả lời đủ cả 3 câu.');return;}const b=$('#submit-answers');b.disabled=true;try{await api(`/api/attempts/${a.id}/answers`,{answers:chosen});await route();}catch(e){$('#quiz-error').textContent=e.message;b.disabled=false;}};
  } else {
    container.innerHTML=`<div class="panel"><div class="panel-head"><h3>${esc(labels[a.state]||a.state)}</h3><span class="muted">C++17</span></div><div class="description"><div>${tags(a.problem)}</div><details><summary class="muted">Xem mã nguồn đã nộp</summary><pre class="prose">${esc(a.code)}</pre></details></div></div>${judgeResults(a)}`;
    if(a.state==='failed_tests')container.innerHTML+=`<div class="actions"><button id="edit-attempt" class="primary">← Sửa lời giải</button></div>`;
    if($('#edit-attempt'))$('#edit-attempt').onclick=()=>{saveDraft(a.problem,a.code);go('problem/'+a.problem.id);};
  }
  if(active.includes(a.state)) container.insertAdjacentHTML('beforeend',`<div class="progress" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><div><strong>${esc(labels[a.state])}</strong><p>${esc(a.error||'Bạn có thể chuyển trang. Tiến trình được lưu và sẽ tự tiếp tục.')}${a.next_run>Date.now()/1000?` Lượt kế tiếp dự kiến: ${new Date(a.next_run*1000).toLocaleString('vi-VN')}.`:''}</p></div></div>`);
  if(['judge_error','llm_error'].includes(a.state)) {
    const retryTime=Math.max(a.retry_at||0,a.quota_reset_at||0);
    container.insertAdjacentHTML('beforeend',`<div class="note error" role="alert">${esc(a.error||'Tác vụ bị gián đoạn khi server khởi động lại. Hãy thử lại.')}${retryTime>Date.now()/1000?` Có thể thử lại sau: ${new Date(retryTime*1000).toLocaleString('vi-VN')}.`:''}<div class="actions"><button id="retry">Thử lại</button><a href="#problem/${esc(a.problem.id)}"><button>Sửa code</button></a></div></div>`);
    $('#retry').onclick=async()=>{const b=$('#retry');b.disabled=true;try{await api(`/api/attempts/${a.id}/retry`,{});route();}catch(e){toast(e.message);b.disabled=false;}};
  }
}
function dashboard() {
  const complete=history.filter(a=>a.state==='completed'), score=complete.reduce((sum,a)=>sum+(a.score||0),0);
  app.innerHTML=`<section class="intro"><div><p class="eyebrow">HÀNH TRÌNH CỦA ${esc(user.name || user.email)}</p><h1>Kết quả của tôi</h1><p>Tiếp tục bộ MCQ đang làm hoặc xem lại feedback.</p></div><button id="reload-history">↻ Làm mới</button></section><div class="stats"><div class="stat"><div><strong>${history.length}</strong><small>Lần nộp gần nhất (tối đa 100)</small></div></div><div class="stat"><div><strong>${complete.length}</strong><small>Lần luyện tập hoàn thành</small></div></div><div class="stat"><div><strong>${complete.length?Math.round(score/(complete.length*3)*100):0}%</strong><small>MCQ đúng trong bài hoàn thành</small></div></div></div><section class="panel table-wrap">${history.length?`<table class="history"><thead><tr><th>Bài toán</th><th>Thời gian</th><th>Trạng thái</th><th>MCQ</th><th></th></tr></thead><tbody>${history.map(a=>`<tr><td><strong>${esc(a.title)}</strong>${a.mode==='demo'?'<br><span class="tag">DEMO</span>':''}</td><td class="nowrap muted">${new Date(a.created*1000).toLocaleString('vi-VN')}</td><td><span class="badge ${a.state==='completed'?'easy':'medium'}">${esc(labels[a.state])}</span></td><td>${a.score===null?'—':a.score+'/3'}</td><td><button data-attempt="${a.id}">${a.state==='mcq_ready'?'Làm MCQ →':'Xem →'}</button></td></tr>`).join('')}</tbody></table>`:'<div class="empty">Bạn chưa nộp bài nào.<br><a href="#problems" class="pass">Chọn bài tập đầu tiên →</a></div>'}</section>`;
  $('#reload-history').onclick=()=>route();document.querySelectorAll('[data-attempt]').forEach(b=>b.onclick=()=>go('attempt/'+b.dataset.attempt));
}
function bankPage() {
  app.innerHTML=`<section class="intro"><div><p class="eyebrow">DÀNH CHO GIẢNG VIÊN</p><h1>Ngân hàng câu hỏi</h1><p>Nhập bài lập trình và trao đổi MCQ với Moodle qua XML.</p></div></section><div class="bank-layout"><section class="panel bank-card"><h2>Nhập ngân hàng</h2><label class="field">Mã quản trị<input id="admin-token" type="password" autocomplete="off" placeholder="ADMIN_TOKEN trên server"></label><div class="upload"><h3>Chọn file XML</h3><p class="muted">XML bài toán hoặc Moodle XML · Tối đa 500 KB</p><input id="xml-file" type="file" accept=".xml,text/xml,application/xml" aria-label="Chọn file XML"></div><button id="import-xml" class="primary">Nhập ngân hàng ↑</button><div id="bank-message" role="status"></div><p class="muted">Bài trùng ID sẽ được cập nhật. Lần nộp cũ giữ nguyên đề và testcase tại thời điểm nộp.</p></section><section class="panel bank-card"><h2>Xuất & định dạng</h2><p><strong>XML bài lập trình</strong><br>Chứa chủ đề, kỹ năng/mức độ, code khởi đầu, lời giải mẫu và testcase. Root: <code>problem-bank version="1"</code>.</p><p><strong>Moodle XML</strong><br>Hỗ trợ <code>multichoice</code>, 4 phương án, 1 đáp án đúng. Cần các tag <code>problem:id</code>, <code>skill:S3</code>, <code>bloom:APPLY</code> và phần giải thích.</p><div class="actions"><button id="export-problems">↓ XML bài toán</button><button id="export-mcqs">↓ Moodle MCQ</button></div><div class="note">Moodle MCQ được nhập vào ngân hàng để lưu trữ/xuất lại. Luồng sinh viên vẫn sinh MCQ mới từ code đã pass, theo đúng yêu cầu Sprint 2.</div><p class="muted">XML bài toán có lời giải: chỉ giảng viên được tải.</p><div id="bank-count" class="muted"></div></section></div>`;
  $('#import-xml').onclick=async()=>{const button=$('#import-xml'),file=$('#xml-file').files[0];if(!file){toast('Chọn một file XML trước.');return;}if(file.size>512000){toast('XML tối đa 500 KB.');return;}button.disabled=true;try{const r=await api('/api/admin/import',{xml:await file.text()},$('#admin-token').value);$('#bank-message').textContent=`Đã nhập ${r.count}/${r.received} ${r.kind==='problems'?'bài toán':'MCQ'} (MCQ trùng được bỏ qua).`;await refresh();}catch(e){$('#bank-message').textContent=e.message;}finally{button.disabled=false;}};
  const download=async(kind)=>{try{const response=await fetch(`/api/admin/export?kind=${kind}`,{headers:{'X-Admin-Token':$('#admin-token').value}});if(!response.ok){const data=await response.json();throw new Error(data.error);}const url=URL.createObjectURL(await response.blob());const a=document.createElement('a');a.href=url;a.download=kind+'.xml';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(e){toast(e.message);}};
  $('#export-problems').onclick=()=>download('problems');$('#export-mcqs').onclick=()=>download('mcqs');
}
async function route() {
  clearTimeout(poll);const version=++routeVersion;if(!user){login();return;}
  const [view,id]=(location.hash.slice(1)||'problems').split('/');
  document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view===view||(b.dataset.view==='problems'&&view==='problem')||(b.dataset.view==='dashboard'&&view==='attempt')));
  try {
    if(view==='attempt') {
      const a=await api('/api/attempts/'+encodeURIComponent(id));if(version!==routeVersion)return;attemptPage(a);
      if(active.includes(a.state)) poll=setTimeout(()=>{if(version===routeVersion)route();},1800);
    } else if(view==='problem') problemPage(problems.find(p=>p.id===id));
    else if(view==='bank') bankPage();
    else {await refresh();if(version!==routeVersion)return;view==='dashboard'?dashboard():library();}
  } catch(e) {if(version===routeVersion){app.innerHTML=`<div class="note error">${esc(e.message)} <a href="#problems">Quay về bài tập</a></div>`;toast(e.message);}}
}
document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>go(b.dataset.view));
$('#logout').onclick=async()=>{try{await api('/api/logout',{});user=null;problems=[];history=[];selections.clear();header();route();}catch(e){toast(e.message);}};
window.addEventListener('hashchange',route);
(async()=>{try{config=await api('/api/config');try{user=await api('/api/me');}catch{user=null;}header();if(user)await refresh();await route();}catch(e){app.innerHTML=`<div class="note error">${esc(e.message)}. Hãy tải lại trang khi server sẵn sàng.</div>`;}})();
