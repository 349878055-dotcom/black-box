package com.xiami.host;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.SecureRandom;
import java.security.cert.X509Certificate;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.UUID;

import javax.net.ssl.HostnameVerifier;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSession;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * 手机端通用登录设施（方案②：手机端全权处理登录，云端 AI 不碰）。
 *
 * 内置「短信验证码登录」状态机（begin → captcha → sms → login），
 * 按 skill 下发的 login 配置（signal + steps 接口模板 + credential 字段）执行。
 *
 * 使用方式（SkillExecutor 检测到登录信号时调用）：
 *   LoginCoordinator coord = new LoginCoordinator(ctx, loginConfig, interactor);
 *   boolean ok = coord.run();   // 同步阻塞完成登录，成功存凭据
 *
 * 交互：LoginCoordinator 不直接弹 UI，通过 Interactor 回调让宿主（MainActivity）呈现：
 *   - askText(title)      → 让用户输入文字（手机号 / 短信验证码）
 *   - showImageAndAsk(b64, title) → 显示验证码图 + 让用户输入
 * 宿主在聊天里推送输入框 / 图片，返回用户输入。
 *
 * 凭据：登录成功按 login.credential 字段写入 CredentialStore（如 tuniu sessionId）。
 */
public class LoginCoordinator {

    /** 宿主交互接口（由 MainActivity 实现：聊天里推送输入框/图片，等用户输入）。 */
    public interface Interactor {
        /** 弹出文字输入（手机号/短信码），返回用户输入（可能为空）。 */
        String askText(String title);

        /** 显示 base64 图片（验证码图）并要求用户输入文字，返回输入。 */
        String showImageAndAsk(String base64, String title);
    }

    private final CredentialStore creds;
    private final JSONObject loginCfg;   // skill 下发的 login 配置
    private final Interactor interactor;
    private final String skill;

    public LoginCoordinator(Context ctx, String skill, JSONObject loginCfg, Interactor interactor) {
        this.creds = new CredentialStore(ctx);
        this.skill = skill == null ? "" : skill;
        this.loginCfg = loginCfg == null ? new JSONObject() : loginCfg;
        this.interactor = interactor;
    }

    /**
     * 执行 sms_verify 登录状态机。成功返回 true（凭据已存），失败 false。
     * 阻塞调用（内部与用户交互），必须在子线程执行。
     */
    public boolean run() {
        try {
            String method = loginCfg.optString("method", "");
            if (!"sms_verify".equals(method)) {
                android.util.Log.w("LoginCoordinator", "不支持的登录方式: " + method);
                return false;
            }
            JSONObject steps = loginCfg.optJSONObject("steps");
            if (steps == null) return false;
            String credential = loginCfg.optString("credential", "");
            JSONObject interact = loginCfg.optJSONObject("interact");

            // ── 0. begin：创建 sessionId（可选）──
            String sessionId = "";
            JSONObject begin = steps.optJSONObject("begin");
            if (begin != null) {
                JSONObject r0 = doStep(begin, new HashMap<String, String>());
                sessionId = pick(r0, field(begin, "save", "sessionId"));
                android.util.Log.i("LoginCoordinator", "begin sessionId=" + sessionId
                        + " raw=" + (r0.toString().length() > 200 ? r0.toString().substring(0, 200) : r0.toString()));
            }

            // ── 1. captcha：图形验证码（need 判定）──
            JSONObject captcha = steps.optJSONObject("captcha");
            String capToken = "";
            boolean need = true;
            if (captcha != null) {
                String phone = askPhone(interact);
                if (phone.isEmpty()) return false;
                Map<String, String> vars = new HashMap<>();
                vars.put("phone", phone);
                JSONObject r1 = doStep(captcha, vars);
                String imgField = captcha.optString("image_field", "data.imageBase64");
                String img = pick(r1, imgField);
                capToken = pick(r1, captcha.optString("token_field", "data.token"));
                String needStr = pick(r1, captcha.optString("need_field", "data.need"));
                need = "true".equalsIgnoreCase(needStr) || "1".equals(needStr);
                android.util.Log.i("LoginCoordinator", "captcha need=" + need
                        + " imgLen=" + img.length() + " capToken=" + capToken
                        + " raw=" + (r1.toString().length() > 250 ? r1.toString().substring(0, 250) : r1.toString()));
                // 会话变量
                String capPrompt = prompt(interact, "captcha_image", "请输入图形验证码");
                if (need && !img.isEmpty()) {
                    String code = interactor.showImageAndAsk(img, capPrompt);
                    if (code == null || code.trim().isEmpty()) return false;
                    vars.put("captcha_code", code.trim());
                    vars.put("captcha_token", capToken);
                } else {
                    vars.put("captcha_code", "");
                    vars.put("captcha_token", "");
                }
                vars.put("need", need ? "true" : "false");
                vars.put("sessionId", sessionId);

                // ── 2. send_sms：发短信 → verifyToken ──
                JSONObject sms = steps.optJSONObject("send_sms");
                if (sms != null) {
                    JSONObject r2 = doStep(sms, vars);
                    String vt = pick(r2, sms.optString("return_verify_token", "data.token"));
                    vars.put("verify_token", vt);
                    boolean sendOk = r2.optBoolean("sendSuccess", false);
                    if (vt.isEmpty()) {
                        // 发短信失败（如图形码错 50018 / 未登录）→ 中断，提示用户重试
                        String emsg = pick(r2, "msg");
                        if (emsg.isEmpty()) emsg = r2.optString("msg", "发送短信失败");
                        android.util.Log.w("LoginCoordinator", "发短信失败: " + emsg
                                + " raw=" + (r2.toString().length() > 200 ? r2.toString().substring(0, 200) : r2.toString()));
                        interactor.askText("❌ " + emsg + "（请稍后重新下单，会重新登录）");
                        return false;
                    }
                    android.util.Log.i("LoginCoordinator", "send_sms verify_token=" + vt
                            + " sendSuccess=" + sendOk
                            + " raw=" + (r2.toString().length() > 250 ? r2.toString().substring(0, 250) : r2.toString()));

                    // ── 3. login：手机号+短信码 → 登录 → 存凭据 ──
                    JSONObject login = steps.optJSONObject("login");
                    if (login != null) {
                        String smsPrompt = prompt(interact, "sms_code", "请输入短信验证码");
                        String smsCode = interactor.askText(smsPrompt);
                        if (smsCode == null || smsCode.trim().isEmpty()) return false;
                        vars.put("sms_code", smsCode.trim());
                        vars.put("sessionId", sessionId);
                        JSONObject r3 = doStep(login, vars);
                        String okField = login.optString("login_ok_field", "data.login");
                        boolean ok = r3.optBoolean(okField, false);
                        // 成功 → 取登录后 sessionId 存凭据
                        String newSid = pick(r3, field(login, "save", credential));
                        if (!newSid.isEmpty()) sessionId = newSid;
                        if (ok && !sessionId.isEmpty()) {
                            creds.setSessionId(skill, sessionId);
                            android.util.Log.i("LoginCoordinator", "登录成功，sessionId 已存: " + skill);
                            return true;
                        }
                        android.util.Log.w("LoginCoordinator", "登录未成功: " + r3.toString());
                        return false;
                    }
                }
            }
            return false;
        } catch (Exception e) {
            android.util.Log.w("LoginCoordinator", "登录异常: " + e.getMessage(), e);
            return false;
        }
    }

    // ─────────── 交互 ───────────
    private String askPhone(JSONObject interact) {
        String title = prompt(interact, "phone", "请输入手机号");
        String phone = interactor.askText(title);
        return phone == null ? "" : phone.trim();
    }

    private String prompt(JSONObject interact, String key, String def) {
        if (interact == null) return def;
        String v = interact.optString(key, "");
        return v.isEmpty() ? def : v;
    }

    // ─────────── 执行单步（按 login.steps 模板，含占位符/公共参数 c/数据传递）───────────
    private JSONObject doStep(JSONObject step, Map<String, String> vars) throws Exception {
        String method = step.optString("method", "GET");
        String url = step.optString("url", "");
        // 占位符替换 URL 中的 {xxx}
        url = fill(url, vars);
        Map<String, String> headers = new HashMap<>();
        headers.put("User-Agent", LoginUtils.USER_AGENT);
        headers.put("Referer", LoginUtils.REFERER);
        headers.put("Content-Type", "application/json");

        // 附加 headers（含占位符）
        JSONObject h = step.optJSONObject("headers");
        if (h != null) {
            Iterator<String> it = h.keys();
            while (it.hasNext()) {
                String k = it.next();
                headers.put(k, fill(h.optString(k, ""), vars));
            }
        }

        // 公共参数 c（途牛登录：query_c=true 时附加）
        String finalUrl = url;
        if (step.optBoolean("query_c", false)) {
            String c = LoginUtils.commonC();
            finalUrl += (finalUrl.contains("?") ? "&" : "?") + "c=" + java.net.URLEncoder.encode(c, "UTF-8");
        }
        // query_d（GET 业务参数，含占位符）
        JSONObject qd = step.optJSONObject("query_d");
        if (qd != null) {
            String d = fill(qd.toString(), vars);
            finalUrl += (finalUrl.contains("?") ? "&" : "?") + "d=" + java.net.URLEncoder.encode(d, "UTF-8");
        }
        // query（begin 用：parameters JSON）
        JSONObject query = step.optJSONObject("query");
        if (query != null) {
            String q = fill(query.toString(), vars);
            finalUrl += (finalUrl.contains("?") ? "&" : "?") + "parameters=" + java.net.URLEncoder.encode(q, "UTF-8");
        }

        // body（POST）
        String bodyStr = null;
        JSONObject body = step.optJSONObject("body");
        if (body != null) {
            bodyStr = fill(body.toString(), vars);
        }

        android.util.Log.i("LoginCoordinator", "[step] " + method + " " + finalUrl
                + (bodyStr != null ? " body=" + bodyStr : ""));
        // 直连
        HttpURLConnection conn = null;
        try {
            URL u = new URL(finalUrl);
            conn = (HttpURLConnection) u.openConnection();
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
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (OutputStream os = conn.getOutputStream()) {
                    os.write(bodyStr.getBytes("UTF-8"));
                }
            }
            int code = conn.getResponseCode();
            InputStream is = (code >= 400) ? conn.getErrorStream() : conn.getInputStream();
            String resp = readAll(is);
            android.util.Log.i("LoginCoordinator", "[resp] http=" + code + " body="
                    + (resp.length() > 300 ? resp.substring(0, 300) : resp));
            return new JSONObject(resp.isEmpty() ? "{}" : resp);
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    // ─────────── 工具 ───────────
    private String fill(String s, Map<String, String> vars) {
        if (s == null || !s.contains("{")) return s;
        for (Map.Entry<String, String> e : vars.entrySet()) {
            s = s.replace("{" + e.getKey() + "}", e.getValue() == null ? "" : e.getValue());
        }
        // 通用生成占位符
        s = s.replace("{uuid}", UUID.randomUUID().toString());
        s = s.replace("{device15}", device15());
        return s;
    }

    /** 生成 15 位数字 deviceId（时间戳末位 + 随机补足）。 */
    private String device15() {
        String ts = String.valueOf(System.currentTimeMillis());
        String base = ts.length() > 15 ? ts.substring(ts.length() - 15) : ts;
        StringBuilder sb = new StringBuilder(base);
        java.util.Random r = new java.util.Random();
        while (sb.length() < 15) sb.append(r.nextInt(10));
        return sb.toString();
    }

    private String field(JSONObject o, String key, String def) {
        return o == null ? def : (o.optString(key, def));
    }

    /** 点分路径取值，如 "data.sessionId" / "data.login" / "imageBase64"。 */
    private String pick(JSONObject obj, String path) {
        if (obj == null || path == null || path.isEmpty()) return "";
        String[] parts = path.split("\\.");
        Object cur = obj;
        for (int i = 0; i < parts.length; i++) {
            if (!(cur instanceof JSONObject)) return "";
            JSONObject o = (JSONObject) cur;
            if (i == parts.length - 1) {
                Object v = o.opt(parts[i]);
                return v == null ? "" : String.valueOf(v);
            }
            cur = o.opt(parts[i]);
        }
        return "";
    }

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

    /** 登录公共常量/工具（UA/Referer/公共参数 c）。 */
    static final class LoginUtils {
        static final String USER_AGENT =
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            + "Chrome/126.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) "
            + "NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) "
            + "UnifiedPCLinuxWechat(0xf2741104) XWEB/14910";
        static final String REFERER = "https://servicewechat.com/wx340329c7ee375a33/523/page-frame.html";

        static String commonC() {
            String deviceNo = "tn-31-" + System.currentTimeMillis() + "-" + randomHex(24);
            return "{\"cc\":\"2500\",\"p\":34505,\"ct\":31,\"dt\":0,\"v\":\"10.70.0\","
                + "\"ov\":\"\",\"deviceNo\":\"" + deviceNo + "\"}";
        }

        static String randomHex(int n) {
            StringBuilder sb = new StringBuilder();
            String hex = "0123456789abcdef";
            java.util.Random r = new java.util.Random();
            for (int i = 0; i < n; i++) sb.append(hex.charAt(r.nextInt(16)));
            return sb.toString();
        }
    }
}
