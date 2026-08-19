package com.xiami.host;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.security.KeyStore;
import java.util.Arrays;
import javax.crypto.KeyGenerator;
import java.util.Locale;
import java.util.Map;

/**
 * 手机本地凭据库（Device-as-Proxy 第 4 条）。
 *
 * 第三方登录态（Bearer token / cookies+sessionId / apiKey）
 * 只存用户手机本地，云端不聚合、不持有。
 *
 * 多账号隔离：只认「当前云端账号 email」，一切数据挂在 email 维度下，key 形如：
 *   token_<email>_<skill> / cookie_<email>_<skill> / api_key_<email>_<skill> / …
 * 一个邮箱对应一套数据（授权、登录态、个人信息、收藏），互不串号。
 * 未登录（无 active email）时读写为空，绝不落到设备级公共 key。
 * 不兼容旧版本设备级 key（无 email 维度）、不做迁移——构造时按 schema 版本
 * 一次性丢弃旧版遗留 key（如 token_<skill>），不保留孤儿数据，只认邮箱。
 */
public class CredentialStore {
    private static final String PREFS = "xiami_creds";
    private static final String ACTIVE_EMAIL = "_active_email";
    // schema 版本：>=2 表示已清理旧版设备级 key（只保留 email 维度数据）
    private static final String SCHEMA_VER = "_schema_ver";
    private static final int SCHEMA_VER_CURRENT = 2;
    private final SharedPreferences sp;

    public CredentialStore(Context ctx) {
        this.sp = ctx.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        // 升级/重新初始化：首次进入先丢弃旧版无 email 维度的设备级 key，只认邮箱
        if (sp.getInt(SCHEMA_VER, 0) < SCHEMA_VER_CURRENT) {
            purgeLegacyKeys();
            sp.edit().putInt(SCHEMA_VER, SCHEMA_VER_CURRENT).apply();
        }
    }

    /** 丢弃旧版设备级 key（无 email 维度，如 token_<skill>），只保留系统键与账号维度 key。 */
    private void purgeLegacyKeys() {
        SharedPreferences.Editor ed = sp.edit();
        boolean dirty = false;
        for (Map.Entry<String, ?> e : sp.getAll().entrySet()) {
            String k = e.getKey();
            if (k == null) continue;
            if (k.startsWith("_")) continue;   // 系统键（_active_email / _schema_ver）
            if (k.contains("@")) continue;     // 账号维度 key（kind_<email>_…，email 含 @）
            ed.remove(k);                      // 其余 = 旧设备级 key，直接删除
            dirty = true;
        }
        if (dirty) ed.apply();
    }

    /** 切换当前云端账号；email 空字符串表示未登录。 */
    public void setActiveAccount(String email) {
        String em = normEmail(email);
        sp.edit().putString(ACTIVE_EMAIL, em).apply();
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

    // ── 加密存储（Android Keystore + AES/GCM，密钥不出硬件）──
    private static final String KS_ALIAS = "xiami_creds_aes";
    private static final String TRANSFORM = "AES/GCM/NoPadding";

    private javax.crypto.SecretKey ksKey() {
        try {
            KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
            ks.load(null);
            if (ks.containsAlias(KS_ALIAS)) {
                return (javax.crypto.SecretKey) ks.getKey(KS_ALIAS, null);
            }
            KeyGenerator kg = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            kg.init(new KeyGenParameterSpec.Builder(KS_ALIAS,
                    KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build());
            return kg.generateKey();
        } catch (Exception e) {
            return null;
        }
    }

    private String enc(String plain) {
        if (plain == null || plain.isEmpty()) return plain;
        try {
            javax.crypto.Cipher c = javax.crypto.Cipher.getInstance(TRANSFORM);
            javax.crypto.SecretKey k = ksKey();
            if (k == null) return null;
            c.init(javax.crypto.Cipher.ENCRYPT_MODE, k);
            byte[] iv = c.getIV();
            byte[] ct = c.doFinal(plain.getBytes("UTF-8"));
            byte[] all = new byte[iv.length + ct.length];
            System.arraycopy(iv, 0, all, 0, iv.length);
            System.arraycopy(ct, 0, all, iv.length, ct.length);
            return Base64.encodeToString(all, Base64.NO_WRAP);
        } catch (Exception e) {
            // 安全红线：加密失败 → 拒绝落盘（fail-closed），绝不降级明文存储
            android.util.Log.w("CredentialStore", "加密失败，拒绝明文落盘", e);
            return null;
        }
    }

    private String dec(String stored) {
        if (stored == null || stored.isEmpty()) return stored;
        try {
            byte[] all = Base64.decode(stored, Base64.NO_WRAP);
            if (all.length <= 12) return "";   // 非法/旧明文 → 视为无凭据
            javax.crypto.Cipher c = javax.crypto.Cipher.getInstance(TRANSFORM);
            javax.crypto.SecretKey k = ksKey();
            if (k == null) return "";
            c.init(javax.crypto.Cipher.DECRYPT_MODE, k,
                    new javax.crypto.spec.GCMParameterSpec(128, Arrays.copyOfRange(all, 0, 12)));
            byte[] pt = c.doFinal(Arrays.copyOfRange(all, 12, all.length));
            return new String(pt, "UTF-8");
        } catch (Exception e) {
            // 解密失败（换机密钥丢失/数据损坏）→ 视为无凭据，绝不把密文/旧数据当明文返回
            android.util.Log.w("CredentialStore", "解密失败，视为无凭据", e);
            return "";
        }
    }

    private String getString(String kind, String skill) {
        String k = key(kind, skill);
        if (k.isEmpty()) return "";
        String v = sp.getString(k, "");
        return dec(v == null ? "" : v);
    }

    private void putString(String kind, String skill, String value) {
        String k = key(kind, skill);
        if (k.isEmpty()) return;
        String encV = enc(value == null ? "" : value);
        if (encV == null) return;   // 加密失败 → 拒绝明文落盘
        sp.edit().putString(k, encV).apply();
    }

    private long getLong(String kind, String skill) {
        String k = key(kind, skill);
        if (k.isEmpty()) return 0L;
        // 新格式：加密 String；兼容旧格式 Long
        String sv = sp.getString(k, "");
        if (sv != null && !sv.isEmpty()) {
            try { return Long.parseLong(dec(sv)); } catch (Exception ignore) {}
        }
        return sp.getLong(k, 0L);
    }

    private void putLong(String kind, String skill, long value) {
        String k = key(kind, skill);
        if (k.isEmpty()) return;
        String encV = enc(String.valueOf(value));
        if (encV == null) return;   // 加密失败 → 拒绝明文落盘
        sp.edit().putString(k, encV).apply();
    }

    // 登录态：Bearer token
    public String getToken(String skill) {
        return getString("token", skill);
    }

    public void setToken(String skill, String token) {
        putString("token", skill, token);
    }

    // refresh_token（自动续期用）
    public String getRefreshToken(String skill) {
        return getString("refresh", skill);
    }

    public void setRefreshToken(String skill, String v) {
        putString("refresh", skill, v);
    }

    // access_token 过期时间戳（毫秒；0 = 未知）
    public long getTokenExpiresAt(String skill) {
        return getLong("expires", skill);
    }

    public void setTokenExpiresAt(String skill, long v) {
        putLong("expires", skill, v);
    }

    // 开放平台 apiKey（按账号 + skill 隔离，不绑定任何平台）
    public String getApiKey(String skill) {
        String em = account();
        if (em.isEmpty()) return "";
        String v = sp.getString("api_key_" + em + "_" + (skill == null ? "" : skill), "");
        return dec(v == null ? "" : v);
    }

    public void setApiKey(String skill, String key) {
        String em = account();
        if (em.isEmpty()) return;
        String encV = enc(key == null ? "" : key);
        if (encV == null) return;   // 加密失败 → 拒绝明文落盘
        sp.edit().putString("api_key_" + em + "_" + (skill == null ? "" : skill), encV).apply();
    }

    // 网页/小程序 cookies（"k=v; k2=v2"）
    public String getCookie(String skill) {
        return getString("cookie", skill);
    }

    public void setCookie(String skill, String cookie) {
        putString("cookie", skill, cookie);
    }

    // 小程序 sessionId
    public String getSessionId(String skill) {
        return getString("session", skill);
    }

    public void setSessionId(String skill, String sessionId) {
        putString("session", skill, sessionId);
    }

    /**
     * 扫描当前账号下已有登录态的 skill（有 token/cookie/session 即算已授权）。
     * 返回 [{skill, kind}]，kind 为 token / cookie / session。
     * 授权中心据此自动出卡片：登录一个平台就多一张，退出则消失。
     */
    public java.util.List<String[]> listAuthorized() {
        java.util.List<String[]> out = new java.util.ArrayList<>();
        String em = account();
        if (em.isEmpty()) return out;
        java.util.LinkedHashMap<String, String> best = new java.util.LinkedHashMap<>();
        String[] kinds = {"token", "cookie", "session"};
        Map<String, ?> all = sp.getAll();
        for (Map.Entry<String, ?> e : all.entrySet()) {
            String k = e.getKey();
            if (k == null) continue;
            Object val = e.getValue();
            if (!(val instanceof String) || ((String) val).isEmpty()) continue;
            for (String kind : kinds) {
                String prefix = kind + "_" + em + "_";
                if (!k.startsWith(prefix)) continue;
                String skill = k.substring(prefix.length());
                if (skill.isEmpty()) continue;
                // token 优先于 cookie/session（同一 skill 只保留一种展示）
                if (!best.containsKey(skill) || "token".equals(kind)) {
                    best.put(skill, kind);
                }
                break;
            }
        }
        for (Map.Entry<String, String> e : best.entrySet()) {
            out.add(new String[]{e.getKey(), e.getValue()});
        }
        return out;
    }

    /** 清除当前账号下某 skill 的全部平台凭据。 */
    public void clearSkill(String skill) {
        String em = account();
        if (em.isEmpty() || skill == null || skill.isEmpty()) return;
        SharedPreferences.Editor ed = sp.edit();
        ed.putString("token_" + em + "_" + skill, "");
        ed.putString("refresh_" + em + "_" + skill, "");
        ed.putString("expires_" + em + "_" + skill, "");
        ed.putString("cookie_" + em + "_" + skill, "");
        ed.putString("session_" + em + "_" + skill, "");
        ed.putString("api_key_" + em + "_" + skill, "");
        ed.apply();
    }

    // 个人资料（就诊人/乘车人：姓名/手机号/证件号等，按邮箱隔离；只存本机，不传云端）
    public void saveProfile(String profileJson) {
        String em = account();
        if (em.isEmpty()) return;
        sp.edit().putString("profile_" + em, enc(profileJson == null ? "" : profileJson)).apply();
    }

    public String getProfile() {
        String em = account();
        if (em.isEmpty()) return "";
        String v = sp.getString("profile_" + em, "");
        return dec(v == null ? "" : v);
    }
}
