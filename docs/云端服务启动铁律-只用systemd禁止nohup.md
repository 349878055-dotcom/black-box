# ⚠️ 云端服务启动铁律：只用 systemd，禁止 nohup 手动启动

> **这是踩了 4768 次崩溃循环换来的教训，交接/测试必读。**
> **一句话铁律：云端服务（19000 端口）只能 `systemctl restart shimeban-cloud.service` 管理，禁止任何 `nohup` / `run.sh` 手动启动。**
> 最后更新：2026-08-13（真机+云端实测定位）

---

## 〇、为什么会有这个铁律（背景）

云端服务 = FastAPI（`python -m cloud.cloud_orchestrator.main`），监听 **19000 端口**。系统里有两套启动方式：

| 方式 | 命令 | 归宿 |
|---|---|---|
| ✅ **systemd（唯一正确）** | `sudo systemctl restart shimeban-cloud.service` | systemd 托管，崩溃自动重启，日志进 `service.log` |
| ❌ **nohup 手动（禁止）** | `nohup bash run.sh &` / `nohup python -m ... &` | 无人托管，占端口不释放 |

**问题**：两套方式**抢同一个 19000 端口**。谁先启动谁占住，后启动的 bind 失败直接退出。

---

## 一、踩坑现场（2026-08-13 实测）

- 有人用 `nohup bash run.sh &` 手动起了服务 → 占住 19000；
- systemd 每次启动都 `Errno 98: address already in use` → uvicorn 退出码 3 → `Restart=always` 又拉起 → 又失败 → **无限循环，累计 NRestarts=4768**；
- 但 nohup 进程一直活着、health 一直 `ok` → **表面"服务正常"，实际 systemd 4768 次全在失败**；
- 于是 `deploy_cloud.py` 里的 `systemctl restart` 其实**根本没重启到真正服务的进程**（它被 nohup 占着端口，systemd 起不来）→ 改完代码重启无效、新代码永远不生效。

**典型症状**：
```
journalctl -u shimeban-cloud.service | tail
→ shimeban-cloud.service: Failed with result 'exit-code'.
→ Main process exited, code=exited, status=3/NOTIMPLEMENTED
service.log 里：
→ ERROR: [Errno 98] error while attempting to bind on address ('0.0.0.0', 19000): address already in use
```

---

## 二、交接/测试前必查（30 秒定位）

```bash
ssh ubuntu@140.143.144.28   # 密码 Jtao_8505

# 1) 19000 端口是谁占的（必须只有一个 systemd 进程）
ss -tlnp | grep 19000
#   ✅ 期望：python pid=X（systemd 管的那个）
#   ❌ 异常：看到多个 python，或 /tmp/cloud_orch.log 在增长（说明有 nohup 手动进程）

# 2) systemd 是否在崩溃循环
systemctl show shimeban-cloud.service -p NRestarts -p ActiveState
#   ❌ 异常：NRestarts 一直在涨 / ActiveState=activating（auto-restart）

# 3) 有没有 nohup 残留进程
pgrep -af 'cloud_orchestrator.main'
#   ❌ 异常：出现非 systemd 的 python -m cloud_orchestrator.main（PPID 不是 1/systemd）
```

---

## 三、踩了怎么办（恢复三步）

```bash
# ① 杀掉所有 nohup 手动进程（释放 19000）
#    先看 pid：ps -o pid,etime,cmd -p $(pgrep -f cloud_orchestrator.main | tr '\n' ',' | sed 's/,$//') 
#    把非 systemd 的 pid 杀掉（如 4030572 这类 PPID=1 的 nohup 进程）：
kill <nohup_pid>

# ② 确认端口释放
ss -tlnp | grep 19000   # 应无输出 = 已释放

# ③ 让 systemd 接管（唯一正确重启方式）
echo Jtao_8505 | sudo -S systemctl restart shimeban-cloud.service
sleep 8
curl -s http://127.0.0.1:19000/health   # {"status":"ok"}
systemctl is-active shimeban-cloud.service   # active
```

> ⚠️ 千万别用 `kill <systemd主pid>` 或者再 nohup 拉起——那会重新回到抢端口循环。

---

## 四、防再犯清单（同事协作时对着做）

1. **重启服务永远只用**：`echo Jtao_8505 | sudo -S systemctl restart shimeban-cloud.service`
2. **绝对禁止**：`nohup bash run.sh &`、`nohup python -m cloud.cloud_orchestrator.main &`、`python run.sh &`
3. **部署代码**：用 `python3 tools/deploy_cloud.py`（内部已内置 systemctl restart），**不要手动 nohup** 再部署
4. **交接时**：先跑一遍第二节的"30 秒必查"，确认 19000 只有一个 systemd 进程、NRestarts 不再涨，再动手
5. **run.sh 只作历史参考，不要执行**：它是旧的手动启动脚本，与 systemd 完全重复；要启动请用 systemd
6. **看到 `address already in use` 或 `status=3`**：先想"是不是又有 nohup 进程"，按第三节恢复，别盲目重启

---

## 五、一句总结

**19000 端口只能有 systemd 一个管家。谁手动 nohup 谁制造 4768 次崩溃循环，而且 health 还显示正常骗过所有人。交接测试前先查端口，别让 nohup 幽灵进程挡路。**
