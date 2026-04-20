# -*- coding: utf-8 -*-
"""
ビルドスクリプト（Sheets直結版）：
  1. Google Sheets を CSV エクスポート経由で取得
  2. Q&A データ構造に変換（A-E分類、信託株主、定型文8件）
  3. 演台UI HTML を生成
  4. AES-256-GCM + PBKDF2(SHA-256, 310,000回) で暗号化
  5. index.html に埋め込んで出力
"""
import os, sys, base64, json, csv, io, urllib.request, datetime, hashlib
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_HTML = os.path.join(ROOT, "index.html")

SHEET_ID = "1-Bn5jOo2NFTBBu2Rt5LWUzdmqfy01vVR2WkfTOglYB8"
SHEET_GID = "0"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={SHEET_GID}"

PASSWORD = os.environ.get("PODIUM_PW", "besterra")
ITERATIONS = 310_000

CAT_LABELS = {
    "A": "A. 事故の直接的状況",
    "B": "B. 責任の所在と指揮系統",
    "C": "C. 業績・財務・賠償への影響",
    "D": "D. 経営責任とガバナンス",
    "E": "E. 今後の捜索・再発防止・事業継続",
    "F": "F. 信託株主からの質問",
}

# 2026-04-20 版 定型文 × 8
TEMPLATES = [
    ("T1", "定型文① 調査中につき回答不能",
     "現在関係当局が事実を確認している状況であり、当社としては、当局の調査に全面的に協力している状況でございます。大変恐縮でございますが、私どもの口から断片的な事実や憶測を申し上げることは出来かねますのでご理解ください。\n―以上、ご回答申し上げました。"),
    ("T2", "定型文② 事業への影響不透明",
     "現時点では、事業への影響や、損害賠償の総額は確定しておりません。当社は賠償責任保険に加入しておりますが、その適用範囲も含め、現在精査を進めております。当社としては、あらゆる事態を想定しながら、事業の継続と企業価値の維持に努めてまいります。財務状況に影響が見込まれる事実は発生しましたら、適時開示のルールに則り、速やかに報告すべき事項をご報告いたします。\n―以上、ご回答申し上げました。"),
    ("T3", "定型文③ 業績への影響不透明",
     "株主の皆様が当社の業績や財務基盤について大変ご心配されていること、重々承知しております。現時点では、事業への影響や、損害賠償の総額は全く確定しておらず、業績や財務状況に関する影響は不明であります。当社は各種賠償責任保険に加入しておりますが、その適用範囲も含め、現在精査を進めております。私ども経営陣としましては、事業の継続と企業価値の維持に努めてまいります。財務状況に影響が見込まれる事実は発生しましたら、適時開示のルールに則り、速やかに報告すべき事項をご報告いたします。\n―以上、ご回答申し上げました。"),
    ("T4", "定型文④ 役員の責任",
     "事故の原因については関係当局と協力して事実を確認している状況でございます。当局の調査に全面的に協力し、事実関係がお伝えできるようになり次第、速やかにご報告させて頂きます。ただし、会社の経営責任は、経営陣にあることには違いありません。そのため、この状況の先頭に立ち、①行方不明者の方の一刻も早い発見、②ご遺族・被災された方への誠心誠意の対応、③徹底的な原因究明、そして④二度とこのような悲劇を繰り返さないための再発防止策の策定と実行に、全身全霊をもって道筋をつけることが私の使命であると考えております。それが、株主の皆様を含む関係者の皆様に対して、私がまず果たすべき責任であると信じております。自らの進退・役員報酬等の返上について、現在は考えておりませんが、事故の原因究明と責任の所在が明らかになり次第、厳正に判断してまいります。\n―以上、ご回答申し上げました。"),
    ("T5", "定型文⑤ 再発防止",
     "現在は、事故の原因について関係当局と協力して事実を確認している状況でございます。再発防止策についてはその原因を受けて策定すべきものと考えているため、当局の調査に全面的に協力し、事実関係がお伝えできるようになり次第、速やかにご報告させて頂きます。\n―以上、ご回答申し上げました。"),
    ("T6", "定型文⑥ 法的な責任分担",
     "建設業法や労働安全衛生法に基づく法的な責任分担の詳細につきましては、現在、関係当局において精査が進められているものと認識しております。しかしながら、法律論以前の問題として、私どもは実際に工事を施工する立場であり、私たちの管理する現場で作業員3名がお亡くなりになり、1名が負傷される事故が発生し、また作業員1名が未だ行方不明となっている事実を、何よりも重く受け止めております。お亡くなりになられた方のご冥福をお祈りし、ご遺族の方々に衷心よりお悔やみ申し上げますと共に、負傷された方には心よりお見舞い申し上げます。責任の所在がどこにあろうとも、事故を防げなかったことに対する我々の責任が軽減されるものではございません。この責任を痛感し、今後の対応にあたってまいります。\n―以上、ご回答申し上げました。"),
    ("T7", "定型文⑦ プライバシー",
     "被災された方々のプライバシーに関わる事項でございますので、詳細についての公表は控えさせていただきます。\n―以上、ご回答申し上げました。"),
    ("TG", "概要説明",
     "株主様より事故の概要を説明して欲しいとのご意見を賜りましたので、概要を説明いたします。2026年4月7日、弊社が施工中の設備解体工事現場において作業員3名がお亡くなりになり、2名が負傷される事故が発生しました。また、作業員1名が未だ行方不明となっており、一刻も早く救助できるよう、関係機関のご協力を得ながら、捜索に全力を尽くしている状況であります。事故の原因につきましては、関係当局の調査中であり、調査に全面的に協力している状況でございます。詳細は、後ほどの事故に関する説明会でご説明申し上げます。\n―以上、ご回答申し上げました。"),
]


def classify_tag(a_class: str) -> str:
    """A分類 → 回答バッジ"""
    a = a_class.strip()
    if "①" in a or "調査中" in a or "⑦" in a or "プライバシー" in a:
        return "declined"
    if "定型文" in a:
        return "template"
    # 個別回答 / 社外役員回答 / 個別的 / その他
    return "answered"


def fetch_sheet_csv() -> str:
    """Google Sheets から CSV をダウンロード"""
    req = urllib.request.Request(SHEET_CSV_URL, headers={"User-Agent": "soukai-qa-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_qa(csv_text: str):
    data = {k: {"label": v, "items": []} for k, v in CAT_LABELS.items()}
    sources = {}
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if len(row) < 7:
            continue
        no_str = row[1].strip()
        if not no_str.isdigit():
            continue
        no = int(no_str)
        a_cls = row[2].strip()
        q = row[3].strip()
        a = row[4].strip()
        src = row[5].strip()
        q_cls = row[6].strip()
        if not q or not a:
            continue

        tag = classify_tag(a_cls)

        if no >= 201:
            cat = "F"
            display_id = f"F{no - 200}"
        else:
            first = q_cls[:1].upper()
            cat = first if first in "ABCDE" else "A"
            display_id = str(no)

        data[cat]["items"].append((display_id, q, a, tag))
        if src:
            sources[display_id] = src
    return data, sources


# ─────────────────── HTML 生成 ───────────────────

HTML_WRAPPER_TEMPLATE = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>ベステラ㈱ 株主総会 演台用Q&A</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{font-family:"Noto Sans JP","Hiragino Sans","Meiryo",sans-serif;background:#0f172a;color:#e2e8f0;font-size:15px;display:flex;flex-direction:column}
header{background:#1e293b;color:#fff;padding:10px 18px;display:flex;align-items:center;justify-content:space-between;gap:14px;border-bottom:2px solid #334155;flex-shrink:0}
header .title{font-size:15px;font-weight:700;letter-spacing:.02em}
header .meta{font-size:11px;color:#94a3b8}
header .actions{display:flex;gap:8px;align-items:center}
header button{background:#334155;color:#fff;border:none;padding:7px 14px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit}
header button:hover{background:#475569}
header button.primary{background:#dc2626}
header button.primary:hover{background:#b91c1c}
.kbd{display:inline-block;padding:2px 6px;background:#0f172a;border:1px solid #475569;border-radius:4px;font-size:10px;color:#cbd5e1;margin:0 2px}
.main{display:flex;flex:1;min-height:0}
.pane-left{width:420px;background:#1e293b;border-right:2px solid #334155;display:flex;flex-direction:column;min-height:0}
.search-area{padding:12px 14px;background:#0f172a;border-bottom:1px solid #334155}
.search-row{display:flex;gap:6px;margin-bottom:8px}
.search-row input{flex:1;padding:10px 14px;border:2px solid #334155;background:#1e293b;color:#e2e8f0;border-radius:6px;font-size:14px;font-family:inherit;outline:none}
.search-row input:focus{border-color:#60a5fa}
#jumpInput{width:68px;text-align:center;font-weight:700}
.scope-row{display:flex;gap:6px;flex-wrap:wrap}
.scope-btn{padding:5px 10px;background:#334155;color:#cbd5e1;border:none;border-radius:4px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.scope-btn.active{background:#3b82f6;color:#fff}
.tab-row{display:flex;gap:2px;padding:0 8px;background:#1e293b;border-bottom:1px solid #334155;flex-shrink:0;overflow-x:auto}
.tab-row::-webkit-scrollbar{height:4px}
.tab-row::-webkit-scrollbar-thumb{background:#475569}
.tab-btn{padding:9px 10px;background:transparent;color:#94a3b8;border:none;border-bottom:3px solid transparent;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap}
.tab-btn.active{color:#fff;border-bottom-color:#3b82f6}
.tab-btn:hover{color:#e2e8f0}
.list-area{flex:1;overflow-y:auto;padding:6px 8px 40px}
.list-area::-webkit-scrollbar{width:8px}
.list-area::-webkit-scrollbar-thumb{background:#475569;border-radius:4px}
.list-item{padding:9px 12px;margin-bottom:3px;border-radius:6px;cursor:pointer;display:flex;gap:8px;align-items:flex-start;border:2px solid transparent;background:#0f172a;transition:background .1s}
.list-item:hover{background:#27344a}
.list-item.selected{background:#1e40af;border-color:#60a5fa}
.list-item.selected .li-num{background:#dc2626}
.li-num{flex-shrink:0;min-width:46px;height:22px;padding:0 6px;background:#334155;color:#fff;border-radius:4px;font-size:11px;font-weight:700;display:flex;align-items:center;justify-content:center}
.li-q{flex:1;font-size:12.5px;line-height:1.5;color:#e2e8f0;font-weight:500;word-break:break-word}
.li-tag{flex-shrink:0;width:8px;height:8px;border-radius:50%;margin-top:6px}
.li-tag.green{background:#22c55e}
.li-tag.orange{background:#f59e0b}
.li-tag.red{background:#ef4444}
.li-tag.blue{background:#3b82f6}
.list-empty{padding:40px 20px;text-align:center;color:#64748b;font-size:13px}
.pane-right{flex:1;background:#f8fafc;color:#0f172a;display:flex;flex-direction:column;min-height:0;min-width:0}
.right-head{padding:14px 28px;background:#fff;border-bottom:2px solid #cbd5e1;display:flex;align-items:center;gap:14px;flex-shrink:0}
.qbox{flex:1;min-width:0}
.qno{display:inline-block;background:#dc2626;color:#fff;padding:4px 14px;border-radius:6px;font-size:18px;font-weight:700;margin-right:10px;vertical-align:middle}
.qtag{display:inline-block;padding:4px 12px;border-radius:6px;font-size:13px;font-weight:700;vertical-align:middle;margin-right:8px;border:2px solid transparent}
.qtag.green{background:#dcfce7;color:#15803d;border-color:#22c55e}
.qtag.orange{background:#fef3c7;color:#92400e;border-color:#f59e0b}
.qtag.red{background:#fee2e2;color:#991b1b;border-color:#ef4444}
.qtag.blue{background:#dbeafe;color:#1e40af;border-color:#3b82f6}
.qtitle{font-size:20px;font-weight:700;line-height:1.6;color:#0f172a;margin-top:8px}
.right-body{flex:1;overflow-y:auto;padding:28px 40px 60px;background:#f8fafc}
.right-body::-webkit-scrollbar{width:12px}
.right-body::-webkit-scrollbar-thumb{background:#94a3b8;border-radius:6px}
.answer-box{background:#fff;border:2px solid #cbd5e1;border-radius:12px;padding:36px 44px;box-shadow:0 4px 16px rgba(0,0,0,.08);max-width:1200px;margin:0 auto}
.answer-label{font-size:13px;font-weight:700;color:#64748b;letter-spacing:.2em;margin-bottom:14px}
.answer-text{font-size:var(--answer-size,28px);line-height:2.0;color:#0f172a;white-space:pre-wrap;font-weight:500;letter-spacing:.02em}
.answer-src{margin-top:24px;padding-top:14px;border-top:1px dashed #cbd5e1;font-size:13px;color:#64748b;white-space:pre-wrap;line-height:1.7}
.actions-row{display:flex;gap:8px;align-items:center}
.actions-row button{background:#1e293b;color:#fff;border:none;padding:8px 14px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap}
.actions-row button:hover{background:#334155}
.actions-row button.big{background:#dc2626;font-size:13px;padding:10px 18px}
.actions-row button.big:hover{background:#b91c1c}
.size-ctl{display:flex;align-items:center;gap:4px;background:#1e293b;border-radius:6px;padding:3px}
.size-ctl button{background:transparent;padding:4px 10px;font-size:14px}
.size-ctl .size-val{color:#fff;font-size:11px;min-width:42px;text-align:center}
.empty-hint{padding:80px 40px;text-align:center;color:#64748b}
.empty-hint h2{font-size:22px;color:#1e293b;margin-bottom:16px}
.empty-hint p{font-size:14px;line-height:1.8;margin-bottom:8px}
body.podium .pane-left{display:none}
body.podium header{display:none}
body.podium .right-head{padding:24px 48px;background:#fff;border-bottom:3px solid #0f172a}
body.podium .qtitle{font-size:28px}
body.podium .qno{font-size:22px;padding:6px 18px}
body.podium .answer-text{font-size:calc(var(--answer-size,28px) * 1.5);line-height:2.0;font-weight:500}
body.podium .answer-box{padding:48px 64px}
body.podium .right-body{padding:40px}
body.podium .actions-row button.exit-podium{display:inline-block}
.actions-row button.exit-podium{display:none;background:#dc2626}
.kbd-hint{position:fixed;bottom:10px;right:14px;background:rgba(15,23,42,.85);color:#cbd5e1;padding:8px 12px;border-radius:6px;font-size:11px;z-index:200;line-height:1.7;pointer-events:none}
.sync-badge{background:#22c55e;color:#fff;font-size:10px;padding:2px 8px;border-radius:4px;margin-left:8px;font-weight:700}
</style>
</head>
<body>
<header>
  <div>
    <div class="title">ベステラ㈱ 株主総会 <span style="color:#f87171">演台用Q&amp;A</span><span class="sync-badge" title="Google Sheets から自動同期">🔄 SHEETS同期</span></div>
    <div class="meta">2026年4月23日 株主総会 ／ データ同期 __BUILD_TIME__ ／ 全__TOTAL__問＋定型文__TPL__件</div>
  </div>
  <div class="actions">
    <button onclick="togglePodium()" class="primary" title="演台モード (F)">🖥 演台モード <span class="kbd">F</span></button>
  </div>
</header>
<div class="main">
  <div class="pane-left">
    <div class="search-area">
      <div class="search-row">
        <input type="text" id="searchInput" placeholder="🔍 キーワード検索" autocomplete="off">
        <input type="text" id="jumpInput" placeholder="Q#" autocomplete="off" title="Q番号を入力してEnter">
      </div>
      <div class="scope-row">
        <button class="scope-btn active" data-scope="both">質問＋回答</button>
        <button class="scope-btn" data-scope="q">質問のみ</button>
        <button class="scope-btn" data-scope="a">回答のみ</button>
      </div>
    </div>
    <div class="tab-row" id="tabRow"></div>
    <div class="list-area" id="listArea"></div>
  </div>
  <div class="pane-right">
    <div class="right-head" id="rightHead" style="display:none">
      <div class="qbox">
        <span class="qno" id="rhNo"></span>
        <span class="qtag" id="rhTag"></span>
        <span style="font-size:11px;color:#64748b" id="rhCat"></span>
        <div class="qtitle" id="rhTitle"></div>
      </div>
      <div class="actions-row">
        <div class="size-ctl">
          <button onclick="adjSize(-2)">A−</button>
          <span class="size-val" id="sizeVal">28px</span>
          <button onclick="adjSize(2)">A＋</button>
        </div>
        <button onclick="copyAnswer()">📋 コピー</button>
        <button onclick="togglePodium()" class="big">🖥 演台モード</button>
        <button onclick="togglePodium()" class="exit-podium">✕ 演台終了</button>
      </div>
    </div>
    <div class="right-body" id="rightBody">
      <div class="empty-hint">
        <h2>👈 左から質問を選択してください</h2>
        <p>キーワード検索 / Q番号直打ち / 定型文タブ から素早く呼び出せます</p>
        <p style="margin-top:24px"><span class="kbd">↑</span> <span class="kbd">↓</span> 候補移動　<span class="kbd">Enter</span> 表示　<span class="kbd">F</span> 演台モード　<span class="kbd">Esc</span> 戻る</p>
        <p style="margin-top:6px">データは Google Sheets から 5 分おきに自動同期（最終: __BUILD_TIME__）</p>
      </div>
    </div>
  </div>
</div>
<div class="kbd-hint">
  <b>ショートカット</b>：<span class="kbd">/</span> 検索  <span class="kbd">Q</span> Q#入力  <span class="kbd">↑↓</span> 候補  <span class="kbd">Enter</span> 表示  <span class="kbd">F</span> 演台ON/OFF  <span class="kbd">Esc</span> 演台終了
</div>
<script>
const QA = __QA_JSON__;
const TEMPLATES = __TEMPLATES_JSON__;
const CATS = __CATS_JSON__;
const TAG_MAP = {"answered":["green","個別回答"],"template":["orange","定型文"],"declined":["red","回答留保"],"updated":["blue","★最新情報"]};
let state = { tab:"ALL", scope:"both", query:"", selected:-1, filtered:[], answerSize:28 };
function buildTabs(){
  const tr = document.getElementById("tabRow");
  let html = '<button class="tab-btn active" data-tab="ALL">全て('+QA.length+')</button>';
  html += '<button class="tab-btn" data-tab="TPL" style="color:#fbbf24">📌定型文('+TEMPLATES.length+')</button>';
  for(const [k,label,n] of CATS){
    const short = label.length>14 ? label.substring(0,12)+"…" : label;
    html += '<button class="tab-btn" data-tab="'+k+'" title="'+label+'">'+short+'('+n+')</button>';
  }
  tr.innerHTML = html;
  tr.querySelectorAll(".tab-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      state.tab = btn.dataset.tab;
      tr.querySelectorAll(".tab-btn").forEach(b=>b.classList.toggle("active", b===btn));
      state.selected = -1;
      render();
    });
  });
}
function buildScope(){
  document.querySelectorAll(".scope-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      state.scope = btn.dataset.scope;
      document.querySelectorAll(".scope-btn").forEach(b=>b.classList.toggle("active", b===btn));
      render();
    });
  });
}
function matches(item){
  const q = state.query.trim().toLowerCase();
  if(!q) return true;
  if(state.scope==="q") return item.q.toLowerCase().includes(q);
  if(state.scope==="a") return item.a.toLowerCase().includes(q);
  return (item.q+" "+item.a).toLowerCase().includes(q);
}
function currentPool(){
  if(state.tab==="TPL") return TEMPLATES.map(t=>({id:t.id,cat:"TPL",catLabel:"定型文",q:t.title,a:t.a,tag:"template",src:"2026-04-20版 定型文"}));
  if(state.tab==="ALL") return QA;
  return QA.filter(x=>x.cat===state.tab);
}
function render(){
  let pool = currentPool();
  const list = pool.filter(matches);
  state.filtered = list;
  const area = document.getElementById("listArea");
  if(list.length===0){ area.innerHTML = '<div class="list-empty">該当なし</div>'; return; }
  let html = "";
  list.forEach((it,idx)=>{
    const tagColor = TAG_MAP[it.tag] ? TAG_MAP[it.tag][0] : "orange";
    const sel = idx===state.selected ? "selected" : "";
    const prefix = state.tab==="TPL" ? "定" : "Q";
    html += '<div class="list-item '+sel+'" data-idx="'+idx+'">'+
            '<div class="li-num">'+ prefix + it.id +'</div>'+
            '<div class="li-q">'+ escapeHtml(it.q) +'</div>'+
            '<div class="li-tag '+tagColor+'"></div>'+
            '</div>';
  });
  area.innerHTML = html;
  area.querySelectorAll(".list-item").forEach(el=>{
    el.addEventListener("click",()=>{ state.selected = parseInt(el.dataset.idx,10); render(); showSelected(); });
    el.addEventListener("dblclick",()=>{ state.selected = parseInt(el.dataset.idx,10); showSelected(); enterPodium(); });
  });
  if(state.selected>=0 && state.selected<list.length){
    const sel = area.querySelector(".list-item.selected");
    if(sel) sel.scrollIntoView({block:"nearest"});
  }
}
function escapeHtml(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function showSelected(){
  const it = state.filtered[state.selected];
  if(!it){
    document.getElementById("rightHead").style.display = "none";
    document.getElementById("rightBody").innerHTML = '<div class="empty-hint"><h2>👈 左から質問を選択してください</h2></div>';
    return;
  }
  document.getElementById("rightHead").style.display = "flex";
  document.getElementById("rhNo").textContent = (state.tab==="TPL"?"":"Q") + it.id;
  const tagInfo = TAG_MAP[it.tag] || ["orange","定型文"];
  const tagEl = document.getElementById("rhTag");
  tagEl.className = "qtag " + tagInfo[0];
  tagEl.textContent = tagInfo[1];
  document.getElementById("rhCat").textContent = it.catLabel;
  document.getElementById("rhTitle").textContent = it.q;
  let bodyHtml = '<div class="answer-box"><div class="answer-label">── 回 答 ──</div>'+
                 '<div class="answer-text">'+ escapeHtml(it.a) +'</div>';
  if(it.src) bodyHtml += '<div class="answer-src">📎 '+ escapeHtml(it.src) +'</div>';
  bodyHtml += '</div>';
  document.getElementById("rightBody").innerHTML = bodyHtml;
  document.documentElement.style.setProperty("--answer-size", state.answerSize+"px");
}
function adjSize(d){
  state.answerSize = Math.max(16, Math.min(72, state.answerSize + d));
  document.getElementById("sizeVal").textContent = state.answerSize + "px";
  document.documentElement.style.setProperty("--answer-size", state.answerSize+"px");
}
function copyAnswer(){
  const it = state.filtered[state.selected];
  if(!it) return;
  navigator.clipboard.writeText(it.a).then(()=>{
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = "✓ コピー済み";
    setTimeout(()=>{btn.textContent = orig;}, 1500);
  });
}
function togglePodium(){ document.body.classList.toggle("podium"); }
function enterPodium(){ if(!document.body.classList.contains("podium")) document.body.classList.add("podium"); }
document.addEventListener("keydown",(e)=>{
  const tag = (e.target.tagName||"").toLowerCase();
  const isInput = (tag==="input" || tag==="textarea");
  if(e.key==="Escape"){
    if(document.body.classList.contains("podium")){ document.body.classList.remove("podium"); e.preventDefault(); return; }
    if(isInput){ e.target.blur(); e.target.value=""; state.query=""; render(); return; }
  }
  if(!isInput){
    if(e.key==="/"){ e.preventDefault(); document.getElementById("searchInput").focus(); return; }
    if(e.key==="q" || e.key==="Q"){ e.preventDefault(); document.getElementById("jumpInput").focus(); return; }
    if(e.key==="f" || e.key==="F"){ e.preventDefault(); togglePodium(); return; }
    if(e.key==="+" || e.key==="="){ e.preventDefault(); adjSize(2); return; }
    if(e.key==="-" || e.key==="_"){ e.preventDefault(); adjSize(-2); return; }
  }
  if(e.key==="ArrowDown"){
    e.preventDefault();
    if(state.filtered.length===0) return;
    state.selected = Math.min(state.filtered.length-1, state.selected<0?0:state.selected+1);
    render(); showSelected();
  } else if(e.key==="ArrowUp"){
    e.preventDefault();
    if(state.filtered.length===0) return;
    state.selected = Math.max(0, state.selected-1);
    render(); showSelected();
  } else if(e.key==="Enter"){
    if(e.target.id==="jumpInput"){
      const v = e.target.value.trim();
      if(v){
        let allPool = QA.concat(TEMPLATES.map(t=>({id:t.id,cat:"TPL",catLabel:"定型文",q:t.title,a:t.a,tag:"template",src:"2026-04-20版 定型文"})));
        const target = allPool.find(it => String(it.id).toUpperCase()===v.toUpperCase());
        if(target){
          state.tab = target.cat;
          state.query = "";
          document.getElementById("searchInput").value = "";
          document.querySelectorAll(".tab-btn").forEach(b=>b.classList.toggle("active", b.dataset.tab===target.cat));
          render();
          const idx = state.filtered.findIndex(x=>x.id===target.id && x.cat===target.cat);
          if(idx>=0){ state.selected = idx; render(); showSelected(); }
        } else {
          e.target.style.background="#fee2e2";
          setTimeout(()=>{e.target.style.background="";},600);
        }
        e.target.value = "";
        e.target.blur();
      }
    } else {
      if(state.selected>=0) showSelected();
    }
  }
});
document.getElementById("searchInput").addEventListener("input",(e)=>{
  state.query = e.target.value;
  state.selected = -1;
  render();
});
function parseInitial(){
  const p = new URLSearchParams(location.search);
  if(p.get("podium")==="1") document.body.classList.add("podium");
}
buildTabs();
buildScope();
parseInitial();
render();
</script>
</body>
</html>
"""


def build_inner_html(data, sources) -> tuple[str, int]:
    total = sum(len(v["items"]) for v in data.values())
    qa_items = []
    for cat_key, val in data.items():
        for display_id, q, a, tag in val["items"]:
            qa_items.append({
                "id": display_id,
                "cat": cat_key,
                "catLabel": val["label"],
                "q": q,
                "a": a,
                "tag": tag,
                "src": sources.get(display_id, ""),
            })

    template_items = [{"id": t[0], "title": t[1], "a": t[2]} for t in TEMPLATES]
    cats = [(k, v["label"], len(v["items"])) for k, v in data.items() if v["items"]]
    build_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST")

    html = (HTML_WRAPPER_TEMPLATE
            .replace("__QA_JSON__",        json.dumps(qa_items, ensure_ascii=False))
            .replace("__TEMPLATES_JSON__", json.dumps(template_items, ensure_ascii=False))
            .replace("__CATS_JSON__",      json.dumps(cats, ensure_ascii=False))
            .replace("__BUILD_TIME__",     build_time)
            .replace("__TOTAL__",          str(total))
            .replace("__TPL__",            str(len(TEMPLATES))))
    return html, total


def wrap_encrypted(inner_html: str) -> str:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    key = kdf.derive(PASSWORD.encode("utf-8"))
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(iv, inner_html.encode("utf-8"), None)

    payload = {
        "salt": base64.b64encode(salt).decode(),
        "iv":   base64.b64encode(iv).decode(),
        "ct":   base64.b64encode(ct).decode(),
        "iter": ITERATIONS,
    }

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
.sync{background:#0f172a;border-left:3px solid #22c55e;padding:8px 12px;margin-top:14px;font-size:11px;color:#94a3b8;border-radius:4px}
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
  <div class="sync">🔄 Google Sheets から5分おきに自動同期<br>最終同期: __BUILD_TIME__</div>
  <div class="hint">
    パスワードをお持ちでない方はご担当者までお問い合わせください。<br>
    本サイトの内容は暗号化されており、正しいパスワードを入力するまで閲覧できません。
  </div>
  <div class="loading" style="display:none" id="loading">
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
  document.getElementById("loading").style.display = "block";
  document.getElementById("bar").style.width = "30%";
  try {
    const enc = new TextEncoder();
    const keyMaterial = await crypto.subtle.importKey("raw", enc.encode(pw), {name:"PBKDF2"}, false, ["deriveKey"]);
    document.getElementById("bar").style.width = "55%";
    const key = await crypto.subtle.deriveKey(
      {name:"PBKDF2", salt: b64ToBytes(PAYLOAD.salt), iterations: PAYLOAD.iter, hash:"SHA-256"},
      keyMaterial, {name:"AES-GCM", length:256}, false, ["decrypt"]
    );
    document.getElementById("bar").style.width = "80%";
    const plain = await crypto.subtle.decrypt(
      {name:"AES-GCM", iv: b64ToBytes(PAYLOAD.iv)}, key, b64ToBytes(PAYLOAD.ct)
    );
    document.getElementById("bar").style.width = "100%";
    const html = new TextDecoder("utf-8").decode(plain);
    document.open(); document.write(html); document.close();
  } catch(e) {
    btn.disabled = false;
    btn.textContent = "🔓 アクセス";
    err.textContent = "パスワードが違います";
    document.getElementById("loading").style.display = "none";
    document.getElementById("pw").select();
  }
}
</script>
</body>
</html>
"""
    build_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST")
    return wrapper.replace("__PAYLOAD__", json.dumps(payload)).replace("__BUILD_TIME__", build_time)


def main():
    print(">>> Sheets CSV 取得")
    csv_text = fetch_sheet_csv()
    print(f"    {len(csv_text):,} bytes")

    print(">>> パース")
    data, sources = parse_qa(csv_text)
    for k, v in data.items():
        print(f"    {k}: {len(v['items'])}件")

    print(">>> 内側HTML生成")
    inner_html, total = build_inner_html(data, sources)
    print(f"    平文 {len(inner_html):,} bytes / {total}問")

    print(">>> 暗号化ラッパー")
    final_html = wrap_encrypted(inner_html)

    # 変更検知：SHA256が同じならスキップ
    new_hash = hashlib.sha256(inner_html.encode("utf-8")).hexdigest()
    hash_file = os.path.join(ROOT, ".last-content-hash")
    prev_hash = ""
    if os.path.exists(hash_file):
        with open(hash_file, encoding="utf-8") as f:
            prev_hash = f.read().strip()

    with open(OUT_HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(final_html)
    with open(hash_file, "w", encoding="utf-8") as f:
        f.write(new_hash)

    if new_hash == prev_hash:
        print(f">>> 変更なし（{new_hash[:12]}...）")
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("changed=false\n")
    else:
        print(f">>> 変更あり {prev_hash[:12] or 'new'}... → {new_hash[:12]}...")
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write("changed=true\n")

    print(f">>> 出力 {OUT_HTML} ({len(final_html):,} bytes)")


if __name__ == "__main__":
    main()
