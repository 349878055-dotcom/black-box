package com.xiami.host;

import android.content.Context;
import android.content.SharedPreferences;

/**
 * 手机本地凭据库（Device-as-Proxy 第 4 条基础版）。
 *
 * 第三方登录态（glyy Bearer token / tuniu cookies+sessionId / apiKey）
 * 只存用户手机本地（用户自己的凭据），云端不聚合、不持有。
 *
 * 基础版：SharedPreferences（私有文件）。
 * 升级版（第 4 条深化）：Android Keystore 加密 / EncryptedSharedPreferences。
 */
public class CredentialStore {
    private static final String PREFS = "xiami_creds";
    private final SharedPreferences sp;

    public CredentialStore(Context ctx) {
        this.sp = ctx.getApplicationContext()
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    // glyy：Bearer token
    public String getToken(String skill) {
        return sp.getString("token_" + skill, "");
    }

    public void setToken(String skill, String token) {
        sp.edit().putString("token_" + skill, token == null ? "" : token).apply();
    }

    // glyy refresh_token（自动续期用，第 4 条扩展）
    public String getRefreshToken(String skill) {
        return sp.getString("refresh_" + skill, "");
    }

    public void setRefreshToken(String skill, String v) {
        sp.edit().putString("refresh_" + skill, v == null ? "" : v).apply();
    }

    // glyy access_token 过期时间戳（毫秒；0 = 未知）
    public long getTokenExpiresAt(String skill) {
        return sp.getLong("expires_" + skill, 0L);
    }

    public void setTokenExpiresAt(String skill, long v) {
        sp.edit().putLong("expires_" + skill, v).apply();
    }

    // tuniu 开放平台 apiKey
    public String getApiKey() {
        return sp.getString("api_key_tuniu", "");
    }

    public void setApiKey(String key) {
        sp.edit().putString("api_key_tuniu", key == null ? "" : key).apply();
    }

    // 网页/小程序 cookies（"k=v; k2=v2"）
    public String getCookie(String skill) {
        return sp.getString("cookie_" + skill, "");
    }

    public void setCookie(String skill, String cookie) {
        sp.edit().putString("cookie_" + skill, cookie == null ? "" : cookie).apply();
    }

    // 途牛小程序 sessionId
    public String getSessionId(String skill) {
        return sp.getString("session_" + skill, "");
    }

    public void setSessionId(String skill, String sessionId) {
        sp.edit().putString("session_" + skill, sessionId == null ? "" : sessionId).apply();
    }
}
