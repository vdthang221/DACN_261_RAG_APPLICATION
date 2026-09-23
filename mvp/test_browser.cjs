/* Optional UI acceptance check. Install/use Playwright outside app dependencies. */
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.BASE_URL || 'http://127.0.0.1:8000';
const full = process.env.RUN_FULL_FLOW === '1';
const seed = JSON.parse(fs.readFileSync(path.join(__dirname, 'seed.json'), 'utf8'));
const output = path.join(__dirname, 'data', 'screenshots');
fs.mkdirSync(output, {recursive:true});

(async()=>{
  const browser=await chromium.launch({channel:process.env.BROWSER_CHANNEL||'msedge',headless:true});
  const errors=[];
  try {
    if(!process.env.BROWSER_STORAGE_STATE) {
      const page=await browser.newPage({viewport:{width:1440,height:1000}});
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base);
      await page.getByRole('heading',{name:'Bắt đầu từ một bài code.'}).waitFor();
      assert.equal(await page.locator('#student-code').count(),0);
      assert.equal((await page.request.get(base+'/api/problems')).status(),401);
      const settings=await (await page.request.get(base+'/api/config')).json();
      if(settings.google_configured)assert.equal(await page.getByRole('link',{name:'Đăng nhập bằng Google'}).getAttribute('href'),'/auth/google/start');
      else await page.getByText('Đăng nhập Google chưa sẵn sàng.',{exact:false}).waitFor();
      await page.screenshot({path:path.join(output,'google-login.png'),fullPage:true});
      await page.goto(base+'/?login_error=email_domain');
      await page.getByRole('alert').filter({hasText:'@hcmut.edu.vn'}).waitFor();
      assert.equal(new URL(page.url()).search,'');
      await page.setViewportSize({width:390,height:844});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
      await page.screenshot({path:path.join(output,'google-login-mobile.png'),fullPage:true});
      assert.deepEqual(errors,[]);
      console.log('Google login UI, anonymous access denial, error message and mobile layout passed. Live Google not exercised.');
      return;
    }
    async function student(index) {
      const state=process.env[`BROWSER_STORAGE_STATE_${index}`]||process.env.BROWSER_STORAGE_STATE;
      const context=await browser.newContext({viewport:{width:1440,height:1000},storageState:state});
      const page=await context.newPage();
      page.on('pageerror',error=>errors.push(error.message));
      await page.goto(base);
      await page.getByRole('heading',{name:'Danh sách bài tập'}).waitFor();
      if(index===1) {
        await page.screenshot({path:path.join(output,'library.png'),fullPage:true});
        await page.getByRole('searchbox').fill('không-có-bài');
        await page.getByText('Không tìm thấy bài phù hợp.',{exact:false}).waitFor();
        await page.getByRole('searchbox').fill('');
      }
      await page.getByRole('link',{name:seed[0].title,exact:true}).click();
      await page.getByRole('textbox',{name:'Mã nguồn C++17'}).fill(seed[0].solution);
      await page.reload();
      await page.getByRole('textbox',{name:'Mã nguồn C++17'}).waitFor();
      assert.equal(await page.getByRole('textbox',{name:'Mã nguồn C++17'}).inputValue(),seed[0].solution);
      if(index===1) {
        await page.screenshot({path:path.join(output,'editor.png'),fullPage:true});
        await page.setViewportSize({width:390,height:844});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile horizontal overflow');
        await page.screenshot({path:path.join(output,'mobile.png'),fullPage:true});
        await page.setViewportSize({width:1440,height:1000});
      }
      if(full) {
        await page.getByRole('button',{name:'Nộp & chấm bài'}).click();
        await page.getByRole('heading',{name:'Bài kiểm tra của bạn',exact:true}).waitFor({timeout:120000});
        assert.equal(await page.locator('input[type=radio]').count(),12);
        if(index===1)await page.screenshot({path:path.join(output,'mcq.png'),fullPage:true});
        for(let q=0;q<3;q++)await page.locator(`input[name=q${q}]`).nth(q).check();
        await page.getByRole('button',{name:'Nộp câu trả lời'}).click();
        await page.getByRole('heading',{name:'Đã hoàn thành bài luyện tập'}).waitFor({timeout:120000});
        if(index===1)await page.screenshot({path:path.join(output,'feedback.png'),fullPage:true});
        await page.reload();
        await page.getByRole('heading',{name:'Đã hoàn thành bài luyện tập'}).waitFor();
      }
      await page.getByRole('button',{name:'Kết quả của tôi',exact:true}).click();
      await page.getByRole('heading',{name:'Kết quả của tôi',exact:true}).waitFor();
      await page.getByRole('button',{name:'Ngân hàng XML',exact:true}).click();
      await page.getByRole('heading',{name:'Ngân hàng câu hỏi',exact:true}).waitFor();
      if(index===1&&process.env.ADMIN_TEST_TOKEN) {
        await page.getByLabel('Mã quản trị').fill(process.env.ADMIN_TEST_TOKEN);
        await page.getByLabel('Chọn file XML').setInputFiles(path.join(__dirname,'examples','moodle.xml'));
        await page.getByRole('button',{name:'Nhập ngân hàng'}).click();
        await page.getByText('MCQ trùng được bỏ qua',{exact:false}).waitFor();
        const downloadEvent=page.waitForEvent('download');
        await page.getByRole('button',{name:'XML bài toán',exact:false}).click();
        const download=await downloadEvent;
        assert.equal(download.suggestedFilename(),'problems.xml');
      }
      await context.close();
      return `SV0${index}: ${full?'C++ → MCQ → feedback → reload':'library/editor/mobile/dashboard/bank'} passed`;
    }
    const students=full&&process.env.BROWSER_STORAGE_STATE_2&&process.env.BROWSER_STORAGE_STATE_3?[1,2,3]:[1];
    const results=await Promise.all(students.map(student));
    assert.deepEqual(errors,[],'Browser runtime errors');
    console.log(results.join('\n'));
    console.log('No JS runtime errors. Screenshots: data/screenshots/');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
