# 安卓 · 装在手机里（Termux，不用编译）

把手机本身当服务器。装完就是一个 7×24 跑着的签到引擎，浏览器打开就能看。

**和 APK 的区别**：这条路不需要 Java/Android Studio/构建，5 分钟能跑起来，功能还更全（引擎、控制台、地图页都在）。代价是没有桌面图标，开机自启要额外配一下。

---

## 1. 装 Termux

**别从 Google Play 装** —— 那个版本 2020 年就停更了，`pkg install python` 会失败。

任选一个：

- F-Droid：<https://f-droid.org/packages/com.termux/>
- GitHub：<https://github.com/termux/termux-app/releases> → 下 `termux-app_v0.118.x+github-debug_universal.apk`

装完打开，看到黑底终端和 `~ $` 就是对的。

---

## 2. 把安装包放进去

把 `cxsign-sentinel.zip` 传到手机，放到 **Download** 目录。

传法：微信/QQ 发给自己 → 保存；或者数据线拖进手机。

---

## 3. 跑安装脚本

在 Termux 里逐行输入（每行回车，等它跑完）：

```bash
pkg update -y
pkg install -y unzip
termux-setup-storage
```

`termux-setup-storage` 会弹「允许访问文件」——**点允许**。没有它读不到 Download 目录。

然后：

```bash
cd ~/Download
unzip cxsign-sentinel.zip
cd cxsign-sentinel
bash android/termux/install.sh
```

> 如果 unzip 说找不到文件，先 `ls /sdcard/Download/` 看一眼名字对不对。

脚本会自动：装 python / zbar / unzip → 解压 → 装解码后端 → 跑一遍环境自检。

看到绿色的「装好了」就成功。

---

## 4. 登录

脚本最后会列三种方式，**推荐 B**（你现在电脑上就有现成的 cookie）：

### B. 从电脑搬 cookie（最稳）

1. 电脑上找到这个文件：
   ```
   cxsign-sentinel/core/data/cookie.json
   ```
2. 微信发给自己 → 手机上保存到 Download
3. Termux 里：

```bash
mkdir -p ~/cxsign-sentinel/core/data
cp /sdcard/Download/cookie.json ~/cxsign-sentinel/core/data/cookie.json
cd ~/cxsign-sentinel/core
python run.py doctor
```

最后两行应该是：

```
登录态      : 有效（登录有效）
uid/fid     : 342160606 / 1403
```

### A. 账号密码（如果 cookie 搬不过去）

```bash
cd ~/cxsign-sentinel/core
python run.py login --account 你的手机号 --password 你的密码
```

账号开了图形验证码的话会被拦，那就回 B。

---

## 5. 启动

```bash
cd ~/cxsign-sentinel/core
bash ~/cxsign-sentinel/android/termux/start.sh -d
```

`-d` 是后台模式，关掉终端也不停。会打印：

```
✓ 后台启动，PID 12345

  手机浏览器:  http://127.0.0.1:8848/
  同 WiFi 设备: http://192.168.1.x:8848/
```

**手机浏览器打开 `http://127.0.0.1:8848/`**，看到控制台就对了。

停止：`bash ~/cxsign-sentinel/android/termux/start.sh --kill`

日志：`tail -f ~/cxsign-sentinel/core/data/sentinel.log`

---

## 6. 别让它被系统杀掉（关键）

Termux 在后台被回收，引擎就停了。三件事都要做：

1. **设置 → 应用 → Termux → 电池 → 不限制 / 无限制**
2. **设置 → 应用 → Termux → 自启动 → 允许**
3. 小米/华为/OPPO/vivo 还要单独开：**后台弹出界面**、**锁屏显示**

装 `termux-api` 可以让脚本自动申请 wakelock：

```bash
pkg install -y termux-api
```

（还要在应用商店装 Termux:API 那个 App）

---

## 7. 加到桌面（当 App 用）

手机 Chrome 打开 `http://127.0.0.1:8848/` → 右上角三个点 → **添加到主屏幕**。

桌面上就有图标了，点开就是控制台。

---

## 8. 开机自启（可选）

装 **Termux:Boot**（F-Droid 里搜），然后：

```bash
mkdir -p ~/.termux/boot
cat > ~/.termux/boot/cxsign.sh <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
cd ~/cxsign-sentinel/core
exec python run.py serve --host 0.0.0.0 --port 8848 >> ~/cxsign-sentinel/core/data/sentinel.log 2>&1
EOF
chmod +x ~/.termux/boot/cxsign.sh
```

开机自动起，不用每次手动。

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `install.sh: /data/data/... : bad interpreter` | 换行符坏了。修：`sed -i 's/\r$//' install.sh start.sh` 再跑 |
| `pkg update` 卡住不动 | 换源：另开一个会话跑 `termux-change-repo`，选清华或中科大 |
| `unzip: cannot find` | 没跑 `termux-setup-storage`，或者路径不对，先 `ls /sdcard/Download/` |
| `python: command not found` | `pkg install -y python` 没成功，重跑一次 |
| 二维码解码不可用 | `pkg install -y zbar` 然后 `pip install pyzbar` |
| 手机浏览器打不开 8848 | 引擎没起来。`bash start.sh`（不加 -d）看前台报错 |
| 电脑连不上手机的 8848 | 两台设备要在同一 WiFi；启动时必须是 `--host 0.0.0.0`（start.sh 默认就是） |
| 跑一阵就没了 | 电池优化没关，回去做第 6 步 |

---

## 关于 APK

想要桌面图标 + 通知栏自动取图，得装那个原生壳（`../`），但它需要构建：

1. 把仓库推到 GitHub → `.github/workflows/build-apk.yml` 自动构建 → Actions 页面底部 Artifacts 下 APK
2. 或者本地装 Android Studio 打开 `android/` 目录点运行

本机没有 Java/Gradle/SDK 的话，走第 1 条最省事。

APK 里的地址填 `http://127.0.0.1:8848`（同一台手机）。
