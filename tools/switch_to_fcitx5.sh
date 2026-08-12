#!/usr/bin/env bash
# 把系统输入法切到 fcitx5，并让 Cursor 使用 fcitx
set -euo pipefail

echo "==> 切换 im-config -> fcitx5"
im-config -n fcitx5

echo "==> 更新 ~/.profile / ~/.xprofile 环境变量"
python3 - <<'PY'
from pathlib import Path
replacements = [
    ("export GTK_IM_MODULE=ibus", "export GTK_IM_MODULE=fcitx"),
    ("export QT_IM_MODULE=ibus", "export QT_IM_MODULE=fcitx"),
    ("export XMODIFIERS=@im=ibus", "export XMODIFIERS=@im=fcitx"),
    ("export SDL_IM_MODULE=ibus", "export SDL_IM_MODULE=fcitx"),
]
for p in [Path.home() / ".profile", Path.home() / ".xprofile"]:
    if not p.exists():
        continue
    text = p.read_text(encoding="utf-8")
    orig = text
    for a, b in replacements:
        text = text.replace(a, b)
    if text != orig:
        p.write_text(text, encoding="utf-8")
        print(f"updated {p}")
    else:
        # ensure fcitx exports exist
        if "GTK_IM_MODULE=fcitx" not in text:
            text += (
                "\n# 中文输入法 fcitx5\n"
                "export GTK_IM_MODULE=fcitx\n"
                "export QT_IM_MODULE=fcitx\n"
                "export XMODIFIERS=@im=fcitx\n"
                "export SDL_IM_MODULE=fcitx\n"
            )
            p.write_text(text, encoding="utf-8")
            print(f"appended {p}")
        else:
            print(f"ok {p}")
PY

echo "==> 写 Cursor 启动项（强制 fcitx）"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/cursor.desktop" <<'EOF'
[Desktop Entry]
Name=Cursor
Comment=The AI Code Editor.
GenericName=Text Editor
Exec=env GTK_IM_MODULE=fcitx QT_IM_MODULE=fcitx XMODIFIERS=@im=fcitx SDL_IM_MODULE=fcitx /usr/share/cursor/cursor %F
Icon=co.anysphere.cursor
Type=Application
StartupNotify=false
StartupWMClass=Cursor
Categories=TextEditor;Development;IDE;
MimeType=application/x-cursor-workspace;
Actions=new-empty-window;
Keywords=cursor;

[Desktop Action new-empty-window]
Name=New Empty Window
Name[zh_CN]=新建空窗口
Exec=env GTK_IM_MODULE=fcitx QT_IM_MODULE=fcitx XMODIFIERS=@im=fcitx SDL_IM_MODULE=fcitx /usr/share/cursor/cursor --new-window %F
Icon=co.anysphere.cursor
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "==> 写 fcitx5 自启动"
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/org.fcitx.Fcitx5.desktop" <<'EOF'
[Desktop Entry]
Name=Fcitx 5
Comment=Start Input Method
Exec=fcitx5 -d
Icon=fcitx
Terminal=false
Type=Application
Categories=System;
X-GNOME-Autostart-Phase=Applications
X-GNOME-AutoRestart=true
EOF

echo "==> GNOME 输入源去掉 ibus-libpinyin（交给 fcitx）"
gsettings set org.gnome.desktop.input-sources sources "[('xkb', 'us')]" || true

echo "==> 重启输入法进程"
ibus exit 2>/dev/null || true
killall ibus-daemon 2>/dev/null || true
sleep 1
killall fcitx5 2>/dev/null || true
sleep 1
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export SDL_IM_MODULE=fcitx
fcitx5 -d --replace
sleep 2

echo "==> 当前状态"
ps aux | grep -E 'fcitx5|ibus-daemon' | grep -v grep || true
grep -E 'IM_|XMOD' "$HOME/.profile" "$HOME/.xprofile" || true
fcitx5-remote 2>/dev/null || true

echo
echo "完成。请完全退出并重新打开 Cursor，再用 Ctrl+Space 切中文。"
echo "若仍异常，注销并重新登录一次桌面会话。"
