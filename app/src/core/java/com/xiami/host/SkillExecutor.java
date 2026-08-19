package com.xiami.host;

import android.content.Context;
import android.net.Uri;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.util.HashMap;
import java.util.Iterator;
import java.util.List;
import java.util.Map;


/**
 * 手机端 skill 执行引擎（Device-as-Proxy 第 6 条）。
 *
 * 收「请求蓝图」skill_request → 本地凭据库填 token/cookies → 手机真实 IP 直连平台 →
 * 回 skill_result 原始响应。
 * App 内置固定引擎（红线 A：只执行 JSON 配置，绝不下发/执行可执行代码）。
 *
 * 底层用 HttpURLConnection（JDK 自带，零第三方依赖，离线可构建）。
 *
 * 蓝图占位符（由本引擎本地替换）：
 *   {{timestamp}} 毫秒时间戳 / {{nonce}} 32位随机 / {{sign}} 按 sign_type 计算
 *   {{token}} 登录 Bearer token / {{api_key}} 开放平台 key
 *   {{cookie}} 网页 cookies / {{session_id}} 小程序会话
 *
 * sign_type（由 skill 蓝图声明，App 只按名实现通用算法，不绑定任何平台）：
 *   "sha1_md5" → sign = SHA1( MD5(appKey + timestamp + nonce) )
 *   "none" → 不签名
 */
public class SkillExecutor {
    private final CredentialStore creds;
    private final Context ctx;
    public SkillExecutor(Context ctx) {
        this.ctx = ctx;
        this.creds = new CredentialStore(ctx);
    }

    /** 执行蓝图，返回 skill_result JSON 字符串：{ok,status,headers,body,error}。 */
    public String execute(String blueprintJson) {
        HttpURLConnection conn = null;
        try {
            JSONObject bp = new JSONObject(blueprintJson == null ? "{}" : blueprintJson);
            JSONObject req = bp.optJSONObject("request");
            if (req == null) return fail("蓝图缺少 request");

            String method = req.optString("method", "GET").toUpperCase();
            String url = req.optString("url", "");
            if (url.isEmpty()) return fail("蓝图缺少 url");
            String skill = bp.optString("skill", "");

            // 1) 蓝图 headers → 落地 headers（含占位符）
            Map<String, String> headers = new HashMap<>();
            JSONObject h = req.optJSONObject("headers");
            if (h != null) {
                Iterator<String> it = h.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    headers.put(k, h.optString(k, ""));
                }
            }
            // cookie 凭据：自动补 Cookie 头（网页 cookie 登录）
            String cookieStr = creds.getCookie(skill);
            if (cookieStr != null && !cookieStr.isEmpty() && !headers.containsKey("Cookie")) {
                headers.put("Cookie", cookieStr);
            }

            // 2) 占位符替换（含签名：sign_type + sign_content 由 skill 声明，App 只算哈希）
            long ts = System.currentTimeMillis();
            String nonce = randomNonce();
            replaceHeaderPlaceholders(bp, headers, skill, ts, nonce);
            // url 也支持占位符（{{token}}/{{timestamp}}/{{sign}}/{{cookie}} 等），与 headers 同源替换
            url = replaceUrlPlaceholders(bp, url, skill, ts, nonce);

            // 登录态检查：bearer 蓝图但本机无 token → 直接返回「需要登录」，不发请求
            String auth = headers.get("Authorization");
            if (auth != null && auth.startsWith("Bearer ")
                    && auth.substring(7).trim().isEmpty()) {
                return fail("缺少登录态（token），请先登录该平台");
            }
            // 自动续期：需要登录的请求，token 快过期 → 按蓝图 refresh 配置静默换新（配置由 skill 下发，App 只执行）
            if (bp.optBoolean("auto_refresh", false)) {
                String auth2 = headers.get("Authorization");
                if (auth2 != null && auth2.startsWith("Bearer ")
                        && !auth2.substring(7).trim().isEmpty()) {
                    autoRefreshIfNeeded(skill, bp, headers);
                }
            }

            // 3) body（JSON）→ 占位符替换；body_type=form 转表单编码、multipart 转多部分上传
            String bodyStr = null;
            boolean formBody = "form".equalsIgnoreCase(req.optString("body_type", ""));
            boolean multipartBody = "multipart".equalsIgnoreCase(req.optString("body_type", ""));
            JSONObject bodyObj = req.optJSONObject("body");
            if (bodyObj != null) {
                String s = replaceBodyPlaceholders(bodyObj.toString(), bp, skill, ts, nonce);
                if (multipartBody) {
                    bodyObj = new JSONObject(s);   // 字段占位符替换后再解析
                } else {
                    bodyStr = formBody ? toFormBody(s) : s;
                }
            }

            // 4) 直连平台（手机真实 IP）—— 老站时好时坏，连接失败自动重试。
            //    仅幂等方法（GET/HEAD/DELETE/OPTIONS）自动重试：重试不会重复执行；
            //    POST/PUT/PATCH 提交类绝不自动重试（避免网络抖动导致重复挂号/下单），失败直接回执云端。
            int code = 0;
            String respBody = "";
            java.io.IOException lastIo = null;
            boolean idempotent = "GET".equals(method) || "HEAD".equals(method)
                    || "DELETE".equals(method) || "OPTIONS".equals(method);
            int maxAttempts = idempotent ? 3 : 1;
            for (int attempt = 1; attempt <= maxAttempts; attempt++) {
                try {
                    URL u = new URL(url);
                    conn = (HttpURLConnection) u.openConnection();
                    // 默认校验证书；仅蓝图 request.insecure_tls=true 时才关校验（自签名老站）
                    applyTls(conn, req.optBoolean("insecure_tls", false));
                    conn.setRequestMethod(method);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(40000);
                    conn.setInstanceFollowRedirects(true);
                    for (Map.Entry<String, String> e : headers.entrySet()) {
                        if (e.getValue() != null && !e.getValue().isEmpty()) {
                            conn.setRequestProperty(e.getKey(), e.getValue());
                        }
                    }
                    if (multipartBody && bodyObj != null) {
                        // multipart/form-data 文件上传：fields 普通字段 + files 本地文件
                        conn.setDoOutput(true);
                        String boundary = "----XiamiBoundary" + System.currentTimeMillis();
                        conn.setRequestProperty("Content-Type", "multipart/form-data; boundary=" + boundary);
                        byte[] mp = buildMultipart(bodyObj, boundary);
                        try (OutputStream os = conn.getOutputStream()) { os.write(mp); }
                    } else if (bodyStr != null) {
                        conn.setDoOutput(true);
                        conn.setRequestProperty("Content-Type", formBody
                                ? "application/x-www-form-urlencoded; charset=utf-8"
                                : "application/json; charset=utf-8");
                        try (OutputStream os = conn.getOutputStream()) {
                            os.write(bodyStr.getBytes("UTF-8"));
                        }
                    }
                    code = conn.getResponseCode();
                    InputStream is = (code >= 400) ? conn.getErrorStream() : conn.getInputStream();
                    respBody = readAll(is);
                    lastIo = null;
                    break;   // 成功
                } catch (java.io.IOException e) {
                    lastIo = e;
                    if (conn != null) { try { conn.disconnect(); } catch (Exception ignore) {} conn = null; }
                    if (attempt < maxAttempts) {
                        try { Thread.sleep(1200L * attempt); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
                    }
                }
            }
            if (lastIo != null) {
                writeExecLog(skill, method, url, 0, lastIo.getMessage() == null ? lastIo.toString() : lastIo.getMessage());
                return fail(lastIo.getMessage() == null ? lastIo.toString() : lastIo.getMessage());
            }

            // 第 4 条：store 回写 —— 登录成功 → token/cookies/sessionId/refresh_token 存手机本地凭据库
            JSONObject store = bp.optJSONObject("store");
            if (store != null && code >= 200 && code < 300) {
                try {
                    JSONObject body = new JSONObject(respBody);
                    String target = store.optString("target", skill);
                    saveCred(store.optString("kind", ""), target,
                             readField(body, store.optString("field", "")));
                    org.json.JSONArray extra = store.optJSONArray("extra");
                    if (extra != null) {
                        for (int i = 0; i < extra.length(); i++) {
                            JSONObject e = extra.optJSONObject(i);
                            if (e == null) continue;
                            saveCred(e.optString("kind", ""), target,
                                     readField(body, e.optString("field", "")));
                        }
                    }
                } catch (Exception ignore) {}
            }

            // ── 登录信号检测（不再自动登录，改为引导客户自己打开浏览器登录）──
            // 客户在浏览器手动登录后，登录态存手机（导出凭据），后续请求自动补凭据。
            JSONObject loginCfg = bp.optJSONObject("login");
            if (loginCfg != null && matchesLoginSignal(respBody, loginCfg)) {
                android.util.Log.i("SkillExecutor", "检测到登录信号，需要登录 skill=" + skill);
                return fail("需要登录，请在浏览器打开登录页登录后重试");
            }

            JSONObject out = new JSONObject();
            out.put("req_id", bp.optString("req_id", ""));
            out.put("ok", code >= 200 && code < 300);
            out.put("status", code);
            JSONObject rh = new JSONObject();
            for (Map.Entry<String, List<String>> hd : conn.getHeaderFields().entrySet()) {
                String k = hd.getKey();
                if (k == null || hd.getValue() == null || hd.getValue().isEmpty()) continue;
                if (!rh.has(k)) rh.put(k, hd.getValue().get(0));
            }
            out.put("headers", rh);
            // 响应裁剪：云端在蓝图 response 里指定只回传部分字段 / 截断，避免全量回传过重
            String outBody = respBody;
            JSONObject respCfg = bp.optJSONObject("response");
            if (respCfg != null && !respBody.isEmpty()) {
                int maxSize = respCfg.optInt("max_size", 0);
                if (maxSize > 0 && outBody.length() > maxSize) {
                    outBody = outBody.substring(0, maxSize);
                    out.put("truncated", true);
                }
                org.json.JSONArray pick = respCfg.optJSONArray("pick");
                if (pick != null && pick.length() > 0) {
                    try {
                        JSONObject full = new JSONObject(outBody);
                        JSONObject slim = new JSONObject();
                        for (int i = 0; i < pick.length(); i++) {
                            String p = pick.optString(i, "");
                            if (p.isEmpty()) continue;
                            Object v = readPath(full, p);
                            if (v != null) slim.put(p, v);
                        }
                        outBody = slim.toString();
                        out.put("picked", true);
                    } catch (Exception ignore) {}
                }
            }
            out.put("body", outBody);
            out.put("error", "");
            // 网络诊断：非 2xx 留痕（脱敏：只记状态码 + 响应前 200 字符，不记完整 body/凭据）
            if (!(code >= 200 && code < 300)) {
                writeExecLog(skill, method, url, code,
                        "HTTP " + code + " body前200=" + (respBody.length() > 200 ? respBody.substring(0, 200) : respBody));
            }
            return out.toString();
        } catch (Exception e) {
            return fail(e.getMessage() == null ? e.toString() : e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    // ─────────── 占位符 / 签名（通用哈希库，不绑平台）───────────
    private void replaceHeaderPlaceholders(JSONObject bp, Map<String, String> headers,
                                           String skill, long ts, String nonce) {
        JSONObject req = bp.optJSONObject("request");
        String signType = req == null ? "none" : req.optString("sign_type", "none");
        String signContent = req == null ? "" : req.optString("sign_content", "");
        String signKey = req == null ? "" : req.optString("sign_key", "");
        String tsStr = String.valueOf(ts);
        // {{deviceid}} 设备指纹：部分平台风控必填，用 Android 真机唯一 ID
        String deviceId = android.provider.Settings.Secure.getString(
                ctx.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        if (deviceId == null || deviceId.isEmpty()) deviceId = "0";
        String appKey = headers.get("appKey");
        String sign = computeSignFor(signType, signContent, signKey, tsStr, nonce, appKey);
        for (Map.Entry<String, String> e : headers.entrySet()) {
            String v = e.getValue();
            if (v == null || !v.contains("{{")) continue;
            e.setValue(fillVars(v, tsStr, nonce, sign, skill, deviceId, appKey, bp));
        }
    }

    private String replaceBodyPlaceholders(String s, JSONObject bp, String skill,
                                           long ts, String nonce) {
        if (!s.contains("{{")) return s;
        JSONObject req = bp.optJSONObject("request");
        String signType = req == null ? "none" : req.optString("sign_type", "none");
        String signContent = req == null ? "" : req.optString("sign_content", "");
        String signKey = req == null ? "" : req.optString("sign_key", "");
        String tsStr = String.valueOf(ts);
        JSONObject hdrs = req == null ? null : req.optJSONObject("headers");
        String appKey = hdrs == null ? null : hdrs.optString("appKey", "");
        String sign = computeSignFor(signType, signContent, signKey, tsStr, nonce, appKey);
        String deviceId = android.provider.Settings.Secure.getString(
                ctx.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        if (deviceId == null || deviceId.isEmpty()) deviceId = "0";
        return fillVars(s, tsStr, nonce, sign, skill, deviceId, appKey, bp);
    }

    /** url 占位符替换（{{token}}/{{timestamp}}/{{nonce}}/{{sign}}/{{cookie}}/{{deviceid}} 等）。 */
    private String replaceUrlPlaceholders(JSONObject bp, String url, String skill,
                                          long ts, String nonce) {
        if (url == null || !url.contains("{{")) return url;
        JSONObject req = bp.optJSONObject("request");
        String signType = req == null ? "none" : req.optString("sign_type", "none");
        String signContent = req == null ? "" : req.optString("sign_content", "");
        String signKey = req == null ? "" : req.optString("sign_key", "");
        String tsStr = String.valueOf(ts);
        JSONObject hdrs = req == null ? null : req.optJSONObject("headers");
        String appKey = hdrs == null ? null : hdrs.optString("appKey", "");
        String sign = computeSignFor(signType, signContent, signKey, tsStr, nonce, appKey);
        String deviceId = android.provider.Settings.Secure.getString(
                ctx.getContentResolver(), android.provider.Settings.Secure.ANDROID_ID);
        if (deviceId == null || deviceId.isEmpty()) deviceId = "0";
        return fillVars(url, tsStr, nonce, sign, skill, deviceId, appKey, bp);
    }

    /** 统一占位符替换（sign 已算好传入）。 */
    private String fillVars(String tpl, String tsStr, String nonce, String sign,
                            String skill, String deviceId, String appKey, JSONObject bp) {
        String v = tpl;
        v = v.replace("{{timestamp}}", tsStr).replace("{{nonce}}", nonce)
             .replace("{{sign}}", sign == null ? "" : sign);
        if (appKey != null) v = v.replace("{{appKey}}", appKey);
        String t = creds.getToken(skill);
        v = v.replace("{{token}}", t == null ? "" : t);
        String ak = creds.getApiKey(skill);
        v = v.replace("{{api_key}}", ak == null ? "" : ak);
        String sid = creds.getSessionId(skill);
        v = v.replace("{{session_id}}", sid == null ? "" : sid);
        String ck = creds.getCookie(skill);
        v = v.replace("{{cookie}}", ck == null ? "" : ck);
        if (deviceId != null) v = v.replace("{{deviceid}}", deviceId);
        // 个人资料占位符（{{name}}/{{name_en}}/{{idnum}}/{{passport_no}}/{{address_en}}…）：
        // 按蓝图 profile_card 选卡，从本机资料库填（读不到为空，skill 可再问客户）
        v = fillProfileVars(v, bp);
        return v;
    }

    /** 个人资料占位符：{{<资料字段>}} → 指定资料卡的字段值（蓝图 profile_card 选卡，缺省主卡）。 */
    private String fillProfileVars(String v, JSONObject bp) {
        if (v == null || !v.contains("{{")) return v;
        String prof = creds.getProfile();
        if (prof == null || prof.isEmpty()) return v;
        try {
            JSONObject pr = new JSONObject(prof);
            JSONArray cards = pr.optJSONArray("cards");
            JSONObject card = null;
            String cardId = bp == null ? "" : bp.optString("profile_card", "");
            if (cards != null) {
                for (int i = 0; i < cards.length(); i++) {
                    JSONObject c = cards.optJSONObject(i);
                    if (c != null && cardId.equals(c.optString("id", ""))) { card = c; break; }
                }
                if (card == null && cards.length() > 0) card = cards.optJSONObject(0); // 主卡
            }
            if (card == null) card = pr; // 兼容旧单份格式（无 cards）
            Iterator<String> it = card.keys();
            while (it.hasNext()) {
                String k = it.next();
                Object val = card.opt(k);
                v = v.replace("{{" + k + "}}", val == null ? "" : String.valueOf(val));
            }
        } catch (Exception ignore) {}
        return v;
    }

    /** 按 skill 蓝图 sign 配置算签名：先把 sign_content 模板占位符替换为真实值，再按 sign_type 哈希。 */
    private String computeSignFor(String signType, String signContent, String signKey,
                                  String tsStr, String nonce, String appKey) {
        if (signType == null || signType.isEmpty() || "none".equals(signType)) return null;
        String key = (signKey != null && !signKey.isEmpty()) ? signKey : appKey;
        String content;
        if (signContent == null || signContent.isEmpty()) {
            // 兼容：skill 未给 sign_content 时，默认 appKey+ts+nonce（sha1_md5 原始拼接）
            content = (appKey == null ? "" : appKey) + tsStr + nonce;
        } else {
            content = signContent
                    .replace("{{timestamp}}", tsStr)
                    .replace("{{nonce}}", nonce)
                    .replace("{{appKey}}", appKey == null ? "" : appKey);
        }
        return computeSign(signType, content, key);
    }

    /** 网络诊断日志：直连平台失败/非 2xx 时留痕（脱敏，供云端排查 skill），存 App 内部 logs/exec.log。 */
    private void writeExecLog(String skill, String method, String url, int status, String error) {
        try {
            java.io.File dir = new java.io.File(ctx.getFilesDir(), "logs");
            if (!dir.exists()) dir.mkdirs();
            java.io.File f = new java.io.File(dir, "exec.log");
            String ts = new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm:ss", java.util.Locale.ROOT)
                    .format(new java.util.Date());
            String err = error == null ? "" : error;
            if (err.length() > 300) err = err.substring(0, 300);
            String line = ts + " | skill=" + skill + " " + method + " | status=" + status
                    + " | url=" + url + " | " + err + "\n";
            try (java.io.FileOutputStream fos = new java.io.FileOutputStream(f, true)) {
                fos.write(line.getBytes("UTF-8"));
            }
        } catch (Exception ignore) {}
    }

    /** body_type=multipart：构建 multipart/form-data（fields 普通字段 + files 本地文件）。 */
    private byte[] buildMultipart(JSONObject bodyObj, String boundary) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] B = "\r\n".getBytes("UTF-8");
        // 普通字段
        JSONObject fields = bodyObj.optJSONObject("fields");
        if (fields != null) {
            Iterator<String> it = fields.keys();
            while (it.hasNext()) {
                String k = it.next();
                String v = fields.optString(k, "");
                out.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
                out.write(("Content-Disposition: form-data; name=\"" + k + "\"\r\n\r\n").getBytes("UTF-8"));
                out.write(v.getBytes("UTF-8"));
                out.write(B);
            }
        }
        // 本地文件
        org.json.JSONArray files = bodyObj.optJSONArray("files");
        if (files != null) {
            for (int i = 0; i < files.length(); i++) {
                JSONObject f = files.optJSONObject(i);
                if (f == null) continue;
                String field = f.optString("field", "");
                String path = f.optString("path", "");
                if (field.isEmpty() || path.isEmpty()) continue;
                String filename = f.optString("filename", "");
                if (filename.isEmpty()) {
                    int slash = path.lastIndexOf('/');
                    filename = slash >= 0 ? path.substring(slash + 1) : path;
                }
                String contentType = f.optString("content_type", "application/octet-stream");
                byte[] data = readFileBytes(path);
                out.write(("--" + boundary + "\r\n").getBytes("UTF-8"));
                out.write(("Content-Disposition: form-data; name=\"" + field
                        + "\"; filename=\"" + filename + "\"\r\n").getBytes("UTF-8"));
                out.write(("Content-Type: " + contentType + "\r\n\r\n").getBytes("UTF-8"));
                out.write(data);
                out.write(B);
            }
        }
        out.write(("--" + boundary + "--\r\n").getBytes("UTF-8"));
        return out.toByteArray();
    }

    /** 读本地文件字节（支持 /绝对路径、file://、content://）。 */
    private byte[] readFileBytes(String path) throws Exception {
        InputStream is = null;
        try {
            if (path.startsWith("content://") || path.startsWith("file://")) {
                is = ctx.getContentResolver().openInputStream(Uri.parse(path));
            } else {
                is = new java.io.FileInputStream(path);
            }
            if (is == null) throw new java.io.FileNotFoundException("无法读取文件: " + path);
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = is.read(buf)) != -1) bos.write(buf, 0, n);
            return bos.toByteArray();
        } finally {
            if (is != null) try { is.close(); } catch (Exception ignore) {}
        }
    }

    /** body_type=form：把 JSON 对象转表单编码（k=urlencode(v)&...），供表单接口用。 */
    private String toFormBody(String jsonBody) {
        try {
            JSONObject o = new JSONObject(jsonBody);
            StringBuilder sb = new StringBuilder();
            Iterator<String> it = o.keys();
            while (it.hasNext()) {
                String k = it.next();
                Object v = o.opt(k);
                if (v == null) continue;
                if (sb.length() > 0) sb.append('&');
                sb.append(java.net.URLEncoder.encode(k, "UTF-8"))
                  .append('=').append(java.net.URLEncoder.encode(String.valueOf(v), "UTF-8"));
            }
            return sb.toString();
        } catch (Exception e) {
            return jsonBody;
        }
    }

    /** 通用哈希/HMAC 库：按 sign_type 对 content 求哈希（不绑任何平台）；未知类型返回 null。 */
    private String computeSign(String signType, String content, String key) {
        try {
            if (content == null) return null;
            switch (signType) {
                case "md5": return md5(content);
                case "sha1": return sha1(content);
                case "sha256": return sha256(content);
                case "sha1_md5": return sha1(md5(content));
                case "hmac_md5": return hmac("HmacMD5", key, content);
                case "hmac_sha1": return hmac("HmacSHA1", key, content);
                case "hmac_sha256": return hmac("HmacSHA256", key, content);
            }
        } catch (Exception ignore) {}
        return null;
    }

    /** 检测响应体是否命中登录信号（login.signal 里的任一词，如 "710114"/"未登录"）。 */
    private boolean matchesLoginSignal(String body, JSONObject loginCfg) {
        if (body == null || loginCfg == null) return false;
        String b = body;
        org.json.JSONArray signals = loginCfg.optJSONArray("signal");
        if (signals == null) return false;
        for (int i = 0; i < signals.length(); i++) {
            String s = signals.optString(i, "");
            if (!s.isEmpty() && b.contains(s)) return true;
        }
        return false;
    }

    /** 点分路径取值（如 data.access_token / data.list[0].id）；找不到返回 null。 */
    private Object readPath(JSONObject root, String path) {
        String[] parts = path.split("\\.");
        Object cur = root;
        for (String p : parts) {
            if (p == null || p.isEmpty() || !(cur instanceof JSONObject)) return null;
            cur = ((JSONObject) cur).opt(p);
        }
        return cur;
    }

    /** 点分路径读取（如 data.access_token）；找不到返回空串。 */
    private String readField(JSONObject obj, String field) {
        if (obj == null || field == null || field.isEmpty()) return "";
        String[] parts = field.split("\\.");
        JSONObject cur = obj;
        for (int i = 0; i < parts.length; i++) {
            if (i == parts.length - 1) return cur.optString(parts[i], "");
            JSONObject next = cur.optJSONObject(parts[i]);
            if (next == null) return "";
            cur = next;
        }
        return "";
    }

    /** 默认走系统证书校验；insecure=true 才信任全部（仅自签名老站蓝图声明）。 */
    private static void applyTls(HttpURLConnection conn, boolean insecure) {
        if (!insecure || !(conn instanceof HttpsURLConnection)) return;
        HttpsURLConnection https = (HttpsURLConnection) conn;
        javax.net.ssl.SSLSocketFactory f = trustAllSslFactory();
        if (f != null) https.setSSLSocketFactory(f);
        https.setHostnameVerifier(new HostnameVerifier() {
            public boolean verify(String hostname, SSLSession session) { return true; }
        });
    }

    /** 仅 insecure_tls 蓝图使用。 */
    private static javax.net.ssl.SSLSocketFactory trustAllSslFactory() {
        try {
            TrustManager[] trustAll = new TrustManager[]{ new X509TrustManager() {
                public X509Certificate[] getAcceptedIssuers() { return new X509Certificate[0]; }
                public void checkClientTrusted(X509Certificate[] chain, String authType) {}
                public void checkServerTrusted(X509Certificate[] chain, String authType) {}
            }};
            SSLContext sc = SSLContext.getInstance("TLS");
            sc.init(null, trustAll, new SecureRandom());
            return sc.getSocketFactory();
        } catch (Exception e) {
            return null;
        }
    }

    private static final int MAX_RESPONSE_BYTES = 10 * 1024 * 1024; // 10 MB
    private String readAll(InputStream is) throws Exception {
        if (is == null) return "";
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n, total = 0;
        while ((n = is.read(buf)) != -1) {
            total += n;
            if (total > MAX_RESPONSE_BYTES) {
                bos.write(buf, 0, n);
                break;
            }
            bos.write(buf, 0, n);
        }
        return bos.toString("UTF-8");
    }

    private String md5(String s) throws Exception {
        return hex(java.security.MessageDigest.getInstance("MD5").digest(s.getBytes("UTF-8")));
    }

    private String sha1(String s) throws Exception {
        return hex(java.security.MessageDigest.getInstance("SHA-1").digest(s.getBytes("UTF-8")));
    }

    private String sha256(String s) throws Exception {
        return hex(java.security.MessageDigest.getInstance("SHA-256").digest(s.getBytes("UTF-8")));
    }

    private String hmac(String algo, String key, String s) throws Exception {
        if (key == null || key.isEmpty()) return null;
        javax.crypto.Mac mac = javax.crypto.Mac.getInstance(algo);
        mac.init(new javax.crypto.spec.SecretKeySpec(key.getBytes("UTF-8"), algo));
        return hex(mac.doFinal(s.getBytes("UTF-8")));
    }

    private String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    private String randomNonce() {
        String chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        StringBuilder sb = new StringBuilder();
        SecureRandom r = new SecureRandom();
        for (int i = 0; i < 32; i++) sb.append(chars.charAt(r.nextInt(chars.length())));
        return sb.toString();
    }

    /** 按 kind 把值写入本地凭据库（token/refresh_token/cookie/session/expires_in）。 */
    private void saveCred(String kind, String target, String val) {
        if (val == null || val.isEmpty()) return;
        String k = kind == null ? "" : kind;
        try {
            switch (k) {
                case "token": creds.setToken(target, val); break;
                case "refresh_token": creds.setRefreshToken(target, val); break;
                case "cookie": creds.setCookie(target, val); break;
                case "session": creds.setSessionId(target, val); break;
                case "expires_in":
                case "expires_at": {
                    double sec = Double.parseDouble(val);
                    creds.setTokenExpiresAt(target, System.currentTimeMillis() + (long) (sec * 1000L));
                    break;
                }
            }
        } catch (Exception ignore) {}
    }

    /** token 快过期（剩 <5 分钟或未知）→ 按蓝图 refresh 配置静默换新（配置由 skill 下发，App 只执行）。 */
    private void autoRefreshIfNeeded(String skill, JSONObject bp, Map<String, String> headers) {
        // 续期接口配置随蓝图下发（skill 声明），App 不内置任何平台细节；无配置则不续期
        JSONObject rf = bp == null ? null : bp.optJSONObject("refresh");
        if (rf == null) return;
        try {
            String refresh = creds.getRefreshToken(skill);
            if (refresh == null || refresh.isEmpty()) return;
            long expiresAt = creds.getTokenExpiresAt(skill);
            if (expiresAt > 0 && System.currentTimeMillis() < expiresAt - 5 * 60 * 1000L) return; // 未快过期

            String encRefresh = java.net.URLEncoder.encode(refresh, "UTF-8");
            String method = rf.optString("method", "PUT");
            String url = rf.optString("url", "").replace("{{refresh_token}}", encRefresh);
            if (url.isEmpty()) return;
            String signType = rf.optString("sign_type", "none");
            String signContent = rf.optString("sign_content", "");
            String signKey = rf.optString("sign_key", "");

            // 请求头（含 {{timestamp}}/{{nonce}}/{{sign}}/{{refresh_token}} 占位符）
            Map<String, String> rh = new HashMap<>();
            JSONObject rho = rf.optJSONObject("headers");
            if (rho != null) {
                Iterator<String> it = rho.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    rh.put(k, rho.optString(k, ""));
                }
            }
            long ts = System.currentTimeMillis();
            String nonce = randomNonce();
            String appKey = rh.get("appKey");
            String sign = computeSignFor(signType, signContent, signKey,
                    String.valueOf(ts), nonce, appKey);
            for (Map.Entry<String, String> e : rh.entrySet()) {
                String v = e.getValue();
                if (v == null) continue;
                v = v.replace("{{timestamp}}", String.valueOf(ts))
                     .replace("{{nonce}}", nonce)
                     .replace("{{sign}}", sign == null ? "" : sign)
                     .replace("{{refresh_token}}", encRefresh);
                e.setValue(v);
            }

            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            JSONObject req0 = bp.optJSONObject("request");
            boolean insecure = (req0 != null && req0.optBoolean("insecure_tls", false))
                    || rf.optBoolean("insecure_tls", false);
            applyTls(c, insecure);
            c.setRequestMethod(method);
            for (Map.Entry<String, String> e : rh.entrySet()) {
                if (e.getKey() != null) c.setRequestProperty(e.getKey(), e.getValue());
            }
            c.setConnectTimeout(20000);
            c.setReadTimeout(40000);
            int code = c.getResponseCode();
            InputStream is = (code >= 400) ? c.getErrorStream() : c.getInputStream();
            String resp = readAll(is);
            JSONObject j = new JSONObject(resp);
            JSONObject data = j.optJSONObject("data");
            if (data != null) {
                // 通用解析：兼容 access_token / token 两种常见字段
                String nt = data.optString("access_token", "");
                if (nt.isEmpty()) nt = data.optString("token", "");
                if (!nt.isEmpty()) {
                    creds.setToken(skill, nt);
                    String nr = data.optString("refresh_token", "");
                    if (!nr.isEmpty()) creds.setRefreshToken(skill, nr);
                    long exp = data.optLong("expires_in", 0L);
                    if (exp > 0) creds.setTokenExpiresAt(skill, System.currentTimeMillis() + exp * 1000L);
                    headers.put("Authorization", "Bearer " + nt);
                    android.util.Log.i("SkillExecutor", "autoRefresh: token 已静默续期");
                }
            }
        } catch (Exception e) {
            android.util.Log.w("SkillExecutor", "autoRefresh err: " + e.getMessage());
        }
    }

    private String fail(String err) {
        try {
            JSONObject o = new JSONObject();
            o.put("ok", false);
            o.put("status", 0);
            o.put("headers", new JSONObject());
            o.put("body", "");
            o.put("error", err == null ? "手机执行失败" : err);
            return o.toString();
        } catch (Exception e) {
            return "{\"ok\":false,\"status\":0,\"headers\":{},\"body\":\"\",\"error\":\"手机执行失败\"}";
        }
    }
}
