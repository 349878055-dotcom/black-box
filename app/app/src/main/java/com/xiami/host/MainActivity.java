package com.xiami.host;

import java.io.InputStream;

import android.app.Activity;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Message;
import android.net.Uri;
import android.provider.MediaStore;
import android.util.Base64;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputMethodManager;
import android.net.http.SslError;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.SslErrorHandler;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;

import org.json.JSONArray;
import org.json.JSONObject;

/**
 * 虾米 · 手机宿主 App（ChatGPT 式界面 + 内置浏览器）。
 *
 * uiWeb      主界面（assets/ui.html）：左侧栏 + 聊天窗口；云端 cmd 经 JS Bridge 交原生执行。
 * browser    内置浏览器：原生地址栏（返回聊天 / 网址输入 / 前往）+ browserWeb（真实网页执行）。
 */
public class MainActivity extends Activity {
    private static final String TAG = "XiamiHost";

    WebView uiWeb;
    WebView browserWeb;
    LinearLayout browserContainer;   // 地址栏 + browserWeb
    EditText addrEdit;
    Handler h = new Handler(Looper.getMainLooper());
    private ValueCallback<Uri[]> uploadCallback = null;  // 网页文件上传回调
    private static final int FILE_CHOOSER_REQUEST = 1001;
    private static final int CHAT_FILE_REQUEST = 1002;   // 聊天窗口选文件上传
    private static final int PHOTO_REQUEST = 1003;       // 聊天窗口拍照上传
    private Uri photoUri = null;                          // 拍照输出 Uri

    // ── 手机端通用登录交互（方案②：登录在聊天里推送输入框/图形码，同步等用户输入）──
    // loginLatch 阻塞 LoginCoordinator.run()（子线程），用户输入后 release 返回
    private java.util.concurrent.CountDownLatch loginLatch = null;
    private String loginResult = null;

    /** 手机端全权登录的交互宿主：在聊天里推问题/图，同步等用户输入（LoginCoordinator 调）。 */
    private final LoginCoordinator.Interactor loginInteractor = new LoginCoordinator.Interactor() {
        @Override
        public String askText(String title) {
            return requestLoginInput(title, null);
        }
        @Override
        public String showImageAndAsk(String base64, String title) {
            return requestLoginInput(title, base64);
        }
    };

    /** 在聊天里推登录问题（可选验证码图），阻塞等用户输入，返回输入（用户取消→null）。 */
    private String requestLoginInput(final String question, final String image) {
        final java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(1);
        runOnUiThread(() -> {
            loginLatch = latch;
            loginResult = null;
            String js = "if(window.__askLogin) window.__askLogin("
                    + JSONObject.quote(question == null ? "" : question) + ","
                    + JSONObject.quote(image == null ? "" : image) + ");";
            try { uiWeb.evaluateJavascript(js, null); } catch (Exception ignore) {}
        });
        try {
            if (!latch.await(120, java.util.concurrent.TimeUnit.SECONDS)) return null;
        } catch (InterruptedException e) {
            return null;
        }
        return loginResult;
    }

    /** ui.html 登录输入回传：用户输入后释放 latch（JsBridge.loginInput 调用）。 */
    void onLoginInput(String value) {
        loginResult = value == null ? "" : value;
        if (loginLatch != null) loginLatch.countDown();
    }

    // navigate / refresh 等真加载：挂一次性回调，onPageFinished 后再回执
    private String pendingNavCbId = null;
    private Runnable navTimeoutRunnable = null;
    private static final long NAV_DEFAULT_TIMEOUT_MS = 45000;
    // 浏览器默认 UA（navigate 切微信 UA 后据此恢复；glyy 老站需微信 UA）
    private String webViewDefaultUA = "";

    // ── 浏览器执行 JS（真实 DOM）──
    static final String READ_JS = """
        (function(){
          var body = document.body ? document.body.innerText : '';
          var els = [];
          var forms = [];
          var labels = [];
          var labs = document.querySelectorAll('label,[class*="label"],[class*="Label"],[class*="title"],[class*="Title"],[class*="placeholder"]');
          for (var i=0;i<labs.length && i<300;i++){
            var lt = (labs[i].innerText||labs[i].getAttribute('placeholder')||'').trim();
            if (lt && lt.length < 80) labels.push(lt.slice(0,80));
          }
          var nodes = document.querySelectorAll('input,textarea,select,button,a,[role="button"],[onclick],[contenteditable="true"]');
          for (var i=0;i<nodes.length && i<800;i++){
            var e = nodes[i];
            var isEditable = e.getAttribute('contenteditable')==='true';
            // 对齐电脑端：不按可见性过滤（之前只收可见 → 不可见 a 链接丢失，点不到/取不到 href）
            var t = (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim();
            var tag = e.tagName.toLowerCase();
            var r = e.getBoundingClientRect();
            if (tag==='input'||tag==='textarea'||tag==='select'||isEditable){
              forms.push({tag:isEditable?'contenteditable':tag,type:e.getAttribute('type')||tag,placeholder:(e.getAttribute('placeholder')||'').slice(0,60),value:(e.value||e.innerText||'').slice(0,50),label:(e.getAttribute('aria-label')||'').slice(0,60),x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),visible:(r.width>0&&r.height>0)});
            } else if (t){
              // 携带 href/alt/target（对齐电脑端 interactives 结构：tag/text/alt/href/target）
              var href = '';
              try { if (e.href) href = e.href; } catch (err) {}
              var alt = '';
              var img = e.querySelector ? e.querySelector('img') : null;
              if (img) alt = (img.alt||'').trim();
              els.push({tag:tag,text:t.slice(0,80),alt:alt.slice(0,80),href:href.slice(0,200),target:e.getAttribute('target')||'',x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),visible:(r.width>0&&r.height>0)});
            }
          }
          return {page_text:(body||'').slice(0,100000), interactives: els, forms: forms, labels: labels, readyState: document.readyState, url: location.href, forms_count: forms.length};
        })()
        """;

    /** 仅查 document.readyState（navigate 落地后二次确认）。 */
    static final String READY_STATE_JS = "(function(){return document.readyState||'';})()";

    static final String CLICK_JS = """
        (function(t){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          // 对齐电脑端 pc_driver.CLICK_JS：a/button 等可点元素优先（含不可见），再兜底 div/span/li/td/p/img
          function find(sel){
            var nodes = document.querySelectorAll(sel);
            for (var i=0;i<nodes.length && i<3000;i++){
              var e = nodes[i];
              var txt = text(e);
              var alt = e.getAttribute ? (e.getAttribute('alt')||'') : '';
              if ((txt && txt.indexOf(t) >= 0) || (alt && alt.indexOf(t) >= 0)){
                // 命中容器(div/span/li/td)时：优先点所在行(tr)的可点元素
                var target = e;
                var tr = e.closest ? e.closest('tr') : null;
                if (tr){
                  var btn = tr.querySelector('a, button, input[type=button], input[type=submit], [role=button], [onclick]');
                  if (btn) target = btn;
                }
                return target;
              }
            }
            return null;
          }
          var el = find('a, button, input[type=button], input[type=submit], [role=button], [onclick]');
          if (!el) el = find('div, span, li, td, p, img');
          if (!el) return "notfound";
          // a 链接：强制当前页跳转（等价电脑端 CLICK_JS：target=_self + click，
          // 解决 target=_blank 不跳/新窗问题，保留 onclick 逻辑）
          if (el.tagName === 'A' && el.href && el.href.indexOf('javascript:') !== 0){
            try { el.setAttribute('target','_self'); el.click(); return "ok"; } catch(err){}
          }
          try{ el.click(); return "ok"; }catch(err){ return "clicked"; }
        })(__TARGET__)
        """;

    static final String FILL_JS = """
        (function(v){
          // 对齐电脑端 FOCUS_FILL_JS：当前聚焦输入框优先，否则第一个可见可填 input/textarea
          function ok(e){ return e && (e.tagName==='INPUT'||e.tagName==='TEXTAREA')
            && e.type!=='hidden' && e.type!=='checkbox' && e.type!=='radio'
            && e.type!=='button' && e.type!=='submit' && e.type!=='file'
            && !e.disabled && e.offsetParent!==null; }
          var el = document.activeElement;
          if (!ok(el)){
            var ins = document.querySelectorAll('input,textarea');
            for (var i=0;i<ins.length;i++){ if (ok(ins[i])){ el = ins[i]; break; } }
          }
          if (!el) return "nofield";
          try {
            var proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            var setter = Object.getOwnPropertyDescriptor(proto,'value').set;
            setter.call(el, v);
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            el.focus();
            return "ok";
          } catch(err){ return "nofield"; }
        })(__VALUE__)
        """;

    // ── 指令集加厚（v2）：scroll_to / wait_clickable / long_press / slider / key_press ──

    /** scroll_to：滚动到含关键词的元素（解决懒加载：先滚到目标再交互）。 */
    // 按 name/id 精确定位填值（对齐电脑端 fill_field；readonly 用 JS setter 兜底，如生日日历）
    static final String FILL_FIELD_JS = """
        (function(a){
          var sel = 'input[name="'+a.n+'"], input[id="'+a.n+'"], textarea[name="'+a.n+'"], textarea[id="'+a.n+'"]';
          var el = document.querySelector(sel);
          if (!el) return "nofield";
          try {
            var proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            var setter = Object.getOwnPropertyDescriptor(proto,'value').set;
            setter.call(el, a.v);
            el.dispatchEvent(new Event('input',{bubbles:true}));
            el.dispatchEvent(new Event('change',{bubbles:true}));
            el.focus();
            return "ok";
          } catch(err){ return "nofield"; }
        })({"n":"__NAME__","v":"__VALUE__"})
        """;

    static final String SCROLL_TO_JS = """
        (function(t){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function into(e){ try{ e.scrollIntoView({block:'center',behavior:'smooth'}); return true; }catch(err){ try{ e.scrollIntoView(); return true; }catch(e2){ return false; } } }
          var q = 'button,a,input,textarea,select,[role="button"],[onclick],[class*="btn"]';
          var nodes = document.querySelectorAll(q);
          for (var i=0;i<nodes.length && i<3000;i++){
            var e = nodes[i]; var txt = text(e);
            if (txt && txt.indexOf(t) >= 0){ return into(e) ? "ok" : "notfound"; }
          }
          // 纯文本节点兜底（懒加载区域）
          var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          var n;
          while (walker.nextNode()) {
            n = walker.currentNode;
            if (n && n.textContent && n.textContent.indexOf(t) >= 0 && n.parentElement){
              return into(n.parentElement) ? "ok" : "notfound";
            }
          }
          return "notfound";
        })(__TARGET__)
        """;

    /** wait_clickable 的检查 JS：返回 "yes"/"no"（目标可见且可点）。 */
    static final String CLICKABLE_JS = """
        (function(t){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function visible(e){
            if (e.offsetParent !== null) return true;
            if (e.tagName==='INPUT' || e.tagName==='TEXTAREA') return true;
            var r = e.getBoundingClientRect();
            return (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight);
          }
          var q = 'button,a,input,textarea,select,[role="button"],[onclick]';
          var nodes = document.querySelectorAll(q);
          for (var i=0;i<nodes.length && i<3000;i++){
            var e = nodes[i]; if (!visible(e)) continue;
            var txt = text(e);
            if (txt === t || (txt && txt.indexOf(t) >= 0)){ return "yes"; }
          }
          return "no";
        })(__TARGET__)
        """;

    /** long_press：长按含关键词元素（触发右键菜单/删除/拖拽入口）。 */
    static final String LONG_PRESS_JS = """
        (function(t){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function visible(e){
            if (e.offsetParent !== null) return true;
            if (e.tagName==='INPUT' || e.tagName==='TEXTAREA') return true;
            var r = e.getBoundingClientRect();
            return (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight);
          }
          var q = 'button,a,input,textarea,select,[role="button"],[onclick]';
          var nodes = document.querySelectorAll(q);
          for (var i=0;i<nodes.length && i<3000;i++){
            var e = nodes[i]; if (!visible(e)) continue;
            var txt = text(e);
            if (txt && txt.indexOf(t) >= 0){
              var r = e.getBoundingClientRect();
              var x = r.left + r.width/2, y = r.top + r.height/2;
              var fire = function(type){
                e.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0}));
              };
              fire('pointerdown'); fire('mousedown');
              setTimeout(function(){ fire('pointerup'); fire('mouseup'); fire('click'); }, 800);
              return "ok";
            }
          }
          return "notfound";
        })(__TARGET__)
        """;

    /** slider：滑块验证码拖动（from 中心 → to 目标，多步 mousemove 模拟）。 */
    static final String SLIDER_JS = """
        (function(t, dx){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function visible(e){
            if (e.offsetParent !== null) return true;
            var r = e.getBoundingClientRect();
            return (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight);
          }
          var q = 'button,a,input,textarea,select,[role="button"],[onclick],[class*="slider"],[class*="captcha"],[class*="drag"],[class*="track"]';
          var nodes = document.querySelectorAll(q);
          var el = null;
          for (var i=0;i<nodes.length && i<3000;i++){
            var e = nodes[i]; if (!visible(e)) continue;
            var txt = text(e);
            if (t && txt && txt.indexOf(t) >= 0){ el = e; break; }
          }
          if (!el){
            // 无关键词匹配：取第一个滑块类元素
            for (var j=0;j<nodes.length && j<3000;j++){
              if (visible(nodes[j])){ el = nodes[j]; break; }
            }
          }
          if (!el) return "notfound";
          var r = el.getBoundingClientRect();
          var startX = r.left + r.width/2, y = r.top + r.height/2;
          var dist = Number(dx) || (r.width + 60);
          var steps = 12;
          var fire = function(type, x){
            el.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,clientX:x,clientY:y,view:window,button:0}));
          };
          fire('pointerdown', startX); fire('mousedown', startX);
          for (var s=1; s<=steps; s++){
            (function(step){
              setTimeout(function(){ fire('pointermove', startX + dist*step/steps); fire('mousemove', startX + dist*step/steps); }, step*30);
            })(s);
          }
          setTimeout(function(){ fire('pointerup', startX+dist); fire('mouseup', startX+dist); }, steps*30+40);
          return "ok";
        })(__TARGET__, __DX__)
        """;

    /** key_press：向当前聚焦元素派发键盘事件（Enter/Tab 等）。 */
    static final String KEY_PRESS_JS = """
        (function(k){
          var e = document.activeElement || document.body;
          try {
            e.dispatchEvent(new KeyboardEvent('keydown',{key:k,code:k,bubbles:true,cancelable:true,view:window}));
            e.dispatchEvent(new KeyboardEvent('keyup',{key:k,code:k,bubbles:true,cancelable:true,view:window}));
            return "ok";
          } catch(err){ return "nofield"; }
        })(__KEY__)
        """;

    // ── 控件原语（v3）：select / check / radio / select_hover / wheel_pick / read_frames ──

    /** select：原生下拉 <select> 选值。 */
    static final String SELECT_JS = """
        (function(label, val){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function matchLabel(e){
            var t = text(e);
            if (!label) return true;
            return (t && t.indexOf(label) >= 0) || (e.getAttribute('name')===label) || (e.id===label);
          }
          var sels = document.querySelectorAll('select');
          for (var i=0;i<sels.length && i<100;i++){
            var s = sels[i]; if (!matchLabel(s)) continue;
            var opts = s.options;
            for (var j=0;j<opts.length;j++){
              var ov = opts[j].value || opts[j].text || '';
              if (ov === val || opts[j].text === val){
                s.value = opts[j].value;
                s.dispatchEvent(new Event('change',{bubbles:true}));
                s.dispatchEvent(new Event('input',{bubbles:true}));
                return "ok";
              }
            }
          }
          return "notfound";
        })(__LABEL__, __VALUE__)
        """;

    /** check：复选框/开关 勾选或取消。 */
    static final String CHECK_JS = """
        (function(label, on){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||e.name||e.id||'').trim(); }
          var q = 'input[type="checkbox"],[role="checkbox"],[class*="checkbox"],[class*="switch"],[class*="check"]';
          var nodes = document.querySelectorAll(q);
          for (var i=0;i<nodes.length && i<300;i++){
            var e = nodes[i];
            var t = text(e);
            if (label && !(t && t.indexOf(label) >= 0)) continue;
            var want = String(on)==='true' || on===true || on===1 || on==='1';
            if (e.tagName === 'INPUT' && e.type === 'checkbox'){
              if (e.checked !== want){ e.click(); }
              else { e.dispatchEvent(new Event('change',{bubbles:true})); }
            } else {
              e.click();
            }
            return "ok";
          }
          return "notfound";
        })(__LABEL__, __ON__)
        """;

    /** radio：单选框选值。 */
    static final String RADIO_JS = """
        (function(label, val){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          var radios = document.querySelectorAll('input[type="radio"]');
          for (var i=0;i<radios.length && i<300;i++){
            var r = radios[i];
            var rv = r.value || '';
            if (rv === val || (r.parentElement && text(r.parentElement) === val) || (label && (r.name===label || text(r)===label))){
              if (!r.checked){ r.click(); }
              return "ok";
            }
          }
          var q = '[role="radio"],[class*="radio"],[class*="option"],[class*="item"]';
          var nodes = document.querySelectorAll(q);
          for (var j=0;j<nodes.length && j<300;j++){
            var e = nodes[j]; var t = text(e);
            if (val && t && t.indexOf(val) >= 0){ e.click(); return "ok"; }
          }
          return "notfound";
        })(__LABEL__, __VALUE__)
        """;

    /** select_hover：悬浮下拉 / 弹层选项（先点开含 openKw 的元素，再点含 optKw 的选项）。 */
    static final String SELECT_HOVER_JS = """
        (function(openKw, optKw){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          function visible(e){
            if (e.offsetParent !== null) return true;
            if (e.tagName==='INPUT' || e.tagName==='TEXTAREA') return true;
            var r = e.getBoundingClientRect();
            return (r.width > 0 && r.height > 0);
          }
          var q = 'button,a,input,textarea,select,[role="button"],[role="combobox"],[onclick],[class*="select"],[class*="picker"]';
          var nodes = document.querySelectorAll(q);
          var opened = false;
          for (var i=0;i<nodes.length && i<500;i++){
            var e = nodes[i]; var t = text(e);
            if (openKw && t && t.indexOf(openKw) >= 0){ try{ e.click(); }catch(err){} opened = true; break; }
          }
          if (!openKw){ opened = true; }
          var optNodes = document.querySelectorAll('li,div,span,a,button,[role="option"],[class*="option"],[class*="item"],[class*="dropdown"]');
          for (var j=0;j<optNodes.length && j<800;j++){
            var o = optNodes[j]; var ot = text(o);
            if (ot && ot === optKw){ try{ o.click(); return "ok"; }catch(err){ return "clicked"; } }
          }
          for (var k=0;k<optNodes.length && k<800;k++){
            var o2 = optNodes[k]; var ot2 = text(o2);
            if (ot2 && ot2.indexOf(optKw) >= 0 && ot2.length < 40){ try{ o2.click(); return "ok"; }catch(err){ return "clicked"; } }
          }
          return opened ? "open_only" : "notfound";
        })(__OPEN__, __OPT__)
        """;

    /** wheel_pick：滚轮选择器（城市/日期/时间滚轮）——滚到目标 + 点确认。 */
    static final String WHEEL_PICK_JS = """
        (function(optKw, confirmKw){
          function text(e){ return (e.innerText||e.value||e.getAttribute('placeholder')||e.getAttribute('aria-label')||'').trim(); }
          var q = 'li,div,span,[role="option"],[class*="wheel"],[class*="picker"],[class*="scroll"]';
          var nodes = document.querySelectorAll(q);
          var target = null;
          for (var i=0;i<nodes.length && i<1000;i++){
            var e = nodes[i]; var t = text(e);
            if (t && t === optKw){ target = e; break; }
          }
          if (!target){
            for (var j=0;j<nodes.length && j<1000;j++){
              var e2 = nodes[j]; var t2 = text(e2);
              if (t2 && t2.indexOf(optKw) >= 0 && t2.length < 20){ target = e2; break; }
            }
          }
          if (target){
            try{ target.scrollIntoView({block:'center'}); }catch(err){ try{ target.scrollIntoView(); }catch(e3){} }
            try{ target.click(); }catch(err){}
          }
          var btns = document.querySelectorAll('button,a,[role="button"],[class*="confirm"],[class*="done"],[class*="ok"]');
          for (var k=0;k<btns.length && k<100;k++){
            var b = btns[k]; var bt = text(b);
            if (bt && (bt.indexOf(confirmKw) >= 0 || (confirmKw==='' && (bt.indexOf('确定')>=0||bt.indexOf('完成')>=0||bt.indexOf('确认')>=0)))){
              try{ b.click(); return "ok"; }catch(err){ return "clicked"; }
            }
          }
          return target ? "selected" : "notfound";
        })(__OPT__, __CONFIRM__)
        """;

    /** read_frames：读取所有 iframe 内的文本（跨 frame 识别）。 */
    static final String READ_FRAMES_JS = """
        (function(){
          var out = [];
          try {
            var frames = document.querySelectorAll('iframe,frame');
            for (var i=0;i<frames.length && i<20;i++){
              var f = frames[i];
              try {
                var doc = f.contentDocument || f.contentWindow.document;
                var txt = doc && doc.body ? doc.body.innerText : '';
                out.push({index:i, text:(txt||'').slice(0,3000)});
              } catch(err){ out.push({index:i, text:'', cross:true}); }
            }
          } catch(err){}
          return JSON.stringify(out);
        })()
        """;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        FrameLayout root = new FrameLayout(this);

        uiWeb = makeUiWeb();
        browserContainer = makeBrowserContainer();
        browserContainer.setVisibility(View.GONE);

        root.addView(uiWeb, new FrameLayout.LayoutParams(-1, -1));
        root.addView(browserContainer, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);

        uiWeb.loadUrl("file:///android_asset/ui.html");
        browserWeb.loadUrl("file:///android_asset/browser_home.html");
    }

    private WebView makeUiWeb() {
        // 调试机：开启 WebView 远程调试（chrome://inspect / CDP 注入辅助），上线可移除
        WebView.setWebContentsDebuggingEnabled(true);
        WebView w = new WebView(this);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        w.setFocusable(true);
        w.setFocusableInTouchMode(true);
        // 点输入框强制弹键盘（不依赖 JS onfocus 时机，兼容部分 ROM WebView 不弹键盘）
        final float sidebarPx = 250f * getResources().getDisplayMetrics().density;   // 侧边栏宽 250 CSS px(≈dp)
        w.setOnTouchListener((v, ev) -> {
            final int act = ev.getActionMasked();
            // 侧边栏「点右侧收回」：原生在 DOWN 时让 JS 自查侧边栏是否打开，是则关闭（幂等，未开无操作）。
            // 华为 WebView 对遮罩（覆盖可滚动区）上方的触摸会吞掉 click/touchstart，前端事件不可靠，必须由原生兜底；
            // 不依赖任何 JS 状态标记，直接查 DOM 真实状态。
            if (act == android.view.MotionEvent.ACTION_DOWN && ev.getX() > sidebarPx) {
                try {
                    Log.d(TAG, "right-tap DOWN x=" + ev.getX() + " > " + sidebarPx + " → 触发 closeSidebar");
                    uiWeb.evaluateJavascript(
                        "(function(){var s=document.getElementById('sidebar');" +
                        "if(s&&s.classList.contains('open')){closeSidebar();}})();", null);
                } catch (Exception ignore) {}
            }
            if (act == android.view.MotionEvent.ACTION_UP) {
                v.requestFocus();
                // 键盘显隐交给 JS 自然处理：点输入框 → onfocus → showKeyboard() 弹键盘；
                // 点消息区 / 空白 / 按钮 → syncSoftInput 按 activeElement 判断，非输入框则收起。
                // （不再用「屏幕下半部就强制弹键盘」的粗暴逻辑，点消息区不再弹键盘。）
                syncSoftInput(w);
            }
            return false;
        });
        w.setWebChromeClient(new WebChromeClient());
        w.addJavascriptInterface(new JsBridge(), "AndroidBridge");
        return w;
    }

    /** 内置浏览器容器：原生地址栏 + browserWeb。 */
    private LinearLayout makeBrowserContainer() {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setBackgroundColor(Color.WHITE);

        // 地址栏：返回 | 网址输入 | 前往
        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(8, 6, 8, 6);
        bar.setBackgroundColor(0xFFF3F4F6);

        Button backBtn = new Button(this);
        backBtn.setText("←");
        backBtn.setTextSize(16);
        backBtn.setPadding(6, 8, 6, 8);
        backBtn.setOnClickListener(v -> showChat());

        addrEdit = new EditText(this);
        addrEdit.setSingleLine(true);
        addrEdit.setHint("输入网址，如 baidu.com");
        addrEdit.setTextSize(14);
        addrEdit.setPadding(12, 8, 12, 8);
        addrEdit.setBackgroundColor(Color.WHITE);
        addrEdit.setInputType(InputType.TYPE_TEXT_VARIATION_URI);
        addrEdit.setImeOptions(EditorInfo.IME_ACTION_GO);
        addrEdit.setOnEditorActionListener((v, actionId, ev) -> {
            if (actionId == EditorInfo.IME_ACTION_GO) { goAddr(); return true; }
            return false;
        });

        Button goBtn = new Button(this);
        goBtn.setText("前往");
        goBtn.setTextSize(13);
        goBtn.setPadding(10, 8, 10, 8);
        goBtn.setOnClickListener(v -> goAddr());

        bar.addView(backBtn, new LinearLayout.LayoutParams(-2, -2));
        bar.addView(addrEdit, new LinearLayout.LayoutParams(0, -2, 1f));
        bar.addView(goBtn, new LinearLayout.LayoutParams(-2, -2));

        browserWeb = makeBrowserWeb();

        col.addView(bar, new LinearLayout.LayoutParams(-1, -2));
        col.addView(browserWeb, new LinearLayout.LayoutParams(-1, 0, 1f));
        return col;
    }

    private void goAddr() {
        String u = (addrEdit.getText() == null ? "" : addrEdit.getText().toString()).trim();
        if (u.isEmpty()) return;
        if (!u.startsWith("http://") && !u.startsWith("https://")) u = "https://" + u;
        browserWeb.loadUrl(u);
    }

    /** 显示聊天主界面（隐藏浏览器容器）。 */
    private void showChat() {
        uiWeb.setVisibility(View.VISIBLE);
        browserContainer.setVisibility(View.GONE);
    }

    /** 显示浏览器：url='home' 回起始页；否则加载 url。 */
    private void showBrowserView(String url) {
        if ("home".equals(url)) {
            browserWeb.loadUrl("file:///android_asset/browser_home.html");
        } else if (url != null && !url.isEmpty()) {
            browserWeb.loadUrl(url);
        }
        uiWeb.setVisibility(View.GONE);
        browserContainer.setVisibility(View.VISIBLE);
    }

    private WebView makeBrowserWeb() {
        WebView w = new WebView(this);
        w.setFocusable(true);
        w.setFocusableInTouchMode(true);
        // 点输入框强制弹键盘（页面 input 点击也能弹）
        w.setOnTouchListener((v, ev) -> {
            if (ev.getAction() == android.view.MotionEvent.ACTION_UP) {
                v.requestFocus();
                v.postDelayed(() -> {
                    try {
                        InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                        if (imm != null) imm.showSoftInput(v, InputMethodManager.SHOW_FORCED);
                    } catch (Exception e) {}
                }, 150);
            }
            return false;
        });
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        // 移动 H5（途牛 M 站 / passport 登录页）视口/弹层需要
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        // 记录系统默认 UA，供 navigate 切回（glyy 老站用微信 UA，其他站点恢复默认）
        try { webViewDefaultUA = s.getUserAgentString(); } catch (Exception ignore) { webViewDefaultUA = ""; }
        // 浏览器 Cookie 持久化（登录态保留，免重复登录）
        CookieManager cm = CookieManager.getInstance();
        cm.setAcceptCookie(true);
        cm.setAcceptThirdPartyCookies(w, true);
        cm.flush();
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        s.setSupportMultipleWindows(true);
        // 用系统标准 UA（部分网站对自定义 UA 返回空白页）
        // s.setUserAgentString(s.getUserAgentString() + " XiamiHost/0.1");
        w.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                // 支付：支付宝 scheme（alipays:// / alipay://）→ 直接拉起支付宝 App（桌面弹出）
                if (url != null && (url.startsWith("alipays://") || url.startsWith("alipay://"))) {
                    try {
                        Intent i = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                        startActivity(i);
                    } catch (Exception e) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                        } catch (Exception ignore) {}
                    }
                    return true;
                }
                // 其余 URL（含 https 支付宝 H5/途牛收银台）留在 WebView 内加载
                return super.shouldOverrideUrlLoading(view, url);
            }
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                String url = request != null ? request.getUrl().toString() : null;
                if (url != null && (url.startsWith("alipays://") || url.startsWith("alipay://"))) {
                    try {
                        Intent i = Intent.parseUri(url, Intent.URI_INTENT_SCHEME);
                        startActivity(i);
                    } catch (Exception e) {
                        try {
                            startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                        } catch (Exception ignore) {}
                    }
                    return true;
                }
                return super.shouldOverrideUrlLoading(view, request);
            }
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                if (addrEdit != null && url != null && !url.isEmpty()) {
                    addrEdit.setText(url);
                }
                onBrowserPageFinished();
            }
            @Override
            public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                // glyy 等老站自签名/老 TLS（net::ERR_SSL_VERSION_INTERFERENCE）必须放行，
                // 与 SkillExecutor 的 trustAll 对齐；仅内置浏览器，不影响系统。
                try { handler.proceed(); } catch (Exception ignore) {}
            }
        });
        w.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                // 处理网站 window.open（如闲鱼「发闲置」新开页面）：
                // 用临时 WebView 拿到新窗口 URL → 导航到当前 browserWeb
                try {
                    WebView temp = new WebView(MainActivity.this);
                    temp.getSettings().setJavaScriptEnabled(true);
                    WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                    transport.setWebView(temp);
                    resultMsg.sendToTarget();
                    temp.setWebViewClient(new WebViewClient() {
                        @Override
                        public void onPageStarted(WebView v, String url, Bitmap favicon) {
                            v.setWebViewClient(null);
                            if (url != null && !url.isEmpty()) {
                                browserWeb.loadUrl(url);
                            }
                            v.destroy();
                        }
                    });
                    return true;
                } catch (Exception e) {
                    return false;
                }
            }
            @Override
            public boolean onShowFileChooser(WebView webView, ValueCallback<Uri[]> filePathCallback,
                                             FileChooserParams fileChooserParams) {
                // 网页点击「上传/选文件」→ 打开系统文件选择器（相册/文件管理）
                if (uploadCallback != null) {
                    uploadCallback.onReceiveValue(null);
                }
                uploadCallback = filePathCallback;
                Intent intent = fileChooserParams.createIntent();
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                try {
                    startActivityForResult(intent, FILE_CHOOSER_REQUEST);
                } catch (Exception e) {
                    uploadCallback = null;
                    return false;
                }
                return true;
            }
        });
        w.addJavascriptInterface(new JsBridge(), "AndroidBridge");
        return w;
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        if (requestCode == FILE_CHOOSER_REQUEST) {
            if (uploadCallback == null) return;
            Uri[] result = null;
            if (resultCode == RESULT_OK && data != null) {
                if (data.getData() != null) {
                    result = new Uri[]{data.getData()};
                } else if (data.getClipData() != null) {
                    int n = data.getClipData().getItemCount();
                    result = new Uri[n];
                    for (int i = 0; i < n; i++) result[i] = data.getClipData().getItemAt(i).getUri();
                }
            }
            uploadCallback.onReceiveValue(result);
            uploadCallback = null;
            return;
        }
        if (requestCode == CHAT_FILE_REQUEST && resultCode == RESULT_OK && data != null && data.getData() != null) {
            sendFileToUi(data.getData());
            return;
        }
        if (requestCode == PHOTO_REQUEST && resultCode == RESULT_OK && photoUri != null) {
            sendFileToUi(photoUri);
            photoUri = null;
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /** 原生读文件 → base64 回传 ui.html（window.__fileChosen），用于聊天上传云端。 */
    private void sendFileToUi(Uri uri) {
        try (InputStream is = getContentResolver().openInputStream(uri)) {
            byte[] bytes = new byte[is.available()];
            int off = 0;
            while (off < bytes.length) {
                int r = is.read(bytes, off, bytes.length - off);
                if (r < 0) break;
                off += r;
            }
            String name = "";
            String mime = getContentResolver().getType(uri);
            try (android.database.Cursor c = getContentResolver().query(uri, null, null, null, null)) {
                if (c != null && c.moveToFirst()) {
                    int idx = c.getColumnIndex(android.provider.OpenableColumns.DISPLAY_NAME);
                    if (idx >= 0) name = c.getString(idx);
                }
            }
            String b64 = Base64.encodeToString(bytes, Base64.NO_WRAP);
            String js = "window.__fileChosen('" + esc(name) + "','" + b64 + "','" + esc(mime == null ? "" : mime) + "')";
            uiWeb.evaluateJavascript(js, null);
        } catch (Exception e) {
            Log.w(TAG, "read uri err", e);
        }
    }

    /** 把原生执行结果回传 UI（注入 window.__cmdResult(cbId, json)）。 */
    void cbResult(String cbId, String json) {
        String safe = json.replace("\\", "\\\\").replace("'", "\\'")
                .replace("\n", "\\n").replace("\r", "\\r");
        String js = "window.__cmdResult('" + cbId + "', '" + safe + "')";
        uiWeb.post(() -> uiWeb.evaluateJavascript(js, null));
    }

    private static String esc(String s) {
        if (s == null) return "";
        return s.replace("\\", "\\\\").replace("'", "\\'")
                .replace("\"", "\\\"").replace("\n", " ").replace("\r", " ");
    }

    /** navigate/refresh 触发的页面加载完成：取消超时，settle 后回执。 */
    void onBrowserPageFinished() {
        final String cbId = pendingNavCbId;
        if (cbId == null) return;
        pendingNavCbId = null;
        if (navTimeoutRunnable != null) {
            h.removeCallbacks(navTimeoutRunnable);
            navTimeoutRunnable = null;
        }
        settleNavigate(cbId, false, 0);
    }

    /** readyState 轮询 + 短 settle，适配 SPA 晚渲染。 */
    void settleNavigate(String cbId, boolean timedOut, int attempt) {
        browserWeb.evaluateJavascript(READY_STATE_JS, value -> {
            String state = value == null ? "" : value.replace("\"", "");
            boolean done = "complete".equals(state) || attempt >= 15;
            if (done) {
                h.postDelayed(() -> {
                    if (timedOut) {
                        cbResult(cbId, "{\"ok\":true,\"warning\":\"load_timeout\",\"readyState\":\"" + esc(state) + "\"}");
                    } else {
                        cbResult(cbId, "{\"ok\":true,\"ready\":true,\"readyState\":\"" + esc(state) + "\"}");
                    }
                }, 400);
            } else {
                h.postDelayed(() -> settleNavigate(cbId, timedOut, attempt + 1), 200);
            }
        });
    }

    /** 开始等待下一次 onPageFinished；超时仍回 ok+warning，避免卡死 WS。 */
    void beginAwaitPageLoad(String cbId, long timeoutMs) {
        if (navTimeoutRunnable != null) {
            h.removeCallbacks(navTimeoutRunnable);
            navTimeoutRunnable = null;
        }
        // 若上一次 navigate 还没回，先失败收尾
        if (pendingNavCbId != null) {
            String old = pendingNavCbId;
            pendingNavCbId = null;
            cbResult(old, "{\"ok\":false,\"error\":\"navigate_superseded\"}");
        }
        pendingNavCbId = cbId;
        final String captured = cbId;
        navTimeoutRunnable = () -> {
            if (captured.equals(pendingNavCbId)) {
                pendingNavCbId = null;
                navTimeoutRunnable = null;
                settleNavigate(captured, true, 15);
            }
        };
        h.postDelayed(navTimeoutRunnable, timeoutMs);
    }

    /** check_ready：轮询 DOM，直到关键词出现或表单数达标。 */
    void pollCheckReady(String cbId, String keyword, java.util.List<String> keywords,
                        int minForms, long deadlineMs) {
        browserWeb.evaluateJavascript(READ_JS, value -> {
            String v = (value == null || value.equals("null")) ? "{}" : value;
            boolean ok = false;
            String hit = "";
            int formsCount = 0;
            try {
                // evaluateJavascript 返回的是 JSON 字符串字面量，需再解一层
                String raw = v;
                if (raw.length() >= 2 && raw.charAt(0) == '"') {
                    raw = new JSONObject("{\"x\":" + raw + "}").getString("x");
                }
                JSONObject data = new JSONObject(raw);
                String pageText = data.optString("page_text", "");
                formsCount = data.optJSONArray("forms") == null ? 0 : data.optJSONArray("forms").length();
                if (keyword != null && !keyword.isEmpty() && pageText.contains(keyword)) {
                    ok = true; hit = keyword;
                }
                if (!ok && keywords != null) {
                    for (String k : keywords) {
                        if (k != null && !k.isEmpty() && pageText.contains(k)) {
                            ok = true; hit = k; break;
                        }
                    }
                }
                boolean formsOk = minForms <= 0 || formsCount >= minForms;
                boolean kwRequired = (keyword != null && !keyword.isEmpty())
                        || (keywords != null && !keywords.isEmpty());
                if (kwRequired) {
                    ok = ok && formsOk;
                } else {
                    ok = formsOk && "complete".equals(data.optString("readyState", ""));
                }
                if (ok) {
                    cbResult(cbId, "{\"ok\":true,\"hit\":\"" + esc(hit)
                            + "\",\"forms_count\":" + formsCount + ",\"data\":" + raw + "}");
                    return;
                }
            } catch (Exception e) {
                Log.w(TAG, "check_ready parse", e);
            }
            if (System.currentTimeMillis() >= deadlineMs) {
                cbResult(cbId, "{\"ok\":false,\"error\":\"check_ready_timeout\",\"forms_count\":"
                        + formsCount + ",\"hit\":\"" + esc(hit) + "\"}");
                return;
            }
            h.postDelayed(() -> pollCheckReady(cbId, keyword, keywords, minForms, deadlineMs), 800);
        });
    }

    /** wait_clickable：轮询 DOM，直到目标关键词对应的元素「可见且可点」。 */
    void pollClickable(String cbId, String target, long deadlineMs) {
        String js = CLICKABLE_JS.replace("__TARGET__", "'" + esc(target) + "'");
        browserWeb.evaluateJavascript(js, value -> {
            boolean ok = value != null && value.contains("yes");
            if (ok) {
                cbResult(cbId, "{\"ok\":true}");
                return;
            }
            if (System.currentTimeMillis() >= deadlineMs) {
                cbResult(cbId, "{\"ok\":false,\"error\":\"wait_clickable_timeout:" + esc(target) + "\"}");
                return;
            }
            h.postDelayed(() -> pollClickable(cbId, target, deadlineMs), 800);
        });
    }

    /** 键盘自动显隐：焦点在输入框 → 弹；点空白/其它 → 自然收起（替代 SHOW_FORCED 锁死）。 */
    void syncSoftInput(WebView w) {
        try {
            w.evaluateJavascript(
                "(function(){var e=document.activeElement;return (e&&(e.tagName==='INPUT'||e.tagName==='TEXTAREA'))?'yes':'no';})()",
                value -> {
                    boolean input = value != null && value.contains("yes");
                    InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                    if (imm == null) return;
                    if (input) {
                        w.requestFocus();
                        imm.showSoftInput(w, InputMethodManager.SHOW_IMPLICIT);
                    } else {
                        imm.hideSoftInputFromWindow(w.getWindowToken(), 0);
                    }
                });
        } catch (Exception e) {
            Log.w(TAG, "syncSoftInput err", e);
        }
    }

    // ═══════════ JS Bridge（UI → 原生）═══════════
    class JsBridge {
        /** 第 6 条：执行 skill 请求蓝图（手机直连平台）→ 回调 ui.html __skillResult 回传 skill_result。
         *  App 内置固定引擎（红线 A：只执行 JSON 配置，绝不下发/执行代码）。 */
        @JavascriptInterface
        public void executeSkill(String reqId, String blueprintJson) {
            new Thread(() -> {
                final String rid = reqId == null ? "" : reqId;
                try {
                    SkillExecutor ex = new SkillExecutor(MainActivity.this);
                    // 注入登录交互宿主：手机端全权处理登录（方案②），登录时在聊天里推送输入框/图形码
                    ex.setLoginInteractor(loginInteractor);
                    String result = ex.execute(blueprintJson);
                    final String js = "window.__skillResult && window.__skillResult("
                            + JSONObject.quote(rid) + "," + result + ");";
                    runOnUiThread(() -> { try { uiWeb.evaluateJavascript(js, null); } catch (Exception ignore) {} });
                } catch (Exception e) {
                    final String err = String.valueOf(e.getMessage());
                    runOnUiThread(() -> {
                        try {
                            uiWeb.evaluateJavascript("window.__skillResult && window.__skillResult("
                                    + JSONObject.quote(rid)
                                    + ",{\"ok\":false,\"status\":0,\"headers\":{},\"body\":\"\",\"error\":"
                                    + JSONObject.quote(err) + "});", null);
                        } catch (Exception ignore) {}
                    });
                }
            }).start();
        }

        /** 手机端通用登录：用户输入回传（ui.html 登录输入框提交时调用，释放等待 latch）。 */
        @JavascriptInterface
        public void loginInput(String value) {
            onLoginInput(value);
        }


        /** 第 5 条：打开系统浏览器支付（App 内零收款，支付全流程在第三方收银台）。 */
        @JavascriptInterface
        public void openExternal(String url) {
            try {
                if (url == null || url.isEmpty()) return;
                Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
            } catch (Exception ignore) {}
        }

        /** 第 4 条：把登录态写入手机本地凭据库（skill, kind=token|cookie|session|api_key, value）。
         *  第三方登录态只存用户手机本地（用户自己的凭据），云端不聚合。 */
        @JavascriptInterface
        public void saveCredential(String skill, String kind, String value) {
            try {
                CredentialStore cs = new CredentialStore(MainActivity.this);
                String v = value == null ? "" : value;
                if ("token".equals(kind)) cs.setToken(skill, v);
                else if ("cookie".equals(kind)) cs.setCookie(skill, v);
                else if ("session".equals(kind)) cs.setSessionId(skill, v);
                else if ("api_key".equals(kind)) cs.setApiKey(v);
            } catch (Exception ignore) {}
        }

        /** 授权中心：返回各平台登录态状态（供 ui.html「授权中心」显示；凭据只在本机，不外传）。
         *  返回 JSON：{skill: {name, category, kind, authorized}} */
        @JavascriptInterface
        public String getCredentials() {
            try {
                CredentialStore cs = new CredentialStore(MainActivity.this);
                org.json.JSONObject out = new org.json.JSONObject();
                out.put("glyy", authStatus(cs, "glyy", "南京鼓楼医院", "医疗挂号", "token"));
                out.put("tuniu", authStatus(cs, "tuniu", "途牛旅游", "出行订票", "cookie"));
                return out.toString();
            } catch (Exception e) { return "{}"; }
        }

        private org.json.JSONObject authStatus(CredentialStore cs, String skill,
                                              String name, String category, String kind) {
            org.json.JSONObject o = new org.json.JSONObject();
            try {
                o.put("name", name);
                o.put("category", category);
                o.put("kind", kind);
                boolean auth;
                if ("token".equals(kind)) auth = !cs.getToken(skill).isEmpty();
                else if ("cookie".equals(kind)) auth = !cs.getCookie(skill).isEmpty();
                else auth = !cs.getSessionId(skill).isEmpty();
                o.put("authorized", auth);
            } catch (Exception ignore) {}
            return o;
        }

        /** 授权中心：清除指定平台登录态（退出登录）。 */
        @JavascriptInterface
        public void clearCredential(String skill) {
            try {
                CredentialStore cs = new CredentialStore(MainActivity.this);
                cs.setToken(skill, ""); cs.setCookie(skill, "");
                cs.setSessionId(skill, ""); cs.setRefreshToken(skill, "");
            } catch (Exception ignore) {}
        }

        @JavascriptInterface
        public void executeCmd(String cmd, String paramsJson, String cbId) {
            runOnUiThread(() -> {
                try {
                    JSONObject p = new JSONObject(paramsJson == null ? "{}" : paramsJson);
                    String c = cmd == null ? "" : cmd;
                    switch (c) {
                        case "export_cookies": {
                            // 导出当前网页登录态 cookies（用户自己的账号，用于后续请求保持登录）
                            String domain = p.optString("domain", "");
                            if (domain.isEmpty()) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"domain empty\"}");
                                break;
                            }
                            try {
                                String cookies = CookieManager.getInstance().getCookie(domain);
                                // 第 4 条：登录态存手机本地凭据库（tuniu），云端不持有
                                try {
                                    new CredentialStore(MainActivity.this).setCookie("tuniu", String.valueOf(cookies));
                                } catch (Exception ignore) {}
                                // 同步写一份到 /sdcard/Download/tuniu_cookies.txt（供电脑 adb pull 读取/摸接口）
                                try {
                                    java.io.File f = new java.io.File("/sdcard/Download/tuniu_cookies.txt");
                                    java.io.FileOutputStream fos = new java.io.FileOutputStream(f);
                                    fos.write((domain + "\n" + String.valueOf(cookies)).getBytes("UTF-8"));
                                    fos.close();
                                } catch (Exception ignore) {}
                                cbResult(cbId, "{\"ok\":true,\"domain\":\"" + esc(domain)
                                        + "\",\"cookies\":" + JSONObject.quote(String.valueOf(cookies)) + "}");
                            } catch (Exception e) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"cookie err\"}");
                            }
                            break;
                        }
                        case "navigate": {
                            String url = p.optString("url", "");
                            long timeoutMs = p.optLong("timeout_ms", NAV_DEFAULT_TIMEOUT_MS);
                            if (timeoutMs < 5000) timeoutMs = 5000;
                            if (url.isEmpty()) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"url empty\"}");
                                break;
                            }
                            // 切到浏览器界面（不二次 load；加载只在这里做一次）
                            uiWeb.setVisibility(View.GONE);
                            browserContainer.setVisibility(View.VISIBLE);
                            beginAwaitPageLoad(cbId, timeoutMs);
                            // 老站对无 Referer 请求返回 403 → 统一带站内 Referer（取当前 URL 域名）
                            java.util.Map<String, String> hdrs = new java.util.HashMap<>();
                            String refHost = "";
                            try { refHost = new java.net.URI(url).getHost(); } catch (Exception ignore) {}
                            if (refHost != null && !refHost.isEmpty()) {
                                hdrs.put("Referer", "https://" + refHost + "/");
                            }
                            // 支持自定义 Referer（glyy 网页被云防护 504，需带小程序 servicewechat Referer 才能过防护）
                            String referer = p.optString("referer", "");
                            if (!referer.isEmpty()) {
                                hdrs.put("Referer", referer);
                            }
                            // glyy 等老站必需微信 UA（否则服务器挂起/403）；ua=wechat 时切换，
                            // 非 wechat 一律恢复默认系统 UA（避免残留微信 UA 影响其他站点）
                            String ua = p.optString("ua", "");
                            if ("wechat".equals(ua)) {
                                browserWeb.getSettings().setUserAgentString(
                                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                        + "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                                        + "MicroMessenger/8.0.38(0x18002623) NetType/WIFI Language/zh_CN");
                            } else {
                                browserWeb.getSettings().setUserAgentString(webViewDefaultUA);
                            }
                            browserWeb.loadUrl(url, hdrs);
                            break;
                        }
                        case "export_token": {
                            // 导出当前网页登录态 token（glyy Bearer token）→ 存手机凭据库 CredentialStore。
                            // 先扫 localStorage 常见 token key；没有再回退 CookieManager 里找 token 字段。
                            String skill = p.optString("skill", "glyy");
                            final String domain = p.optString("domain", "");
                            browserWeb.evaluateJavascript(
                                "(function(){try{var keys=['access_token','token','userToken','authToken',"
                                + "'authorization','Authorization'];var found='';var all={};"
                                + "for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);"
                                + "var v=localStorage.getItem(k);if(v&&v.length>0)all[k]=v;}"
                                + "for(var j=0;j<keys.length;j++){if(all[keys[j]]){found=all[keys[j]];break;}}"
                                + "return JSON.stringify({found:found,all:all});"
                                + "}catch(e){return JSON.stringify({found:'',all:{},err:''+e});}})()",
                                value -> {
                                    String v = (value == null || value.equals("null")) ? "{}" : value;
                                    try {
                                        String raw = v;
                                        if (raw.length() >= 2 && raw.charAt(0) == '"') {
                                            raw = new JSONObject("{\"x\":" + raw + "}").getString("x");
                                        }
                                        JSONObject o = new JSONObject(raw);
                                        String tk = o.optString("found", "");
                                        JSONObject all = o.optJSONObject("all");
                                        if (tk.isEmpty() && all != null) {
                                            // 兜底：遍历 localStorage 找含 token 的 key
                                            java.util.Iterator<String> it = all.keys();
                                            while (it.hasNext()) {
                                                String k = it.next();
                                                String val = all.optString(k, "");
                                                if (!val.isEmpty() && (k.toLowerCase().contains("token"))) {
                                                    tk = val; break;
                                                }
                                            }
                                        }
                                        // 兜底2：cookie 里找 token 字段（glyy 登录态可能放 cookie）
                                        if (tk.isEmpty() && domain != null && !domain.isEmpty()) {
                                            String cookies = CookieManager.getInstance().getCookie(domain);
                                            if (cookies != null) {
                                                String[] parts = cookies.split(";");
                                                for (String ck : parts) {
                                                    String[] kv = ck.trim().split("=", 2);
                                                    if (kv.length == 2 && (kv[0].toLowerCase().contains("token"))) {
                                                        tk = kv[1].trim(); break;
                                                    }
                                                }
                                            }
                                        }
                                        if (!tk.isEmpty()) {
                                            new CredentialStore(MainActivity.this).setToken(skill, tk);
                                            // 同步写一份到 Download 供排查（登录态仅存本机）
                                            try {
                                                java.io.File f = new java.io.File(
                                                        "/sdcard/Download/" + skill + "_token.txt");
                                                java.io.FileOutputStream fos = new java.io.FileOutputStream(f);
                                                fos.write((domain + "\n" + tk).getBytes("UTF-8"));
                                                fos.close();
                                            } catch (Exception ignore) {}
                                            cbResult(cbId, "{\"ok\":true,\"skill\":\"" + skill
                                                    + "\",\"token_len\":" + tk.length() + "}");
                                        } else {
                                            String keys = (all == null) ? "" : all.toString();
                                            cbResult(cbId, "{\"ok\":false,\"error\":\"no token in localStorage/cookie\","
                                                    + "\"keys\":" + JSONObject.quote(keys) + "}");
                                        }
                                    } catch (Exception e) {
                                        cbResult(cbId, "{\"ok\":false,\"error\":\"export_token parse err\"}");
                                    }
                                });
                            break;
                        }
                        case "check_ready": {
                            String keyword = p.optString("keyword", "");
                            int minForms = p.optInt("min_forms", 0);
                            long timeoutMs = p.optLong("timeout_ms", 30000);
                            if (timeoutMs < 1000) timeoutMs = 1000;
                            java.util.List<String> kws = new java.util.ArrayList<>();
                            JSONArray arr = p.optJSONArray("keywords");
                            if (arr != null) {
                                for (int i = 0; i < arr.length(); i++) {
                                    String k = arr.optString(i, "");
                                    if (!k.isEmpty()) kws.add(k);
                                }
                            }
                            long deadline = System.currentTimeMillis() + timeoutMs;
                            pollCheckReady(cbId, keyword, kws, minForms, deadline);
                            break;
                        }
                        case "read": {
                            browserWeb.evaluateJavascript(READ_JS, value -> {
                                String v = (value == null || value.equals("null")) ? "{}" : value;
                                cbResult(cbId, "{\"ok\":true,\"data\":" + v + "}");
                            });
                            break;
                        }
                        case "click": {
                            String target = p.optString("target", "");
                            String js = CLICK_JS.replace("__TARGET__", "'" + esc(target) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && (value.contains("ok") || value.contains("clicked"));
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到可点元素:" + esc(target) + "\"}");
                            });
                            break;
                        }
                        case "fill": {
                            String value = "";
                            JSONArray fields = p.optJSONArray("fields");
                            if (fields != null && fields.length() > 0) {
                                value = fields.optJSONObject(0).optString("value", "");
                            }
                            String js = FILL_JS.replace("__VALUE__", "'" + esc(value) + "'");
                            browserWeb.evaluateJavascript(js, r -> {
                                boolean ok = r != null && r.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到可填输入框\"}");
                            });
                            break;
                        }
                        case "fill_field": {
                            // 按 name/id 精确定位填值（对齐电脑端 fill_field；readonly 日历也能填）
                            String nid = p.optString("name", "");
                            String val = p.optString("value", "");
                            String js = FILL_FIELD_JS.replace("__NAME__", esc(nid)).replace("__VALUE__", esc(val));
                            browserWeb.evaluateJavascript(js, r -> {
                                boolean ok = r != null && r.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到字段:" + esc(nid) + "\"}");
                            });
                            break;
                        }
                        case "wait":
                        case "wait_for": {
                            long ms = Math.max(100, p.optLong("ms", 800));
                            h.postDelayed(() -> cbResult(cbId, "{\"ok\":true}"), ms);
                            break;
                        }
                        case "refresh": {
                            long timeoutMs = p.optLong("timeout_ms", NAV_DEFAULT_TIMEOUT_MS);
                            if (timeoutMs < 5000) timeoutMs = 5000;
                            beginAwaitPageLoad(cbId, timeoutMs);
                            browserWeb.reload();
                            break;
                        }
                        // ── 指令集加厚（v2）──
                        case "scroll_to": {
                            String target = p.optString("target", "");
                            String js = SCROLL_TO_JS.replace("__TARGET__", "'" + esc(target) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"滚不到目标:" + esc(target) + "\"}");
                            });
                            break;
                        }
                        case "wait_clickable": {
                            String target = p.optString("target", "");
                            long timeoutMs = p.optLong("timeout_ms", 30000);
                            if (timeoutMs < 1000) timeoutMs = 1000;
                            long deadline = System.currentTimeMillis() + timeoutMs;
                            pollClickable(cbId, target, deadline);
                            break;
                        }
                        case "long_press": {
                            String target = p.optString("target", "");
                            String js = LONG_PRESS_JS.replace("__TARGET__", "'" + esc(target) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到长按目标:" + esc(target) + "\"}");
                            });
                            break;
                        }
                        case "slider": {
                            String target = p.optString("target", "");
                            String dx = p.optString("dx", "0");
                            String js = SLIDER_JS
                                    .replace("__TARGET__", "'" + esc(target) + "'")
                                    .replace("__DX__", esc(dx));
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到滑块" + (target.isEmpty() ? "" : ":" + esc(target)) + "\"}");
                            });
                            break;
                        }
                        case "key_press": {
                            String key = p.optString("key", "Enter");
                            String js = KEY_PRESS_JS.replace("__KEY__", "'" + esc(key) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"按键失败:" + esc(key) + "\"}");
                            });
                            break;
                        }
                        // ── 控件原语（v3）：select / check / radio / select_hover / wheel_pick / read_frames ──
                        case "select": {
                            String label = p.optString("label", "");
                            String val = p.optString("value", "");
                            String js = SELECT_JS
                                    .replace("__LABEL__", "'" + esc(label) + "'")
                                    .replace("__VALUE__", "'" + esc(val) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到下拉项:" + esc(val) + "\"}");
                            });
                            break;
                        }
                        case "check": {
                            String label = p.optString("label", "");
                            boolean on = p.optBoolean("on", true);
                            String js = CHECK_JS
                                    .replace("__LABEL__", "'" + esc(label) + "'")
                                    .replace("__ON__", on ? "true" : "false");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到勾选项:" + esc(label) + "\"}");
                            });
                            break;
                        }
                        case "radio": {
                            String label = p.optString("label", "");
                            String val = p.optString("value", "");
                            String js = RADIO_JS
                                    .replace("__LABEL__", "'" + esc(label) + "'")
                                    .replace("__VALUE__", "'" + esc(val) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到单选项:" + esc(val) + "\"}");
                            });
                            break;
                        }
                        case "select_hover": {
                            String openKw = p.optString("open", "");
                            String optKw = p.optString("opt", "");
                            String js = SELECT_HOVER_JS
                                    .replace("__OPEN__", "'" + esc(openKw) + "'")
                                    .replace("__OPT__", "'" + esc(optKw) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"找不到悬浮选项:" + esc(optKw) + "\"}");
                            });
                            break;
                        }
                        case "wheel_pick": {
                            String optKw = p.optString("opt", "");
                            String confirmKw = p.optString("confirm", "");
                            String js = WHEEL_PICK_JS
                                    .replace("__OPT__", "'" + esc(optKw) + "'")
                                    .replace("__CONFIRM__", "'" + esc(confirmKw) + "'");
                            browserWeb.evaluateJavascript(js, value -> {
                                boolean ok = value != null && value.contains("ok");
                                cbResult(cbId, ok ? "{\"ok\":true}"
                                        : "{\"ok\":false,\"error\":\"滚轮选择失败:" + esc(optKw) + "\"}");
                            });
                            break;
                        }
                        case "read_frames": {
                            browserWeb.evaluateJavascript(READ_FRAMES_JS, value -> {
                                String v = (value == null || value.equals("null")) ? "[]" : value;
                                cbResult(cbId, "{\"ok\":true,\"frames\":" + v + "}");
                            });
                            break;
                        }
                        default:
                            cbResult(cbId, "{\"ok\":true}");
                    }
                } catch (Exception e) {
                    Log.w(TAG, "executeCmd err", e);
                    cbResult(cbId, "{\"ok\":false,\"error\":\"" + esc(e.getMessage()) + "\"}");
                }
            });
        }

        /** 左侧栏「浏览器」：url='home' 回到起始页，否则加载 url，并切到浏览器。 */
        @JavascriptInterface
        public void showBrowser(String url) {
            runOnUiThread(() -> {
                try {
                    showBrowserView(url);
                } catch (Exception e) {
                    Log.w(TAG, "showBrowser err", e);
                }
            });
        }

        /** 返回聊天主界面。 */
        @JavascriptInterface
        public void showChat() {
            // 注意：lambda 里的 showChat() 会解析到本类（JsBridge.showChat）造成无限递归，
            // 必须显式调用外部类 MainActivity.this.showChat()。
            runOnUiThread(() -> {
                try {
                    MainActivity.this.showChat();
                } catch (Exception e) {
                    Log.w(TAG, "showChat err", e);
                }
            });
        }

        /** 保存验证码图片到手机 Download/相册（供用户看图输入图形码；不依赖 WebView 内嵌显示）。 */
        @JavascriptInterface
        public void saveCaptchaImage(String dataUri) {
            try {
                if (dataUri == null || dataUri.isEmpty()) return;
                String b64 = dataUri.contains(",") ? dataUri.substring(dataUri.indexOf(",") + 1) : dataUri;
                byte[] bytes = Base64.decode(b64, Base64.DEFAULT);
                java.io.File dir = new java.io.File("/sdcard/Download");
                if (!dir.exists()) dir.mkdirs();
                java.io.File f = new java.io.File(dir, "glyy_captcha.png");
                java.io.FileOutputStream fos = new java.io.FileOutputStream(f);
                fos.write(bytes);
                fos.close();
                // 通知相册刷新
                try {
                    Intent media = new Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE);
                    media.setData(Uri.fromFile(f));
                    sendBroadcast(media);
                } catch (Exception ignore) {}
            } catch (Exception e) {
                Log.w(TAG, "saveCaptchaImage err", e);
            }
        }

        /** 弹出软键盘（输入框聚焦时调用；用 SHOW_IMPLICIT，可被系统/空白点击自然收起）。 */
        @JavascriptInterface
        public void showKeyboard() {
            runOnUiThread(() -> {
                View target = getCurrentFocus();
                if (target == null) target = uiWeb;
                target.requestFocus();
                InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                if (imm != null) imm.showSoftInput(target, InputMethodManager.SHOW_IMPLICIT);
            });
        }

        /** 收起软键盘（点空白 / 收起按钮时调用）。 */
        @JavascriptInterface
        public void hideKeyboard() {
            runOnUiThread(() -> {
                View target = getCurrentFocus();
                InputMethodManager imm = (InputMethodManager) getSystemService(Context.INPUT_METHOD_SERVICE);
                if (imm != null && target != null) imm.hideSoftInputFromWindow(target.getWindowToken(), 0);
            });
        }

        /** 切到内置浏览器视图（不重载当前页）——聊天↔浏览器自由切换。 */
        @JavascriptInterface
        public void showBrowserCurrent() {
            runOnUiThread(() -> {
                uiWeb.setVisibility(View.GONE);
                browserContainer.setVisibility(View.VISIBLE);
                try { syncSoftInput(browserWeb); } catch (Exception e) {}
            });
        }

        /** 聊天窗口「＋」：打开系统文件选择器（图片/PDF），选中后回传 ui.html 上传云端。 */
        @JavascriptInterface
        public void chooseFile() {
            runOnUiThread(() -> {
                try {
                    Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                    intent.setType("*/*");
                    intent.putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"image/*", "application/pdf"});
                    intent.addCategory(Intent.CATEGORY_OPENABLE);
                    startActivityForResult(intent, CHAT_FILE_REQUEST);
                } catch (Exception e) {
                    Log.w(TAG, "chooseFile err", e);
                }
            });
        }

        /** 聊天窗口「📷」：打开相机拍照，拍完回传 ui.html 上传云端。 */
        @JavascriptInterface
        public void takePhoto() {
            runOnUiThread(() -> {
                try {
                    Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                    ContentValues values = new ContentValues();
                    values.put(MediaStore.Images.Media.DISPLAY_NAME, "xiami_" + System.currentTimeMillis() + ".jpg");
                    values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                    photoUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                    intent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
                    startActivityForResult(intent, PHOTO_REQUEST);
                } catch (Exception e) {
                    Log.w(TAG, "takePhoto err", e);
                }
            });
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        // 确保 cookies 写盘（登录态持久化）
        try {
            CookieManager.getInstance().flush();
        } catch (Exception ignore) {}
    }

    @Override
    public void onBackPressed() {
        if (browserContainer.getVisibility() == View.VISIBLE) {
            if (browserWeb.canGoBack()) {
                browserWeb.goBack();
            } else {
                uiWeb.setVisibility(View.VISIBLE);
                browserContainer.setVisibility(View.GONE);
            }
            return;
        }
        // 侧栏打开时：返回键优先收起侧栏（不退出 App）。直接查 DOM 真实状态，不依赖状态同步标记；
        // 侧栏开着 → closeSidebar() 并消费返回；侧栏关着 → 回调里再走默认退出。
        Log.d(TAG, "onBackPressed: query sidebar DOM");
        try {
            uiWeb.evaluateJavascript(
                "(function(){var s=document.getElementById('sidebar');" +
                "if(s&&s.classList.contains('open')){closeSidebar();return 'open';}return 'closed';})();",
                value -> {
                    Log.d(TAG, "onBackPressed: sidebar was " + value);
                    if (!"open".equals(value)) {
                        runOnUiThread(this::defaultFinish);
                    }
                });
        } catch (Exception e) {
            Log.d(TAG, "onBackPressed: evaluateJavascript err " + e);
            super.onBackPressed();
        }
    }

    /** onBackPressed 里异步确认侧栏未开后，再走系统默认返回（退出）。 */
    private void defaultFinish() {
        super.onBackPressed();
    }
}
