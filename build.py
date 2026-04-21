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

# A分類 (Sheet C列) をタブ化する際の順序とキー (2026-04-20 会議指示)
A_CLASS_ORDER = [
    ("個別回答",                        "IND",  "📝 個別回答"),
    ("定型文①調査中につき回答不能",   "TPL1", "① 調査中"),
    ("定型文②事業への影響不透明",     "TPL2", "② 事業影響"),
    ("定型文③業績への影響不透明",     "TPL3", "③ 業績影響"),
    ("定型文④役員の責任",              "TPL4", "④ 役員責任"),
    ("定型文⑤再発防止",                "TPL5", "⑤ 再発防止"),
    ("定型文⑥法的な責任分担",          "TPL6", "⑥ 法的責任"),
    ("定型文⑦プライバシー保護",        "TPL7", "⑦ プライバシー"),
    ("社外役員回答",                   "OUT",  "🎓 社外役員"),
    ("個別的",                          "IND2", "個別的"),
]
A_CLASS_LOOKUP = {name: (key, short) for name, key, short in A_CLASS_ORDER}

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
    """A分類(C列)をカテゴリキーとして分類する。"""
    data = {key: {"label": f"{short}", "items": []} for _, key, short in A_CLASS_ORDER}
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
        if not q or not a:
            continue

        tag = classify_tag(a_cls)
        key_short = A_CLASS_LOOKUP.get(a_cls)
        if not key_short:
            # 未知のA分類は 個別回答 へフォールバック
            key_short = ("IND", "📝 個別回答")
        cat_key = key_short[0]

        if no >= 201:
            display_id = f"F{no - 200}"
        else:
            display_id = str(no)

        data[cat_key]["items"].append((display_id, q, a, tag))
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
body{font-family:"Noto Sans JP","Hiragino Sans","Meiryo",sans-serif;background:#0f172a;color:#e2e8f0;font-size:16px;display:flex;flex-direction:column}
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
.tab-btn{padding:10px 12px;background:transparent;color:#94a3b8;border:none;border-bottom:3px solid transparent;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;white-space:nowrap}
.tab-btn.active{color:#fff;border-bottom-color:#3b82f6}
.tab-btn:hover{color:#e2e8f0}
.tpl-row{display:none;padding:5px 8px;background:#0f172a;border-bottom:1px solid #334155;flex-shrink:0}
.tpl-row.on{display:flex}
.tpl-btn{width:100%;padding:7px 10px;background:#3b0764;color:#fbbf24;border:2px solid #7c3aed;border-radius:6px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;text-align:left;font-family:inherit}
.tpl-btn:hover{background:#581c87}
.tpl-btn.active{background:#7c3aed;color:#fff;border-color:#fbbf24}
.list-area{flex:1;overflow-y:auto;padding:6px 8px 40px}
.list-area::-webkit-scrollbar{width:8px}
.list-area::-webkit-scrollbar-thumb{background:#475569;border-radius:4px}
.list-item{padding:12px 14px;margin-bottom:4px;border-radius:6px;cursor:pointer;display:flex;gap:10px;align-items:flex-start;border:2px solid transparent;background:#0f172a;transition:background .1s;flex-wrap:wrap;position:relative}
.list-item:hover{background:#27344a}
.list-item.selected{background:#1e40af;border-color:#60a5fa}
.list-item.selected .li-num{background:#dc2626}
.list-item.checked{background:#0f3d26;border-color:#22c55e}
.list-item.checked.selected{background:#1e40af;border-color:#60a5fa}
.li-chk{flex-shrink:0;width:22px;height:22px;border:2px solid #64748b;border-radius:4px;margin-top:2px;display:flex;align-items:center;justify-content:center;background:#1e293b;font-size:14px;font-weight:900;color:transparent}
.list-item.checked .li-chk{background:#22c55e;border-color:#22c55e;color:#0f172a}
.list-item.checked .li-chk::after{content:"✓"}
.li-order{position:absolute;top:6px;right:8px;min-width:18px;height:18px;padding:0 5px;background:#dc2626;color:#fff;border-radius:9px;font-size:10px;font-weight:700;display:none;align-items:center;justify-content:center}
.list-item.checked .li-order{display:flex}
.li-num{flex-shrink:0;min-width:54px;height:26px;padding:0 8px;background:#334155;color:#fff;border-radius:4px;font-size:13px;font-weight:700;display:flex;align-items:center;justify-content:center}
.li-q{flex:1;font-size:15px;line-height:1.55;color:#e2e8f0;font-weight:500;word-break:break-word;min-width:0}
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
.answer-box{background:#fff;border:2px solid #cbd5e1;border-radius:12px;padding:36px 44px;box-shadow:0 4px 16px rgba(0,0,0,.08);max-width:1200px;margin:0 auto 20px}
.answer-box.idx-1{border-color:#3b82f6;border-width:3px}
.answer-box.idx-2{border-color:#8b5cf6;border-width:3px}
.answer-box.idx-3{border-color:#f59e0b;border-width:3px}
.answer-box.idx-4{border-color:#ef4444;border-width:3px}
.answer-idx{display:inline-block;background:#dc2626;color:#fff;border-radius:50%;width:30px;height:30px;line-height:30px;text-align:center;font-size:16px;font-weight:900;margin-right:10px;vertical-align:middle}
.remove-card{float:right;background:transparent;border:2px solid #cbd5e1;color:#64748b;border-radius:6px;padding:4px 10px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.remove-card:hover{background:#fee2e2;border-color:#ef4444;color:#991b1b}
.card-q{font-size:16px;font-weight:700;color:#0f172a;line-height:1.6;margin-bottom:10px}
body.podium .card-q{font-size:22px}
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
.kbd-toggle{position:fixed;bottom:10px;left:10px;width:36px;height:36px;background:#1e293b;color:#cbd5e1;border:2px solid #475569;border-radius:50%;font-size:16px;cursor:pointer;z-index:201;font-family:inherit;display:flex;align-items:center;justify-content:center}
.kbd-toggle:hover{background:#334155;color:#fff}
body.podium .kbd-toggle{display:none}
.kbd-hint{position:fixed;bottom:54px;left:14px;background:rgba(15,23,42,.92);color:#cbd5e1;padding:10px 14px;border-radius:6px;font-size:11px;z-index:200;line-height:1.8;pointer-events:none;border:1px solid #475569}
body.podium .kbd-hint{display:none !important}
.sync-badge{background:#22c55e;color:#fff;font-size:10px;padding:2px 8px;border-radius:4px;margin-left:8px;font-weight:700}
.closing-dock{position:fixed;right:14px;bottom:14px;background:linear-gradient(135deg,#fbbf24,#f59e0b);color:#451a03;padding:16px 22px;border-radius:12px;font-size:15px;font-weight:700;line-height:1.75;z-index:250;box-shadow:0 6px 20px rgba(0,0,0,.45);border:3px solid #fef3c7;max-width:400px;letter-spacing:.02em;cursor:move;user-select:none}
.closing-dock .cd-label{font-size:10px;letter-spacing:.15em;color:#78350f;font-weight:900;margin-bottom:6px}
.closing-dock .cd-line{color:#0f172a;font-size:16px}
body.podium .closing-dock{font-size:20px;padding:22px 30px;max-width:560px;border-width:4px}
body.podium .closing-dock .cd-line{font-size:22px;line-height:1.85}
body.podium .closing-dock .cd-label{font-size:12px}
.counter-chip{position:fixed;top:14px;right:14px;background:#1e293b;color:#fbbf24;padding:6px 14px;border-radius:999px;font-size:13px;font-weight:700;z-index:120;border:2px solid #fbbf24;display:none;gap:10px;align-items:center}
.counter-chip.on{display:flex}
.counter-chip .clear-all{background:#dc2626;color:#fff;border:none;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.counter-chip .clear-all:hover{background:#b91c1c}
.mode-row{display:flex;background:#0f172a;padding:6px 6px;gap:4px;border-bottom:1px solid #334155;flex-shrink:0}
.mode-btn{flex:1;padding:10px;background:#1e293b;color:#94a3b8;border:2px solid transparent;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}
.mode-btn.active{background:#dc2626;color:#fff;border-color:#fbbf24}
.mode-btn:hover:not(.active){background:#27344a;color:#e2e8f0}
.mode-btn .mode-badge{display:inline-block;font-size:10px;margin-left:6px;opacity:.7}
.quick-btn{display:block;width:100%;padding:10px 12px;background:#7c3aed;color:#fff;border:2px solid #a78bfa;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;margin-bottom:6px}
.quick-btn:hover{background:#6d28d9}
.quick-btn.ai{background:#0891b2;border-color:#22d3ee}
.quick-btn.ai:hover{background:#0e7490}
.quick-area{padding:8px 10px;background:#0f172a;border-top:1px solid #334155;flex-shrink:0}
.ai-paste-box{background:#fff;border:3px dashed #0891b2;border-radius:12px;padding:20px 24px;max-width:1200px;margin:0 auto 20px}
.ai-paste-box textarea{width:100%;min-height:180px;padding:14px;border:2px solid #cbd5e1;border-radius:8px;font-size:16px;font-family:inherit;line-height:1.7;color:#0f172a;resize:vertical;outline:none}
.ai-paste-box textarea:focus{border-color:#0891b2}
.ai-paste-box .ai-q{width:100%;min-height:70px;font-size:15px;font-weight:700;margin-bottom:10px}
.ai-paste-box label{display:block;font-size:12px;font-weight:700;color:#64748b;letter-spacing:.1em;margin-bottom:6px;margin-top:12px}
.ai-paste-box .label-row{display:flex;align-items:center;gap:10px;margin-top:12px;margin-bottom:6px}
.ai-paste-box .label-row label{margin:0;flex:0 0 auto}
.ai-paste-box .mic-btn{background:#fff;color:#0891b2;border:2px solid #0891b2;padding:6px 14px;border-radius:999px;font-size:12px;font-weight:800;cursor:pointer;font-family:inherit;display:inline-flex;align-items:center;gap:6px;white-space:nowrap}
.ai-paste-box .mic-btn:hover{background:#cffafe}
.ai-paste-box .mic-btn.rec{background:#dc2626;color:#fff;border-color:#fbbf24;animation:recpulse 1s infinite}
.ai-paste-box .mic-btn .mic-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:currentColor}
.ai-paste-box .mic-status{font-size:11px;color:#64748b;margin-left:auto}
.ai-paste-box .mic-btn.rec .mic-dot{background:#fff}
@keyframes recpulse{0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,.8)}50%{box-shadow:0 0 0 8px rgba(220,38,38,0)}}
.ai-paste-box .row{display:flex;gap:8px;margin-top:12px;align-items:center}
.ai-paste-box .row button{background:#0891b2;color:#fff;border:none;padding:8px 16px;border-radius:6px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit}
.ai-paste-box .row button.secondary{background:#475569}
.ai-paste-box .interim{color:#64748b;font-style:italic}
body.podium .ai-paste-box{border-style:solid}
.office-slide{background:linear-gradient(135deg,#fef3c7,#fde68a);border:4px solid #f59e0b;border-radius:14px;padding:60px 50px;text-align:center;max-width:1200px;margin:0 auto 20px}
.office-slide h1{font-size:48px;color:#7c2d12;margin-bottom:24px;font-weight:900;letter-spacing:.05em}
.office-slide p{font-size:20px;color:#451a03;line-height:1.8;margin-bottom:16px;font-weight:700}
body.podium .office-slide h1{font-size:72px}
body.podium .office-slide p{font-size:28px}
</style>
</head>
<body>
<header>
  <div>
    <div class="title">ベステラ㈱ 株主総会 <span style="color:#f87171">演台用Q&amp;A</span><span class="sync-badge" title="Google Sheets から自動同期">🔄 SHEETS同期</span></div>
    <div class="meta">2026年4月23日 株主総会 ／ データ同期 __BUILD_TIME__ ／ 全__TOTAL__問＋定型文__TPL__件</div>
  </div>
  <div class="actions">
    <button onclick="clearAllChecks()" id="clearAllBtnHdr" title="選択を全て解除">✕ 全解除</button>
    <button onclick="togglePodium()" class="primary" title="演台モード (F)">🖥 演台モード <span class="kbd">F</span></button>
  </div>
</header>
<div class="main">
  <div class="pane-left">
    <div class="mode-row">
      <button class="mode-btn active" data-mode="accident">🚨 事故Q&A<span class="mode-badge" id="modeAccidentCount"></span></button>
      <button class="mode-btn" data-mode="general">💬 一般Q&A<span class="mode-badge" id="modeGeneralCount"></span></button>
    </div>
    <div class="search-area">
      <div class="search-row">
        <input type="text" id="searchInput" placeholder="🔍 キーワード検索" autocomplete="off">
      </div>
      <div class="scope-row">
        <button class="scope-btn active" data-scope="both">質問＋回答</button>
        <button class="scope-btn" data-scope="q">質問のみ</button>
        <button class="scope-btn" data-scope="a">回答のみ</button>
      </div>
    </div>
    <div class="tab-row" id="tabRow"></div>
    <div class="tpl-row" id="tplRow">
      <button class="tpl-btn" id="tplBtn" data-tab="TPL">📌 定型文リファレンス（T1〜TG 計8件）</button>
    </div>
    <div class="list-area" id="listArea"></div>
    <div class="quick-area">
      <button class="quick-btn" id="btnOffice">🏢 事務局に相談（画面に表示）</button>
      <button class="quick-btn ai" id="btnAiPaste">🤖 AI回答をペースト（想定外質問用）</button>
    </div>
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
        <h2>👈 左の □ にチェックを入れてください（最大4件）</h2>
        <p>キーワード検索 / Q番号直打ち / 定型文タブ から素早く呼び出せます</p>
        <p style="margin-top:24px"><span class="kbd">↑</span> <span class="kbd">↓</span> 候補移動　<span class="kbd">Space/Enter</span> ✓トグル　<span class="kbd">F</span> 演台モード　<span class="kbd">Esc</span> 戻る</p>
        <p style="margin-top:6px">データは Google Sheets から 5 分おきに自動同期（最終: __BUILD_TIME__）</p>
      </div>
    </div>
  </div>
</div>
<button class="kbd-toggle" id="kbdToggle" title="ショートカット一覧">⌨</button>
<div class="kbd-hint" id="kbdHint" style="display:none">
  <b>ショートカット</b><br>
  <span class="kbd">/</span> 検索  <span class="kbd">↑↓</span> 候補  <span class="kbd">Space/Enter</span> ✓<br>
  <span class="kbd">F</span> 演台ON/OFF  <span class="kbd">Esc</span> 閉じる
</div>
<div class="counter-chip" id="counterChip"><span>選択中 <span id="counterNum">0</span> / 4</span><button class="clear-all" id="clearAllBtn" title="全てのチェックを解除">✕ 全解除</button></div>
<div class="closing-dock" id="closingDock" title="ドラッグで移動">
  <div class="cd-label">📢 回答の締めくくり（読み上げ）</div>
  <div class="cd-line">以上、ご回答申し上げました。</div>
  <div class="cd-line">他にご質問はございませんでしょうか？</div>
</div>
<script>
const QA = __QA_JSON__;
const TEMPLATES = __TEMPLATES_JSON__;
const CATS = __CATS_JSON__;
const GENERAL = __GENERAL_JSON__;
const GENERAL_CATS = __GENERAL_CATS_JSON__;
const TAG_MAP = {"answered":["green","個別回答"],"template":["orange","定型文"],"declined":["red","回答留保"],"updated":["blue","★最新情報"]};
const MAX_CHECKED = 4;
const SPECIAL = {
  OFFICE: {id:"OFFICE", cat:"SP", catLabel:"特別スライド", q:"事務局に相談します", a:"", tag:"declined", src:"", special:"office"},
};
let state = { tab:"ALL", scope:"both", query:"", selected:-1, filtered:[], answerSize:28, checked:[], mode:"accident", aiQ:"", aiA:"" };
function keyOf(it){ return (it.cat||"") + ":" + it.id + (it.mode==="general"?":G":""); }
function findByKey(k){
  if(k==="SP:OFFICE") return SPECIAL.OFFICE;
  if(k==="SP:AI") return {id:"AI", cat:"SP", catLabel:"AI即席回答", q:state.aiQ || "（質問を入力してください）", a:state.aiA || "", tag:"updated", src:"AI生成（当日）", special:"ai"};
  const allPool = QA.concat(
    TEMPLATES.map(t=>({id:t.id,cat:"TPL",catLabel:"定型文",q:t.title,a:t.a,tag:"template",src:"2026-04-20版 定型文"})),
    GENERAL.map(g=>Object.assign({}, g, {mode:"general"}))
  );
  return allPool.find(it => keyOf(it)===k) || null;
}
function buildTabs(){
  const tr = document.getElementById("tabRow");
  const tplRow = document.getElementById("tplRow");
  let html = '';
  if(state.mode === "accident"){
    html += '<button class="tab-btn active" data-tab="ALL">全て('+QA.length+')</button>';
    for(const [k,label,n] of CATS){
      if(n === 0) continue;
      const short = label.length>14 ? label.substring(0,12)+"…" : label;
      html += '<button class="tab-btn" data-tab="'+k+'" title="'+label+' ('+n+'件)">'+short+'('+n+')</button>';
    }
    tplRow.classList.add("on");
  } else {
    tplRow.classList.remove("on");
    html += '<button class="tab-btn active" data-tab="ALL">全て('+GENERAL.length+')</button>';
    for(const [k,label,n] of GENERAL_CATS){
      if(n === 0) continue;
      const short = label.length>12 ? label.substring(0,11)+"…" : label;
      html += '<button class="tab-btn" data-tab="'+k+'" title="'+label+' ('+n+'件)">'+short+'('+n+')</button>';
    }
  }
  tr.innerHTML = html;
  tr.querySelectorAll(".tab-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      state.tab = btn.dataset.tab;
      tr.querySelectorAll(".tab-btn").forEach(b=>b.classList.toggle("active", b===btn));
      document.getElementById("tplBtn").classList.remove("active");
      state.selected = -1;
      render();
    });
  });
  // 定型文専用ボタン
  const tplBtn = document.getElementById("tplBtn");
  tplBtn.classList.toggle("active", state.tab === "TPL");
  tplBtn.onclick = () => {
    state.tab = "TPL";
    tr.querySelectorAll(".tab-btn").forEach(b=>b.classList.remove("active"));
    tplBtn.classList.add("active");
    state.selected = -1;
    render();
  };
  document.getElementById("modeAccidentCount").textContent = "("+(QA.length + TEMPLATES.length)+")";
  document.getElementById("modeGeneralCount").textContent = "("+GENERAL.length+")";
}
function buildModes(){
  document.querySelectorAll(".mode-btn").forEach(btn=>{
    btn.addEventListener("click",()=>{
      state.mode = btn.dataset.mode;
      state.tab = "ALL";
      state.selected = -1;
      document.querySelectorAll(".mode-btn").forEach(b=>b.classList.toggle("active", b===btn));
      buildTabs();
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
  if(state.mode === "general"){
    const pool = GENERAL.map(g=>Object.assign({}, g, {mode:"general"}));
    if(state.tab==="ALL") return pool;
    return pool.filter(x=>x.cat===state.tab);
  }
  if(state.tab==="TPL") return TEMPLATES.map(t=>({id:t.id,cat:"TPL",catLabel:"定型文",q:t.title,a:t.a,tag:"template",src:"2026-04-20版 定型文"}));
  if(state.tab==="ALL") return QA;
  return QA.filter(x=>x.cat===state.tab);
}
function render(){
  let pool = currentPool();
  const list = pool.filter(matches);
  state.filtered = list;
  const area = document.getElementById("listArea");
  if(list.length===0){
    area.innerHTML = '<div class="list-empty">該当なし</div>';
    renderRight(); return;
  }
  let html = "";
  list.forEach((it,idx)=>{
    const tagColor = TAG_MAP[it.tag] ? TAG_MAP[it.tag][0] : "orange";
    const sel = idx===state.selected ? "selected" : "";
    const checkIdx = state.checked.indexOf(keyOf(it));
    const chk = checkIdx >= 0 ? "checked" : "";
    const order = checkIdx >= 0 ? (checkIdx+1) : "";
    const prefix = state.tab==="TPL" ? "定" : "Q";
    const tipTxt = "【回答】" + (it.a||"").replace(/\s+/g," ");
    html += '<div class="list-item '+sel+' '+chk+'" data-idx="'+idx+'" data-key="'+keyOf(it)+'" title="'+ escapeAttr(tipTxt) +'">'+
            '<div class="li-chk" data-chk="1"></div>'+
            '<div class="li-num">'+ prefix + it.id +'</div>'+
            '<div class="li-q">'+ escapeHtml(it.q) +'</div>'+
            '<div class="li-tag '+tagColor+'"></div>'+
            '<div class="li-order">'+ order +'</div>'+
            '</div>';
  });
  area.innerHTML = html;
  area.querySelectorAll(".list-item").forEach(el=>{
    el.addEventListener("click",(ev)=>{
      state.selected = parseInt(el.dataset.idx,10);
      toggleCheck(el.dataset.key);
    });
    el.addEventListener("dblclick",()=>{
      const k = el.dataset.key;
      state.checked = [k];
      state.selected = parseInt(el.dataset.idx,10);
      render(); renderRight(); enterPodium();
    });
  });
  if(state.selected>=0 && state.selected<list.length){
    const sel = area.querySelector(".list-item.selected");
    if(sel) sel.scrollIntoView({block:"nearest"});
  }
  renderRight();
}
function escapeAttr(s){ return s.replace(/"/g,"&quot;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function toggleCheck(k){
  const i = state.checked.indexOf(k);
  if(i>=0){
    state.checked.splice(i,1);
  } else {
    if(state.checked.length >= MAX_CHECKED){
      toastLimit();
      render();
      return;
    }
    state.checked.push(k);
  }
  render();
}
let _toastTimer=null;
function toastLimit(){
  const chip = document.getElementById("counterChip");
  chip.style.background = "#dc2626";
  chip.style.color = "#fff";
  setTimeout(()=>{ chip.style.background=""; chip.style.color=""; }, 700);
}
function escapeHtml(s){ return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
function renderRight(){
  const head = document.getElementById("rightHead");
  const body = document.getElementById("rightBody");
  const chip = document.getElementById("counterChip");
  document.getElementById("counterNum").textContent = state.checked.length;
  chip.classList.toggle("on", state.checked.length>0);
  const items = state.checked.map(findByKey).filter(Boolean);
  if(items.length === 0){
    head.style.display = "none";
    body.innerHTML = '<div class="empty-hint"><h2>👈 左の □ にチェックを入れてください（最大4件）</h2><p>クリックで✓／もう一度クリックで解除　・　ダブルクリックでその1件だけ選んで演台モード</p></div>';
    return;
  }
  head.style.display = "flex";
  if(items.length === 1){
    const it = items[0];
    document.getElementById("rhNo").textContent = (it.cat==="TPL"?"":"Q") + it.id;
    const tagInfo = TAG_MAP[it.tag] || ["orange","定型文"];
    const tagEl = document.getElementById("rhTag");
    tagEl.className = "qtag " + tagInfo[0];
    tagEl.textContent = tagInfo[1];
    document.getElementById("rhCat").textContent = it.catLabel || "";
    document.getElementById("rhTitle").textContent = it.q;
  } else {
    document.getElementById("rhNo").textContent = items.length + "件";
    document.getElementById("rhTag").className = "qtag blue";
    document.getElementById("rhTag").textContent = "複数選択";
    document.getElementById("rhCat").textContent = "";
    document.getElementById("rhTitle").textContent = items.map(it=> (it.cat==="TPL"?"定":"Q")+it.id).join(" / ");
  }
  let html = "";
  items.forEach((it, idx)=>{
    const n = idx+1;
    const showIdx = items.length > 1;
    if(it.special === "office"){
      html += '<div class="office-slide">'+
              '<button class="remove-card" data-k="'+keyOf(it)+'">✕ 外す</button>'+
              (showIdx ? '<span class="answer-idx">'+n+'</span>' : '')+
              '<h1>🏢 事務局に相談します</h1>'+
              '<p>誠に恐れ入りますが、この件につきましては、<br>事務局とも相談の上、改めてご回答申し上げます。</p>'+
              '<p style="margin-top:28px;font-size:18px;color:#78350f">― お時間を頂戴いたします。―</p>'+
              '</div>';
      return;
    }
    if(it.special === "ai"){
      html += '<div class="ai-paste-box">'+
              '<button class="remove-card" data-k="'+keyOf(it)+'">✕ 外す</button>'+
              (showIdx ? '<span class="answer-idx">'+n+'</span>' : '')+
              '<div class="label-row">'+
                '<label style="margin:0">🎤 受けた質問（マイクで録音 or 手入力）</label>'+
                '<button id="micBtn" class="mic-btn" type="button"><span class="mic-dot"></span><span id="micLabel">録音開始</span></button>'+
                '<span class="mic-status" id="micStatus"></span>'+
              '</div>'+
              '<textarea id="aiQInput" class="ai-q" placeholder="マイクボタンで録音すると、リアルタイムで文字起こしされます。手入力も可。">'+ escapeHtml(state.aiQ) +'</textarea>'+
              '<label>🤖 AI回答（Claude 等で作成した回答をペースト）</label>'+
              '<textarea id="aiAInput" placeholder="ここに回答をペーストしてください。そのまま表示されます。">'+ escapeHtml(state.aiA) +'</textarea>'+
              '<div class="row">'+
                '<button id="aiApply">✅ 表示を更新</button>'+
                '<button id="aiClear" class="secondary">クリア</button>'+
                '<span style="font-size:11px;color:#64748b;margin-left:auto">'+ (state.aiA.length) +'文字</span>'+
              '</div>';
      if(state.aiA){
        html += '<div style="margin-top:20px;border-top:2px solid #e2e8f0;padding-top:20px">'+
                '<div class="card-q"><span class="qno" style="font-size:14px;padding:2px 10px;margin-right:8px;background:#0891b2">AI</span>'+ escapeHtml(state.aiQ || "（質問未入力）") +'</div>'+
                '<div class="answer-label">── 回 答 ──</div>'+
                '<div class="answer-text">'+ escapeHtml(state.aiA) +'</div>'+
                '</div>';
      }
      html += '</div>';
      return;
    }
    const prefix = it.cat==="TPL" ? "定" : "Q";
    html += '<div class="answer-box idx-'+n+'">'+
            '<button class="remove-card" data-k="'+keyOf(it)+'">✕ 外す</button>'+
            (showIdx ? '<span class="answer-idx">'+n+'</span>' : '')+
            '<div class="card-q"><span class="qno" style="font-size:14px;padding:2px 10px;margin-right:8px">'+ prefix + it.id +'</span>'+ escapeHtml(it.q) +'</div>'+
            '<div class="answer-label">── 回 答 ──</div>'+
            '<div class="answer-text">'+ escapeHtml(it.a) +'</div>';
    if(it.src) html += '<div class="answer-src">📎 '+ escapeHtml(it.src) +'</div>';
    html += '</div>';
  });
  body.innerHTML = html;
  body.querySelectorAll(".remove-card").forEach(btn=>{
    btn.addEventListener("click",(ev)=>{
      ev.stopPropagation();
      const k = btn.dataset.k;
      const i = state.checked.indexOf(k);
      if(i>=0){ state.checked.splice(i,1); render(); }
    });
  });
  const aiApply = document.getElementById("aiApply");
  if(aiApply){
    aiApply.addEventListener("click",()=>{
      state.aiQ = document.getElementById("aiQInput").value;
      state.aiA = document.getElementById("aiAInput").value;
      renderRight();
    });
    document.getElementById("aiClear").addEventListener("click",()=>{
      state.aiQ=""; state.aiA="";
      if(_mic.running){ try{ _mic.rec.stop(); }catch(e){} }
      renderRight();
    });
    // マイク（Web Speech API）
    const micBtn = document.getElementById("micBtn");
    if(micBtn){
      micBtn.addEventListener("click",()=>toggleMic());
      if(_mic.running){
        micBtn.classList.add("rec");
        document.getElementById("micLabel").textContent = "録音停止";
      }
      const st = document.getElementById("micStatus");
      if(st){
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if(!SR) st.textContent = "⚠ このブラウザは未対応（Chrome/Edge推奨）";
        else st.textContent = _mic.running ? "● 録音中..." : "（Chrome/Edge で動作）";
      }
    }
    // Qテキストエリアへの手入力も state に同期
    document.getElementById("aiQInput").addEventListener("input",(e)=>{
      _mic.manualBase = e.target.value;
      state.aiQ = e.target.value;
    });
  }
  document.documentElement.style.setProperty("--answer-size", state.answerSize+"px");
}
function clearAllChecks(){
  if(state.checked.length===0) return;
  state.checked = [];
  render();
}
const _mic = { rec:null, running:false, finalText:"", manualBase:"" };
function toggleMic(){
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR){ alert("このブラウザは音声認識に対応していません。\nChrome または Edge でお試しください。"); return; }
  const qEl = document.getElementById("aiQInput");
  const micBtn = document.getElementById("micBtn");
  const micLabel = document.getElementById("micLabel");
  const micStatus = document.getElementById("micStatus");
  if(_mic.running){ try{ _mic.rec.stop(); }catch(e){} return; }
  _mic.finalText = qEl.value || "";
  _mic.manualBase = _mic.finalText;
  _mic.rec = new SR();
  _mic.rec.lang = "ja-JP";
  _mic.rec.continuous = true;
  _mic.rec.interimResults = true;
  _mic.rec.onresult = (ev)=>{
    let interim = "";
    for(let i=ev.resultIndex; i<ev.results.length; i++){
      const r = ev.results[i];
      const t = r[0].transcript;
      if(r.isFinal){
        const sep = (_mic.finalText && !_mic.finalText.endsWith("\n") && !_mic.finalText.endsWith("。")) ? " " : "";
        _mic.finalText += sep + t;
      } else {
        interim += t;
      }
    }
    const qLive = document.getElementById("aiQInput");
    if(qLive) qLive.value = _mic.finalText + (interim ? "（" + interim + "）" : "");
    state.aiQ = _mic.finalText;
    const sEl = document.getElementById("micStatus");
    if(sEl) sEl.textContent = "● 録音中..." + (interim ? " " + interim.slice(-20) : "");
  };
  _mic.rec.onerror = (e)=>{
    console.warn("speech error", e);
    const sEl = document.getElementById("micStatus");
    if(sEl) sEl.textContent = "⚠ " + (e.error || "error");
  };
  _mic.rec.onend = ()=>{
    _mic.running = false;
    const b = document.getElementById("micBtn");
    const lb = document.getElementById("micLabel");
    const st = document.getElementById("micStatus");
    if(b){ b.classList.remove("rec"); }
    if(lb){ lb.textContent = "録音開始"; }
    if(st){ st.textContent = "（停止中／もう一度押すと再開）"; }
    state.aiQ = _mic.finalText;
    const qLive = document.getElementById("aiQInput");
    if(qLive) qLive.value = _mic.finalText;
  };
  try {
    _mic.rec.start();
    _mic.running = true;
    micBtn.classList.add("rec");
    micLabel.textContent = "録音停止";
    if(micStatus) micStatus.textContent = "● 録音中...";
  } catch(err){
    console.warn(err);
    if(micStatus) micStatus.textContent = "⚠ 起動失敗: " + err.message;
  }
}
function pushSpecial(k){
  const i = state.checked.indexOf(k);
  if(i>=0){ state.checked.splice(i,1); render(); return; }
  if(state.checked.length >= MAX_CHECKED){ toastLimit(); return; }
  state.checked.push(k);
  render();
}
function showSelected(){ renderRight(); }
function adjSize(d){
  state.answerSize = Math.max(16, Math.min(72, state.answerSize + d));
  document.getElementById("sizeVal").textContent = state.answerSize + "px";
  document.documentElement.style.setProperty("--answer-size", state.answerSize+"px");
}
function copyAnswer(){
  const items = state.checked.map(findByKey).filter(Boolean);
  if(items.length===0) return;
  const text = items.map((it,i)=>{
    const prefix = it.cat==="TPL" ? "定" : "Q";
    const hd = items.length>1 ? `【${i+1}】${prefix}${it.id} ${it.q}\n` : "";
    return hd + it.a;
  }).join("\n\n――――――\n\n") + "\n\n以上、ご回答申し上げました。\n他にご質問はございませんでしょうか？";
  navigator.clipboard.writeText(text).then(()=>{
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
    if(e.key==="f" || e.key==="F"){ e.preventDefault(); togglePodium(); return; }
    if(e.key==="+" || e.key==="="){ e.preventDefault(); adjSize(2); return; }
    if(e.key==="-" || e.key==="_"){ e.preventDefault(); adjSize(-2); return; }
  }
  if(e.key==="ArrowDown"){
    e.preventDefault();
    if(state.filtered.length===0) return;
    state.selected = Math.min(state.filtered.length-1, state.selected<0?0:state.selected+1);
    render();
  } else if(e.key==="ArrowUp"){
    e.preventDefault();
    if(state.filtered.length===0) return;
    state.selected = Math.max(0, state.selected-1);
    render();
  } else if(e.key===" " && !isInput){
    e.preventDefault();
    if(state.selected>=0 && state.filtered[state.selected]){
      toggleCheck(keyOf(state.filtered[state.selected]));
    }
  } else if(e.key==="Enter" && !isInput){
    if(state.selected>=0 && state.filtered[state.selected]){
      toggleCheck(keyOf(state.filtered[state.selected]));
    }
  }
});

// Kbd-hint toggle
(function initKbdToggle(){
  const btn = document.getElementById("kbdToggle");
  const hint = document.getElementById("kbdHint");
  if(!btn || !hint) return;
  btn.addEventListener("click",()=>{
    hint.style.display = (hint.style.display === "none") ? "block" : "none";
  });
})();

// Closing dock のドラッグ
(function initDrag(){
  const dock = document.getElementById("closingDock");
  if(!dock) return;
  let down=false, sx=0, sy=0, ox=0, oy=0;
  dock.addEventListener("mousedown",(e)=>{
    down=true; sx=e.clientX; sy=e.clientY;
    const r = dock.getBoundingClientRect(); ox=r.left; oy=r.top;
    dock.style.transition="none";
  });
  window.addEventListener("mousemove",(e)=>{
    if(!down) return;
    const nx = ox + (e.clientX - sx);
    const ny = oy + (e.clientY - sy);
    dock.style.left = Math.max(0, Math.min(window.innerWidth - dock.offsetWidth, nx)) + "px";
    dock.style.top  = Math.max(0, Math.min(window.innerHeight - dock.offsetHeight, ny)) + "px";
    dock.style.right = "auto"; dock.style.bottom = "auto";
  });
  window.addEventListener("mouseup",()=>{ down=false; });
})();
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
buildModes();
document.getElementById("btnOffice").addEventListener("click",()=>pushSpecial("SP:OFFICE"));
document.getElementById("btnAiPaste").addEventListener("click",()=>pushSpecial("SP:AI"));
document.getElementById("clearAllBtn").addEventListener("click",(ev)=>{ ev.stopPropagation(); clearAllChecks(); });
parseInitial();
render();
</script>
</body>
</html>
"""


def load_general_qa():
    """general_qa.json を読み込む（存在しなければ空）"""
    p = os.path.join(ROOT, "general_qa.json")
    if not os.path.exists(p):
        return {"items": [], "cats": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def build_inner_html(data, sources) -> tuple[str, int]:
    total = sum(len(v["items"]) for v in data.values())
    qa_items = []
    # A_CLASS_ORDER の順序を保ちたい → sort by major then by id numeric if possible
    for _, cat_key, short in A_CLASS_ORDER:
        val = data.get(cat_key)
        if not val:
            continue
        # sort by numeric id (F#は末尾に)
        sorted_items = sorted(val["items"], key=lambda t: (t[0].startswith("F"), int(t[0][1:]) if t[0].startswith("F") else int(t[0])))
        for display_id, q, a, tag in sorted_items:
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

    gen = load_general_qa()
    general_items = gen.get("items", [])
    general_cats = gen.get("cats", [])
    build_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M JST")

    html = (HTML_WRAPPER_TEMPLATE
            .replace("__QA_JSON__",        json.dumps(qa_items, ensure_ascii=False))
            .replace("__TEMPLATES_JSON__", json.dumps(template_items, ensure_ascii=False))
            .replace("__CATS_JSON__",      json.dumps(cats, ensure_ascii=False))
            .replace("__GENERAL_JSON__",   json.dumps(general_items, ensure_ascii=False))
            .replace("__GENERAL_CATS_JSON__", json.dumps(general_cats, ensure_ascii=False))
            .replace("__BUILD_TIME__",     build_time)
            .replace("__TOTAL__",          str(total))
            .replace("__GEN_TOTAL__",      str(len(general_items)))
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
