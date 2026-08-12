package com.xiami.host;

import android.content.Context;
import android.content.SharedPreferences;

import java.util.Locale;
import java.util.Map;

/**
 * 手机本地凭据库（Device-as-Proxy 第 4 条）。
 *
 * 第三方登录态（glyy Bearer token / tuniu cookies+sessionId / apiKey）
 * 只存用户手机本地，云端不聚合、不持有。
 *
 * 多账号隔离：所有 key 挂在「当前云端账号 email」下：
 *   token_&lt;email&gt;_&lt;skill&gt; / cookie_&lt;email&gt;_&lt;skill&gt; / …
 * 未登录（无 active email）时读写为空，避免串号。
 * 兼容：首次切到某账号时，若新 key 为空则懒迁移旧的设备级 key（无 email 维度）。
 */
public class CredentialStore {
    private static final String PREFS = "xiami_creds";
    private static final String ACTIVE_EMAIL = "_active_email";
    private final SharedPreferences sp;

    public CredentialStore(Context ctx) {
        this.sp = ctx.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** 切换当前云端账号；email 空字符串表示未登录。 */
    public void setActiveAccount(String email) {
        String em = normEmail(email);
        sp.edit().putString(ACTIVE_EMAIL, em).apply();
        if (!em.isEmpty()) migrateLegacyFor(em);
    }

    public String getActiveAccount() {
        return normEmail(sp.getString(ACTIVE_EMAIL, ""));
    }

    private static String normEmail(String email) {
        return email == null ? "" : email.trim().toLowerCase(Locale.ROOT);
    }

    private String account() {
        return getActiveAccount();
    }

    /** kind_email_skill，无账号时返回空串（调用方应当不存在）。 */
    private String key(String kind, String skill) {
        String em = account();
        if (em.isEmpty()) return "";
        return kind + "_" + em + "_" + (skill == null ? "" : skill);
    }

    private String legacyKey(String kind, String skill) {
        return kind + "_" + (skill == null ? "" : skill);
    }

    private String getString(String kind, String skill) {
        String k = key(kind, skill);
        if (k.isEmpty()) return "";
        String v = sp.getString(k, "");
        if (v != null && !v.isEmpty()) return v;
        // 懒迁移：旧设备级 key → 当前账号
        String legacy = sp.getString(legacyKey(kind, skill), "");
        if (legacy != null && !legacy.isEmpty()) {
            sp.edit().putString(k, legacy).remove(legacyKey(kind, skill)).apply();
            return legacy;
        }
        return "";
    }

    private void putString(String kind, String skill, String value) {
        String k = key(kind, skill);
        if (k.isEmpty()) return;
        sp.edit().putString(k, value == null ? "" : value).apply();
    }

    private long getLong(String kind, String skill) {
        String k = key(kind, skill);
        if (k.isEmpty()) return 0L;
        long v = sp.getLong(k, 0L);
        if (v != 0L) return v;
        String lk = legacyKey(kind, skill);
        if (sp.contains(lk)) {
            long legacy = sp.getLong(lk, 0L);
            sp.edit().putLong(k, legacy).remove(lk).apply();
            return legacy;
        }
        return 0L;
    }

    private void putLong(String kind, String skill, long value) {
        String k = key(kind, skill);
        if (k.isEmpty()) return;
        sp.edit().putLong(k, value).apply();
    }

    /** 账号首次激活：把仍残留的设备级 key 迁到该账号（仅目标为空时）。 */
    private void migrateLegacyFor(String em) {
        SharedPreferences.Editor ed = sp.edit();
        boolean dirty = false;
        Map<String, ?> all = sp.getAll();
        for (Map.Entry<String, ?> e : all.entrySet()) {
            String k = e.getKey();
            if (k == null || k.startsWith("_")) continue;
            // 已是账号维度：kind_email_…（email 含 @）
            if (k.contains("@")) continue;
            String newKey = null;
            if ("api_key_tuniu".equals(k)) {
                newKey = "api_key_" + em + "_tuniu";
            } else if (k.startsWith("token_") || k.startsWith("refresh_")
                    || k.startsWith("expires_") || k.startsWith("cookie_")
                    || k.startsWith("session_")) {
                // token_glyy → token_<em>_glyy
                int i = k.indexOf('_');
                if (i > 0 && i + 1 < k.length()) {
                    String kind = k.substring(0, i);
                    String skill = k.substring(i + 1);
                    newKey = kind + "_" + em + "_" + skill;
                }
            }
            if (newKey == null) continue;
            if (all.containsKey(newKey)) {
                Object existing = all.get(newKey);
                if (existing instanceof String && !((String) existing).isEmpty()) {
                    ed.remove(k);
                    dirty = true;
                    continue;
                }
                if (existing instanceof Long && ((Long) existing) != 0L) {
                    ed.remove(k);
                    dirty = true;
                    continue;
                }
            }
            Object val = e.getValue();
            if (val instanceof String) ed.putString(newKey, (String) val);
            else if (val instanceof Long) ed.putLong(newKey, (Long) val);
            else continue;
            ed.remove(k);
            dirty = true;
        }
        if (dirty) ed.apply();
    }

    // glyy：Bearer token
    public String getToken(String skill) {
        return getString("token", skill);
    }

    public void setToken(String skill, String token) {
        putString("token", skill, token);
    }

    // glyy refresh_token（自动续期用）
    public String getRefreshToken(String skill) {
        return getString("refresh", skill);
    }

    public void setRefreshToken(String skill, String v) {
        putString("refresh", skill, v);
    }

    // glyy access_token 过期时间戳（毫秒；0 = 未知）
    public long getTokenExpiresAt(String skill) {
        return getLong("expires", skill);
    }

    public void setTokenExpiresAt(String skill, long v) {
        putLong("expires", skill, v);
    }

    // tuniu 开放平台 apiKey（按账号隔离）
    public String getApiKey() {
        String em = account();
        if (em.isEmpty()) return "";
        String k = "api_key_" + em + "_tuniu";
        String v = sp.getString(k, "");
        if (v != null && !v.isEmpty()) return v;
        String legacy = sp.getString("api_key_tuniu", "");
        if (legacy != null && !legacy.isEmpty()) {
            sp.edit().putString(k, legacy).remove("api_key_tuniu").apply();
            return legacy;
        }
        return "";
    }

    public void setApiKey(String key) {
        String em = account();
        if (em.isEmpty()) return;
        sp.edit().putString("api_key_" + em + "_tuniu", key == null ? "" : key).apply();
    }

    // 网页/小程序 cookies（"k=v; k2=v2"）
    public String getCookie(String skill) {
        return getString("cookie", skill);
    }

    public void setCookie(String skill, String cookie) {
        putString("cookie", skill, cookie);
    }

    // 途牛小程序 sessionId
    public String getSessionId(String skill) {
        return getString("session", skill);
    }

    public void setSessionId(String skill, String sessionId) {
        putString("session", skill, sessionId);
    }

    /** 清除当前账号下某 skill 的全部平台凭据。 */
    public void clearSkill(String skill) {
        String em = account();
        if (em.isEmpty() || skill == null || skill.isEmpty()) return;
        SharedPreferences.Editor ed = sp.edit();
        ed.putString("token_" + em + "_" + skill, "");
        ed.putString("refresh_" + em + "_" + skill, "");
        ed.putLong("expires_" + em + "_" + skill, 0L);
        ed.putString("cookie_" + em + "_" + skill, "");
        ed.putString("session_" + em + "_" + skill, "");
        if ("tuniu".equals(skill)) {
            ed.putString("api_key_" + em + "_tuniu", "");
        }
        ed.apply();
    }
}
