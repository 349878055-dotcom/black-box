package com.xiami.host;

import android.content.Context;

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
import java.util.Random;

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
 *   {{token}} glyy Bearer token / {{api_key}} 途牛开放平台 key
 *   {{cookie}} 途牛 cookies / {{session_id}} 途牛小程序会话
 *
 * sign_type：
 *   "glyy_sha1_md5" → sign = SHA1( MD5(appKey + timestamp + nonce) )
 *   "none" → 不签名
 */
public class SkillExecutor {
    private final CredentialStore creds;
    private final Context ctx;
    // 登录交互宿主（MainActivity 注入；null 则禁用自动登录，保持旧行为）
    private LoginCoordinator.Interactor loginInteractor = null;

    public SkillExecutor(Context ctx) {
        this.ctx = ctx;
        this.creds = new CredentialStore(ctx);
    }

    /** 注入登录交互宿主（聊天推送输入框/图片）。未注入则不自动登录。 */
    public void setLoginInteractor(LoginCoordinator.Interactor interactor) {
        this.loginInteractor = interactor;
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
            String signType = req.optString("sign_type", "none");
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
            // cookie 凭据：自动补 Cookie 头（途牛网页版）
            String cookieStr = creds.getCookie(skill);
            if (cookieStr != null && !cookieStr.isEmpty() && !headers.containsKey("Cookie")) {
                headers.put("Cookie", cookieStr);
            }

            // 2) 占位符替换（含签名，timestamp/nonce 全蓝图统一一份）
            long ts = System.currentTimeMillis();
            String nonce = randomNonce();
            String appKey = headers.get("appKey");
            replaceHeaderPlaceholders(headers, skill, ts, nonce, signType, appKey);

            // 登录态检查：bearer 蓝图但本机无 token → 直接返回「需要登录」，不发请求
            String auth = headers.get("Authorization");
            if (auth != null && auth.startsWith("Bearer ")
                    && auth.substring(7).trim().isEmpty()) {
                return fail("缺少登录态（token），请先登录鼓楼医院");
            }
            // 自动续期：需要登录的请求，token 快过期 → 用 refresh_token 静默换新（官方 PUT /session?refresh_token=）
            if (bp.optBoolean("auto_refresh", false)) {
                String auth2 = headers.get("Authorization");
                if (auth2 != null && auth2.startsWith("Bearer ")
                        && !auth2.substring(7).trim().isEmpty()) {
                    autoRefreshIfNeeded(skill, headers);
                }
            }

            // 3) body（JSON）→ 占位符替换（如 session_id）；body_type=form 时转表单编码
            String bodyStr = null;
            boolean formBody = "form".equalsIgnoreCase(req.optString("body_type", ""));
            JSONObject bodyObj = req.optJSONObject("body");
            if (bodyObj != null) {
                String s = replaceBodyPlaceholders(bodyObj.toString(), skill, ts, nonce,
                        signType, appKey);
                bodyStr = formBody ? toFormBody(s) : s;
            }

            // 4) 直连平台（手机真实 IP）—— glyy 老站时好时坏，连接失败自动重试（最多 3 次）
            int code = 0;
            String respBody = "";
            java.io.IOException lastIo = null;
            for (int attempt = 1; attempt <= 3; attempt++) {
                try {
                    URL u = new URL(url);
                    conn = (HttpURLConnection) u.openConnection();
                    // 平台老站多为自签名证书（glyy:9532），与云端 verify=False 对齐：信任所有证书
                    if (conn instanceof HttpsURLConnection) {
                        HttpsURLConnection https = (HttpsURLConnection) conn;
                        https.setSSLSocketFactory(trustAllSslFactory());
                        https.setHostnameVerifier(new HostnameVerifier() {
                            public boolean verify(String hostname, SSLSession session) { return true; }
                        });
                    }
                    conn.setRequestMethod(method);
                    conn.setConnectTimeout(15000);
                    conn.setReadTimeout(40000);
                    conn.setInstanceFollowRedirects(true);
                    for (Map.Entry<String, String> e : headers.entrySet()) {
                        if (e.getValue() != null && !e.getValue().isEmpty()) {
                            conn.setRequestProperty(e.getKey(), e.getValue());
                        }
                    }
                    if (bodyStr != null) {
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
                    if (attempt < 3) {
                        try { Thread.sleep(1200L * attempt); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); break; }
                    }
                }
            }
            if (lastIo != null) {
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
            out.put("body", respBody);
            out.put("error", "");
            return out.toString();
        } catch (Exception e) {
            return fail(e.getMessage() == null ? e.toString() : e.getMessage());
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    // ─────────── 占位符 / 签名 ───────────
    private void replaceHeaderPlaceholders(Map<String, String> headers, String skill,
                                           long ts, String nonce, String signType, String appKey) {
        String tsStr = String.valueOf(ts);
        String sign = computeSign(signType, appKey, tsStr, nonce);
        for (Map.Entry<String, String> e : headers.entrySet()) {
            String v = e.getValue();
            if (v == null || !v.contains("{{")) continue;
            v = v.replace("{{timestamp}}", tsStr)
                 .replace("{{nonce}}", nonce)
                 .replace("{{sign}}", sign == null ? "" : sign);
            String t = creds.getToken(skill);
            v = v.replace("{{token}}", t == null ? "" : t);
            String ak = creds.getApiKey();
            v = v.replace("{{api_key}}", ak == null ? "" : ak);
            e.setValue(v);
        }
    }

    private String replaceBodyPlaceholders(String s, String skill, long ts, String nonce,
                                           String signType, String appKey) {
        if (!s.contains("{{")) return s;
        String tsStr = String.valueOf(ts);
        String sign = computeSign(signType, appKey, tsStr, nonce);
        s = s.replace("{{timestamp}}", tsStr).replace("{{nonce}}", nonce)
             .replace("{{sign}}", sign == null ? "" : sign);
        String sid = creds.getSessionId(skill);
        s = s.replace("{{session_id}}", sid == null ? "" : sid);
        return s;
    }

    /** body_type=form：把 JSON 对象转表单编码（k=urlencode(v)&...），供途牛 M 站等 form 接口用。 */
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

    /** 按 sign_type 计算签名；未知类型返回 null。 */
    private String computeSign(String signType, String appKey, String ts, String nonce) {
        try {
            if ("glyy_sha1_md5".equals(signType) && appKey != null && !appKey.isEmpty()) {
                return sha1(md5(appKey + ts + nonce));
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

    /** 信任所有证书的 SSLContext（对齐云端 verify=False，测试/老站必须；上线可收敛为指定 CA）。 */
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

    private String readAll(InputStream is) throws Exception {
        if (is == null) return "";
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = is.read(buf)) != -1) bos.write(buf, 0, n);
        return bos.toString("UTF-8");
    }

    private String md5(String s) throws Exception {
        return hex(java.security.MessageDigest.getInstance("MD5").digest(s.getBytes("UTF-8")));
    }

    private String sha1(String s) throws Exception {
        return hex(java.security.MessageDigest.getInstance("SHA-1").digest(s.getBytes("UTF-8")));
    }

    private String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x));
        return sb.toString();
    }

    private String randomNonce() {
        String chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
        StringBuilder sb = new StringBuilder();
        Random r = new Random();
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

    /** token 快过期（剩 <5 分钟或未知）→ 用 refresh_token 静默换新，并更新当前请求 Authorization。 */
    private void autoRefreshIfNeeded(String skill, Map<String, String> headers) {
        try {
            String refresh = creds.getRefreshToken(skill);
            if (refresh == null || refresh.isEmpty()) return;
            long expiresAt = creds.getTokenExpiresAt(skill);
            if (expiresAt > 0 && System.currentTimeMillis() < expiresAt - 5 * 60 * 1000L) return; // 未快过期
            // 官方刷新接口：PUT /v4/session?refresh_token=xxx（签名头同登录，对齐契约「PUT /session?refresh_token=」）
            String base = "https://www.ih.njglyy.com:9532/caring/api";
            String url = base + "/v4/session?refresh_token=" + java.net.URLEncoder.encode(refresh, "UTF-8");
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            if (c instanceof HttpsURLConnection) {
                HttpsURLConnection h = (HttpsURLConnection) c;
                h.setSSLSocketFactory(trustAllSslFactory());
                h.setHostnameVerifier(new HostnameVerifier() {
                    public boolean verify(String host, SSLSession s) { return true; }
                });
            }
            long ts = System.currentTimeMillis();
            String nonce = randomNonce();
            String appKey = "1340patient";
            String sign = sha1(md5(appKey + ts + nonce));
            c.setRequestMethod("PUT");
            c.setRequestProperty("User-Agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.38(0x18002623) NetType/WIFI Language/zh_CN");
            c.setRequestProperty("appKey", appKey);
            c.setRequestProperty("role", "patient");
            c.setRequestProperty("tenant", "1340");
            c.setRequestProperty("timestamp", String.valueOf(ts));
            c.setRequestProperty("nonce", nonce);
            c.setRequestProperty("sign", sign);
            c.setConnectTimeout(20000);
            c.setReadTimeout(40000);
            int code = c.getResponseCode();
            InputStream is = (code >= 400) ? c.getErrorStream() : c.getInputStream();
            String resp = readAll(is);
            JSONObject j = new JSONObject(resp);
            JSONObject data = j.optJSONObject("data");
            if (j.optInt("code", -1) == 0 && data != null) {
                String nt = data.optString("access_token", "");
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
