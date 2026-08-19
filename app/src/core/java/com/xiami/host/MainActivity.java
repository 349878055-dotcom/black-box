package com.xiami.host;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

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
 * 虾米办 · 手机宿主（功能入口；界面在 src/ui/）。
 *
 * 功能：
 *  1) uiWeb     — 加载 ui/assets/ui.html：登录、聊天、连云端 WS
 *  2) browser   — 内置浏览器：仅用于真人登录（打开登录页 + 导出登录态）
 *  3) Bridge    — AndroidBridge：skill 执行、凭据读写、支付跳系统浏览器
 *
 * 界面文件：src/ui/assets/ui.html（脚本在上，样式与 HTML 在下）
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
    private static final int PHOTO_PICK_REQUEST = 1004;  // 资料卡证件照选择
    private Uri photoUri = null;                          // 聊天拍照输出 Uri
    private String pendingPhotoCbId = null;              // 证件照回调 id
    private String pendingPhotoCard = "";                // 属于哪张资料卡
    private String pendingPhotoField = "";               // 属于哪个字段
    private Uri pendingPhotoUri = null;                  // 证件照拍照输出
    private JsBridge jsBridge = null;                    // 保存引用（授权后重试拍照）

    // navigate 真加载：挂一次性回调，onPageFinished 后再回执
    private String pendingNavCbId = null;
    private Runnable navTimeoutRunnable = null;
    private static final long NAV_DEFAULT_TIMEOUT_MS = 45000;
    // 浏览器默认 UA（navigate 切微信 UA 后据此恢复；老站需微信 UA）
    private String webViewDefaultUA = "";

    // ── 浏览器执行 JS（navigate 落地确认）──

    /** 仅查 document.readyState（navigate 落地后二次确认）。 */
    static final String READY_STATE_JS = "(function(){return document.readyState||'';})()";

    /** check_ready 用：读取页面文本 / 表单数 / 就绪状态（登录页落地确认）。 */
    static final String READ_JS = """
        (function(){
          var body = document.body ? document.body.innerText : '';
          var forms = [];
          var nodes = document.querySelectorAll('input,textarea,select');
          for (var i=0;i<nodes.length && i<800;i++){
            var e = nodes[i];
            var isEditable = e.getAttribute('contenteditable')==='true';
            var tag = e.tagName.toLowerCase();
            if (tag==='input'||tag==='textarea'||tag==='select'||isEditable){
              forms.push({tag:isEditable?'contenteditable':tag,type:e.getAttribute('type')||tag});
            }
          }
          return {page_text:(body||'').slice(0,100000), forms: forms, readyState: document.readyState, url: location.href};
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

    @SuppressWarnings("deprecation")
    private WebView makeUiWeb() {
        // WebView 远程调试（chrome://inspect）：仅 debug 包开启，release 必须关闭（防调试注入）
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        WebView w = new WebView(this);
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        // 展示厅用 srcdoc 注入；这两项给 file:// 兜底读取 assets
        s.setAllowFileAccessFromFileURLs(true);
        s.setAllowUniversalAccessFromFileURLs(true);
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
        jsBridge = new JsBridge();
        w.addJavascriptInterface(jsBridge, "AndroidBridge");
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
        w.setOnTouchListener((v, ev) -> {
            if (ev.getAction() == android.view.MotionEvent.ACTION_UP) {
                v.requestFocus();
                syncSoftInput(w);
            }
            return false;
        });
        WebSettings s = w.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        // 移动 H5（登录页）视口/弹层需要
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        // 记录系统默认 UA，供 navigate 切回（老站用微信 UA，其他站点恢复默认）
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
                // 拦截系统协议跳转（sms:/tel:/intent:/wxp 等）：避免 WebView 崩溃报
                // ERR_UNKNOWN_URL_SCHEME（登录页可能调 sms:/tel: 等系统协议）。
                // 验证码实际通过真实短信送达，这里直接吞掉跳转，页面保持正常。
                if (url != null && (url.startsWith("sms:") || url.startsWith("tel:")
                        || url.startsWith("intent:") || url.startsWith("weixin://"))) {
                    return true;
                }
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
                // 其余 URL（含 https 支付收银台）留在 WebView 内加载
                return super.shouldOverrideUrlLoading(view, url);
            }
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
                String url = request != null ? request.getUrl().toString() : null;
                if (url != null && (url.startsWith("sms:") || url.startsWith("tel:")
                        || url.startsWith("intent:") || url.startsWith("weixin://"))) {
                    return true;
                }
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
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                super.onPageStarted(view, url, favicon);
                // 注意：onPageStarted 注入 JS（mock 定位/webdriver）会干扰 H5 首页接口（"网络不给力"），
                // 故不再自动注入。mock 定位改用页面内 eval 按需注入（按需注入）。
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
                // 仅对内置浏览器已知需要放行的场景（过期证书、主机名不匹配）允许继续；
                // 其他 SSL 错误（如不受信任的根证书）拒绝，防止中间人攻击。
                if (error != null) {
                    int pe = error.getPrimaryError();
                    if (pe == SslError.SSL_DATE_INVALID || pe == SslError.SSL_IDMISMATCH
                            || pe == SslError.SSL_EXPIRED) {
                        try { handler.proceed(); return; } catch (Exception ignore) {}
                    }
                }
                try { handler.cancel(); } catch (Exception ignore) {}
            }
            @Override
            public void onReceivedError(WebView view, android.webkit.WebResourceRequest request,
                                        android.webkit.WebResourceError error) {
                super.onReceivedError(view, request, error);
                // 主文档加载失败（DNS/断网/ERR_*）→ 立刻回执 navigate 失败，不再静默等 45s 超时
                // 还误报成功；被重定向/取消（ERR_ABORTED=-3）不是真实失败，跳过。
                if (request != null && request.isForMainFrame() && error != null
                        && error.getErrorCode() != -3 /* ERR_ABORTED */) {
                    String desc = error.getDescription() == null
                            ? "网络错误" : error.getDescription().toString();
                    failPendingNavigate("页面加载失败(" + error.getErrorCode() + "): " + desc);
                }
            }
            @Override
            public void onReceivedHttpError(WebView view, android.webkit.WebResourceRequest request,
                                            android.webkit.WebResourceResponse errorResponse) {
                super.onReceivedHttpError(view, request, errorResponse);
                // 主文档返回 4xx/5xx（被云防护 504、403 等）→ 同样立刻回执失败，
                // 云端收到后自动重试 / 引导手动打开。
                if (request != null && request.isForMainFrame() && errorResponse != null) {
                    failPendingNavigate("HTTP " + errorResponse.getStatusCode() + " 加载失败");
                }
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
        // ⚠️ 安全红线：browserWeb 会加载第三方登录页/任意外部站点，
        // 绝不给它注入完整原生桥（executeSkill/openExternal/凭据读写/文件/相机等），
        // 防止外部网站页面滥用手机能力（发请求/开链接/读凭据）。
        // 只暴露最小导航桥：起始页 browser_home.html 的「返回聊天」按钮需要 AndroidBridge.showChat()。
        // 登录原语（navigate/export_token/export_cookies/check_ready）由 ui.html 经 executeCmd 驱动，
        // 第三方页面不需要、也不允许直接调原生能力。
        w.addJavascriptInterface(new Object() {
            @JavascriptInterface
            public void showChat() {
                runOnUiThread(() -> MainActivity.this.showChat());
            }
        }, "AndroidBridge");
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
        if (requestCode == PHOTO_PICK_REQUEST) {
            if (resultCode == RESULT_OK) {
                Uri src = pendingPhotoUri;
                if (src == null && data != null && data.getData() != null) src = data.getData();
                String path = saveToSandbox(src);
                pendingPhotoUri = null;
                final String cb = pendingPhotoCbId;
                pendingPhotoCbId = null; pendingPhotoCard = ""; pendingPhotoField = "";
                if (cb != null) {
                    final String p = path;
                    runOnUiThread(() -> {
                        try { uiWeb.evaluateJavascript("window.__photoResult && window.__photoResult("
                                + JSONObject.quote(cb) + "," + JSONObject.quote(p) + ");", null); } catch (Exception ignore) {}
                    });
                }
            } else {
                pendingPhotoUri = null; pendingPhotoCbId = null; pendingPhotoCard = ""; pendingPhotoField = "";
            }
            return;
        }
        super.onActivityResult(requestCode, resultCode, data);
    }

    /** 把图片复制到 App 内部沙盒（持久，重启仍可读），返回 file:// 路径。 */
    private String saveToSandbox(Uri src) {
        if (src == null) return "";
        try {
            java.io.File dir = new java.io.File(getFilesDir(), "photos");
            if (!dir.exists()) dir.mkdirs();
            java.io.File f = new java.io.File(dir, "photo_" + System.currentTimeMillis() + ".jpg");
            InputStream is = getContentResolver().openInputStream(src);
            if (is == null) return "";
            try (java.io.FileOutputStream fos = new java.io.FileOutputStream(f)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = is.read(buf)) != -1) fos.write(buf, 0, n);
            } finally {
                try { is.close(); } catch (Exception ignore) {}
            }
            return Uri.fromFile(f).toString();
        } catch (Exception e) {
            return "";
        }
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == 9001 && grantResults.length > 0
                && grantResults[0] == android.content.pm.PackageManager.PERMISSION_GRANTED
                && jsBridge != null && pendingPhotoCbId != null) {
            runOnUiThread(() -> jsBridge.retryCamera());
        }
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

    /** 写文本到系统 Download/Xiami 目录（Android 10+ MediaStore，兼容 scoped storage）。 */
    void writeToDownload(String name, String content) {
        try {
            if (android.os.Build.VERSION.SDK_INT >= 29) {
                ContentValues cv = new ContentValues();
                cv.put(MediaStore.Downloads.DISPLAY_NAME, name);
                cv.put(MediaStore.Downloads.MIME_TYPE, "text/plain");
                cv.put(MediaStore.Downloads.RELATIVE_PATH, "Download/Xiami");
                Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                if (uri != null) {
                    try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                        if (os != null) { os.write(content.getBytes("UTF-8")); os.flush(); }
                    }
                }
            } else {
                java.io.File dir = new java.io.File("/sdcard/Download/Xiami");
                if (!dir.exists()) dir.mkdirs();
                java.io.File f = new java.io.File(dir, name);
                try (java.io.FileOutputStream fos = new java.io.FileOutputStream(f)) {
                    fos.write(content.getBytes("UTF-8"));
                }
            }
        } catch (Exception ignore) {}
    }

    /** 按域名清空 CookieManager（登录前清残留，防站点重定向回首页）。 */
    void clearCookiesForDomain(String domainUrl) {
        CookieManager cm = CookieManager.getInstance();
        java.util.LinkedHashSet<String> urls = new java.util.LinkedHashSet<>();
        urls.add(domainUrl);
        try {
            java.net.URI u = new java.net.URI(domainUrl);
            String host = u.getHost();
            if (host != null && !host.isEmpty()) {
                urls.add("https://" + host);
                urls.add("http://" + host);
                urls.add("https://" + host + "/");
                urls.add("http://" + host + "/");
                if (host.startsWith("www.")) {
                    String bare = host.substring(4);
                    urls.add("https://" + bare);
                    urls.add("https://m." + bare);
                } else {
                    urls.add("https://www." + host);
                    urls.add("https://m." + host);
                }
            }
        } catch (Exception ignore) {}
        for (String url : urls) {
            String cookies = cm.getCookie(url);
            if (cookies == null || cookies.isEmpty()) continue;
            String[] parts = cookies.split(";");
            for (String part : parts) {
                String name = part.trim().split("=", 2)[0].trim();
                if (name.isEmpty()) continue;
                cm.setCookie(url, name + "=; Max-Age=0; Path=/");
                cm.setCookie(url, name + "=; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/");
            }
        }
        cm.flush();
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

    /** 主文档加载失败（网络/HTTP 错误）→ 立刻回执 pending navigate 为失败，
     *  避免静默等 45s 超时还误报成功（否则云端以为页面已打开）。 */
    void failPendingNavigate(String reason) {
        final String cbId = pendingNavCbId;
        if (cbId == null) return;
        pendingNavCbId = null;
        if (navTimeoutRunnable != null) {
            h.removeCallbacks(navTimeoutRunnable);
            navTimeoutRunnable = null;
        }
        cbResult(cbId, "{\"ok\":false,\"error\":\"" + esc(reason) + "\"}");
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
        /** 读 assets 文本（展示厅页面）。只允许相对路径，禁止 .. */
        @JavascriptInterface
        public String readAsset(String path) {
            if (path == null || path.isEmpty() || path.contains("..") || path.startsWith("/")) return "";
            try (InputStream in = getAssets().open(path);
                 ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buf = new byte[4096];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                return out.toString("UTF-8");
            } catch (Exception e) {
                Log.w(TAG, "readAsset " + path, e);
                return "";
            }
        }

        /** 第 6 条：执行 skill 请求蓝图（手机直连平台）→ 回调 ui.html __skillResult 回传 skill_result。
         *  App 内置固定引擎（红线 A：只执行 JSON 配置，绝不下发/执行代码）。 */
        @JavascriptInterface
        public void executeSkill(String reqId, String blueprintJson) {
            new Thread(() -> {
                final String rid = reqId == null ? "" : reqId;
                try {
                    SkillExecutor ex = new SkillExecutor(MainActivity.this);
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

        /** 切换当前云端账号：凭据库按 email 隔离读写。登录/恢复会话时由 ui.html 调用。 */
        @JavascriptInterface
        public void setActiveAccount(String email) {
            try {
                new CredentialStore(MainActivity.this).setActiveAccount(email);
            } catch (Exception ignore) {}
        }

        /** 第 4 条：个人资料（就诊人/乘车人）同步到本机凭据库（只存本机，按邮箱隔离）。
         *  skill 请求时可按 {{字段}} 占位符填入（姓名/手机号/证件号等），云端不聚合。 */
        @JavascriptInterface
        public void saveProfile(String profileJson) {
            try {
                new CredentialStore(MainActivity.this).saveProfile(profileJson);
            } catch (Exception ignore) {}
        }

        /** 授权中心：按本机已存凭据自动出卡片（登录一个平台就多一张；凭据只在本机）。
         *  不认识平台：只回 skill id + 凭据 kind；展示名/分类由前端用云端契约补。 */
        @JavascriptInterface
        public String getCredentials() {
            try {
                CredentialStore cs = new CredentialStore(MainActivity.this);
                org.json.JSONObject out = new org.json.JSONObject();
                for (String[] row : cs.listAuthorized()) {
                    String skill = row[0];
                    String kind = row[1];
                    org.json.JSONObject o = new org.json.JSONObject();
                    o.put("kind", kind == null ? "" : kind);
                    o.put("authorized", true);
                    out.put(skill, o);
                }
                return out.toString();
            } catch (Exception e) { return "{}"; }
        }

        /** 授权中心：清除当前账号下指定平台登录态。 */
        @JavascriptInterface
        public void clearCredential(String skill) {
            try {
                new CredentialStore(MainActivity.this).clearSkill(skill);
            } catch (Exception ignore) {}
        }

        @JavascriptInterface
        public void executeCmd(String cmd, String paramsJson, String cbId) {
            runOnUiThread(() -> {
                try {
                    JSONObject p = new JSONObject(paramsJson == null ? "{}" : paramsJson);
                    String c = cmd == null ? "" : cmd;
                    switch (c) {
                        case "clear_cookies": {
                            // 按域名清 CookieManager 残留（登录前必清，否则登录页被重定向回首页）
                            String domain = p.optString("domain", "");
                            if (domain.isEmpty()) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"domain empty\"}");
                                break;
                            }
                            try {
                                clearCookiesForDomain(domain);
                                cbResult(cbId, "{\"ok\":true,\"domain\":\"" + esc(domain) + "\"}");
                            } catch (Exception e) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"clear_cookies err\"}");
                            }
                            break;
                        }
                        case "export_cookies": {
                            // 导出当前网页登录态 cookies（用户自己的账号，用于后续请求保持登录）
                            String domain = p.optString("domain", "");
                            // 第 4 条：登录态存手机本地凭据库（skill 由云端传入，App 不设默认）
                            String skill = p.optString("skill", "");
                            if (domain.isEmpty() || skill.isEmpty()) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"domain/skill empty\"}");
                                break;
                            }
                            try {
                                String cookies = CookieManager.getInstance().getCookie(domain);
                                try {
                                    new CredentialStore(MainActivity.this).setCookie(skill, String.valueOf(cookies));
                                } catch (Exception ignore) {}
                                // 同步写一份到系统 Download 目录（供电脑 adb pull 读取/调试）
                                writeToDownload(skill + "_cookies.txt",
                                        domain + "\n" + String.valueOf(cookies));
                                cbResult(cbId, "{\"ok\":true,\"domain\":\"" + esc(domain)
                                        + "\",\"skill\":\"" + esc(skill)
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
                            // 支持自定义 Referer（老站被云防护 504，需带特定 Referer 才能过防护）
                            String referer = p.optString("referer", "");
                            if (!referer.isEmpty()) {
                                hdrs.put("Referer", referer);
                            }
                            // 老站必需微信 UA（否则服务器挂起/403）；ua=wechat 时切换，
                            // 非 wechat 一律恢复默认系统 UA（避免残留微信 UA 影响其他站点）
                            String ua = p.optString("ua", "");
                            if ("wechat".equals(ua)) {
                                browserWeb.getSettings().setUserAgentString(
                                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                        + "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
                                        + "MicroMessenger/8.0.38(0x18002623) NetType/WIFI Language/zh_CN");
                            } else if ("browser".equals(ua) || "default".equals(ua)) {
                                // 真手机浏览器 UA（去掉 WebView 的 "; wv" 标志）：
                                // 部分站检测到 "; wv" 会识别为非标准浏览器，拒绝提交订单等高风险操作。
                                browserWeb.getSettings().setUserAgentString(
                                        "Mozilla/5.0 (Linux; Android 10; CLT-AL00 Build/HUAWEICLT-AL00) "
                                        + "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 "
                                        + "Mobile Safari/537.36");
                            } else {
                                browserWeb.getSettings().setUserAgentString(webViewDefaultUA);
                            }
                            browserWeb.loadUrl(url, hdrs);
                            break;
                        }
                        case "export_token": {
                            // 导出当前网页登录态 token（Bearer token）→ 存手机凭据库 CredentialStore。
                            // 先扫 localStorage 常见 token key；没有再回退 CookieManager 里找 token 字段。
                            String skill = p.optString("skill", "");
                            final String domain = p.optString("domain", "");
                            if (skill.isEmpty()) {
                                cbResult(cbId, "{\"ok\":false,\"error\":\"skill empty\"}");
                                break;
                            }
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
                                        // 兜底2：cookie 里找 token 字段（登录态可能放 cookie）
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
                                            writeToDownload(skill + "_token.txt",
                                                    domain + "\n" + tk);
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
                        default:
                            // 未知命令必须失败，禁止假成功（曾导致 clear_cookies 等「报 ok 实际没做」）
                            cbResult(cbId, "{\"ok\":false,\"error\":\"unknown cmd:" + esc(c) + "\"}");
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

        /** 保存验证码图片到手机「下载」目录（聊天内已显示验证码，这里另存一份供放大/去文件管理查看）。
         *  Android 10+（API 29）：用 MediaStore 写入系统下载目录 Download/Xiami，免权限、scoped storage 兼容；
         *  老版本（API <29）：本 App 未声明写外部存储权限，直写 /sdcard/Download 会失败，故跳过（聊天内显示已够用）。 */
        @JavascriptInterface
        public void saveCaptchaImage(String dataUri) {
            try {
                if (dataUri == null || dataUri.isEmpty()) return;
                String b64 = dataUri.contains(",") ? dataUri.substring(dataUri.indexOf(",") + 1) : dataUri;
                byte[] bytes = Base64.decode(b64, Base64.DEFAULT);
                String name = "captcha_" + System.currentTimeMillis() + ".png";
                if (android.os.Build.VERSION.SDK_INT >= 29) {
                    ContentValues cv = new ContentValues();
                    cv.put(MediaStore.Images.Media.DISPLAY_NAME, name);
                    cv.put(MediaStore.Images.Media.MIME_TYPE, "image/png");
                    cv.put(MediaStore.Images.Media.RELATIVE_PATH, "Download/Xiami");
                    Uri uri = getContentResolver().insert(
                            MediaStore.Downloads.EXTERNAL_CONTENT_URI, cv);
                    if (uri != null) {
                        try (OutputStream os = getContentResolver().openOutputStream(uri)) {
                            if (os != null) { os.write(bytes); os.flush(); }
                        }
                    }
                }
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

        /** 资料卡证件照：拍照 / 相册选 → 复制到 App 沙盒 → 回调 ui.html 存资料卡（skill 按 uri 上传）。 */
        @JavascriptInterface
        public void pickPhoto(String cardId, String field, String cbId) {
            runOnUiThread(() -> {
                pendingPhotoCbId = cbId;
                pendingPhotoCard = cardId == null ? "" : cardId;
                pendingPhotoField = field == null ? "" : field;
                new android.app.AlertDialog.Builder(MainActivity.this)
                        .setTitle("选择证件照")
                        .setItems(new String[]{"拍照", "从相册选择"}, (d, which) -> {
                            if (which == 0) launchCamera();
                            else launchGallery();
                        })
                        .setNegativeButton("取消", null)
                        .show();
            });
        }

        private void launchCamera() {
            try {
                if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(android.Manifest.permission.CAMERA)
                        != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                    requestPermissions(new String[]{android.Manifest.permission.CAMERA}, 9001);
                    return;
                }
                ContentValues values = new ContentValues();
                values.put(MediaStore.Images.Media.DISPLAY_NAME, "xiami_photo_" + System.currentTimeMillis() + ".jpg");
                values.put(MediaStore.Images.Media.MIME_TYPE, "image/jpeg");
                pendingPhotoUri = getContentResolver().insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values);
                Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                intent.putExtra(MediaStore.EXTRA_OUTPUT, pendingPhotoUri);
                startActivityForResult(intent, PHOTO_PICK_REQUEST);
            } catch (Exception e) { cancelPhotoPick(); }
        }

        private void launchGallery() {
            try {
                Intent intent = new Intent(Intent.ACTION_GET_CONTENT);
                intent.setType("image/*");
                intent.addCategory(Intent.CATEGORY_OPENABLE);
                startActivityForResult(intent, PHOTO_PICK_REQUEST);
            } catch (Exception e) { cancelPhotoPick(); }
        }

        private void cancelPhotoPick() {
            pendingPhotoUri = null; pendingPhotoCbId = null; pendingPhotoCard = ""; pendingPhotoField = "";
        }

        /** CAMERA 授权后重试拍照（onRequestPermissionsResult 调用）。 */
        public void retryCamera() {
            runOnUiThread(() -> launchCamera());
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
