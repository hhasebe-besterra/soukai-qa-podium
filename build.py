# -*- coding: utf-8 -*-
"""
ビルドスクリプト：
  - generate_qa_podium.py を実行して 株主総会QA_演台用.html を最新化
  - AES-GCM + PBKDF2(SHA-256, 310,000回) で暗号化
  - index.html（パスワード入力→復号→表示）に埋め込んで出力
"""
import os, sys, base64, json, subprocess, shutil
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = r"C:\Users\h.hasebe\Downloads\川崎事故対応\川崎事故対応"
SRC_HTML = os.path.join(SRC_DIR, "株主総会QA_演台用.html")
GEN_SCRIPT = os.path.join(SRC_DIR, "generate_qa_podium.py")
OUT_HTML = os.path.join(ROOT, "index.html")

PASSWORD = "besterra"
ITERATIONS = 310_000  # OWASP推奨値

# 1. 最新HTMLを生成
print(">>> 生成スクリプト実行")
subprocess.run([sys.executable, GEN_SCRIPT], check=True)

with open(SRC_HTML, "rb") as f:
    plaintext = f.read()
print(f">>> 平文 {len(plaintext):,} bytes")

# 2. 暗号化
salt = os.urandom(16)
iv   = os.urandom(12)
kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
key = kdf.derive(PASSWORD.encode("utf-8"))
aesgcm = AESGCM(key)
ct = aesgcm.encrypt(iv, plaintext, None)

payload = {
    "salt": base64.b64encode(salt).decode(),
    "iv":   base64.b64encode(iv).decode(),
    "ct":   base64.b64encode(ct).decode(),
    "iter": ITERATIONS,
}
print(f">>> 暗号文 {len(payload['ct']):,} bytes (base64)")

wrapper = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ベステラ㈱ 株主総会 演台用Q&A</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;font-family:"Noto Sans JP","Hiragino Sans","Meiryo",sans-serif}
body{background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;padding:20px}
.login-box{background:#1e293b;padding:44px 40px;border-radius:12px;max-width:440px;width:100%;box-shadow:0 10px 40px rgba(0,0,0,.5);border:1px solid #334155}
.brand{font-size:13px;color:#94a3b8;letter-spacing:.08em;margin-bottom:8px}
h1{font-size:20px;color:#fff;margin-bottom:6px;line-height:1.5}
.sub{font-size:12px;color:#94a3b8;margin-bottom:28px;line-height:1.7}
.sub .strong{color:#f87171;font-weight:700}
label{display:block;font-size:12px;color:#cbd5e1;margin-bottom:8px;font-weight:700}
input{width:100%;padding:14px 18px;border:2px solid #334155;background:#0f172a;color:#fff;border-radius:8px;font-size:16px;font-family:inherit;outline:none;letter-spacing:.1em}
input:focus{border-color:#60a5fa}
button{width:100%;margin-top:18px;padding:14px;background:#dc2626;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;font-family:inherit}
button:hover{background:#b91c1c}
button:disabled{background:#475569;cursor:wait}
.err{color:#f87171;font-size:13px;margin-top:14px;min-height:20px;text-align:center;font-weight:700}
.hint{margin-top:22px;padding-top:18px;border-top:1px solid #334155;font-size:11px;color:#64748b;line-height:1.8}
.loading{text-align:center;color:#94a3b8;font-size:13px}
.loading .bar{margin-top:12px;height:4px;background:#334155;border-radius:2px;overflow:hidden}
.loading .bar span{display:block;height:100%;width:0;background:#60a5fa;transition:width .3s}
</style>
</head>
<body>
<div class="login-box" id="loginBox">
  <div class="brand">BESTERRA · CONFIDENTIAL</div>
  <h1>株主総会 演台用Q&amp;A</h1>
  <div class="sub">2026年4月23日 株主総会 議長用<br>
    <span class="strong">※</span> 本資料は機密情報を含みます。外部への転送・開示を禁じます。
  </div>
  <form onsubmit="unlock(event)">
    <label for="pw">パスワード</label>
    <input type="password" id="pw" placeholder="••••••••" autofocus autocomplete="current-password">
    <button type="submit" id="btn">🔓 アクセス</button>
    <div class="err" id="err"></div>
  </form>
  <div class="hint">
    パスワードをお持ちでない方はご担当者までお問い合わせください。<br>
    本サイトの内容は暗号化されており、正しいパスワードを入力するまで閲覧できません。
  </div>
</div>
<div class="login-box" id="loadingBox" style="display:none">
  <div class="loading">
    <div>復号中...</div>
    <div class="bar"><span id="bar"></span></div>
  </div>
</div>

<script>
const PAYLOAD = __PAYLOAD__;

function b64ToBytes(b64){
  const s = atob(b64);
  const bytes = new Uint8Array(s.length);
  for(let i=0;i<s.length;i++) bytes[i] = s.charCodeAt(i);
  return bytes;
}

async function unlock(ev){
  ev.preventDefault();
  const pw = document.getElementById("pw").value;
  const btn = document.getElementById("btn");
  const err = document.getElementById("err");
  if(!pw){ err.textContent = "パスワードを入力してください"; return; }
  err.textContent = "";
  btn.disabled = true;
  btn.textContent = "復号中...";
  document.getElementById("bar").style.width = "30%";
  try {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey(
      "raw", enc.encode(pw),
      {name:"PBKDF2"}, false, ["deriveKey"]
    );
    document.getElementById("bar").style.width = "55%";
    const key = await crypto.subtle.deriveKey(
      {name:"PBKDF2", salt: b64ToBytes(PAYLOAD.salt), iterations: PAYLOAD.iter, hash:"SHA-256"},
      keyMaterial,
      {name:"AES-GCM", length:256},
      false, ["decrypt"]
    );
    document.getElementById("bar").style.width = "80%";
    const plain = await crypto.subtle.decrypt(
      {name:"AES-GCM", iv: b64ToBytes(PAYLOAD.iv)},
      key,
      b64ToBytes(PAYLOAD.ct)
    );
    document.getElementById("bar").style.width = "100%";
    const html = new TextDecoder("utf-8").decode(plain);
    // 復号成功：本体HTMLで差し替え
    document.open();
    document.write(html);
    document.close();
  } catch(e) {
    btn.disabled = false;
    btn.textContent = "🔓 アクセス";
    err.textContent = "パスワードが違います";
    document.getElementById("pw").select();
  }
}
// クリップボードからの自動入力（URL ?pw=xxx）は安全性のため提供しない
</script>
</body>
</html>
"""

final = wrapper.replace("__PAYLOAD__", json.dumps(payload))
with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
    f.write(final)
print(f">>> 出力 {OUT_HTML} ({len(final):,} bytes)")
