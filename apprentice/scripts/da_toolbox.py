#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
da_toolbox.py — 领域学徒（domain-apprentice）配套工具箱 v0.1

作用：把 skill 里的三件知识资产（知识总账 / 缺口登记簿 / 能力画像）从"LLM 手写 markdown、
靠自律维持格式"升级为"SQLite 为真相源 + 命令行操作 + markdown 渲染视图"，并提供两个
机械执行体：答前门控（铁律⑪）与卡片校验（审核前的格式安检）。

设计约定：
- SQLite（研究档案/.da_ledger.db）是机器真相源；render 生成的 .md 是人读视图（文件头有
  自动生成标记，请勿手改，改动一律走本工具命令）。
- 状态词表封闭枚举，杜绝跨会话格式漂移。
- 仅用标准库，单文件，不服务化——符合 skill"一次性脚本"哲学。

用法示例：
  python da_toolbox.py init <项目根目录>
  python da_toolbox.py coverage set <根> 异体合并 字编A区 已覆盖 档案/v2-1.md
  python da_toolbox.py gap add <根> --what 缺上古音数据 --signal 巡检 --action 找EVOBC --blocks 争议型
  python da_toolbox.py gap list <根> --status 待办
  python da_toolbox.py profile record <根> 异体合并型 已知答案 pass --evidence v2-验收
  python da_toolbox.py gate <根> 异体合并型 [--difficulty 争议]
  python da_toolbox.py check <研究卡.md>
  python da_toolbox.py stats <根> ;  render <根> [总账|登记簿|画像|all]
"""
import argparse
import datetime
import os
import sqlite3
import sys

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_NAME = ".da_ledger.db"
GAP_STATUS = ["待办", "补缺中", "已复测销账", "存而不论"]
GAP_OPEN = ["待办", "补缺中"]
COV_STATUS = ["已覆盖", "部分覆盖", "未覆盖"]
DIFFS = ["已知答案", "争议", "开放"]
CONF = ["确", "较可信", "存疑", "弱假说", "存而不论"]
MARKS = ["〔已验证", "〔模型记忆", "〔未知", "待核对"]
CARD_KEYWORDS = ["建档材料", "证据链", "候选", "已排除假设", "缺口清单"]
AUTO_HEADER = "<!-- 本文件由 da_toolbox render 自动生成，请勿手改；改动请用 toolbox 命令 -->\n\n"


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def db_connect(root):
    d = os.path.join(root, "研究档案")
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(os.path.join(d, DB_NAME))
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS gaps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        what TEXT NOT NULL, signal TEXT, action TEXT, cost TEXT, blocks TEXT,
        status TEXT DEFAULT '待办', created TEXT, closed TEXT);
    CREATE TABLE IF NOT EXISTS profile(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_type TEXT NOT NULL, difficulty TEXT, result TEXT,
        evidence TEXT, created TEXT);
    CREATE TABLE IF NOT EXISTS coverage(
        zone TEXT NOT NULL, source_item TEXT NOT NULL,
        status TEXT DEFAULT '未覆盖', archive_ref TEXT, updated TEXT,
        PRIMARY KEY(zone, source_item));
    """)
    return conn, d


# ---------- 渲染 ----------
def render_coverage(conn):
    rows = conn.execute("SELECT zone, source_item, status, archive_ref, updated FROM coverage ORDER BY zone, source_item").fetchall()
    if not rows:
        return AUTO_HEADER + "# 知识总账（空）\n\n> 用 coverage set 逐区登记权威普查工件条目。\n"
    total = len(rows)
    cov = sum(1 for r in rows if r[2] == "已覆盖")
    part = sum(1 for r in rows if r[2] == "部分覆盖")
    rate = (cov + 0.5 * part) / total * 100
    out = [AUTO_HEADER, "# 知识总账（供应侧盘点）\n",
           f"- 条目 {total}；已覆盖 {cov}，部分 {part}，未覆盖 {total-cov-part}；**覆盖率 {rate:.0f}%**\n",
           "| 知识区 | 来源条目 | 状态 | 对应档案 | 更新 |", "|---|---|---|---|---|"]
    out += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3] or ''} | {r[4] or ''} |" for r in rows]
    return "\n".join(out) + "\n"


def render_gaps(conn):
    rows = conn.execute("SELECT id, what, signal, action, cost, blocks, status, created, closed FROM gaps ORDER BY id").fetchall()
    out = [AUTO_HEADER, "# 缺口登记簿\n"]
    if not rows:
        out.append("> 空。巡检四种信号：定期diff / 任务失败 / 源分歧 / 专家指盲。\n")
        return "\n".join(out) + "\n"
    for r in rows:
        out.append(f"\n## #{r[0]} [{r[6]}] {r[1]}\n")
        out.append(f"- 信号源：{r[2] or ''}；补缺动作：{r[3] or ''}；成本：{r[4] or ''}；阻塞：{r[5] or ''}")
        out.append(f"- 登记：{r[7] or ''}；关闭：{r[8] or '—'}")
    return "\n".join(out) + "\n"


def render_profile(conn):
    rows = conn.execute("SELECT task_type, difficulty, result, evidence, created FROM profile ORDER BY task_type, difficulty, id").fetchall()
    out = [AUTO_HEADER, "# 能力画像\n"]
    if not rows:
        out.append("> 空。未测试＝未知——用 profile record 记录每次盲测/验收/抽测结果。\n")
        return "\n".join(out) + "\n"
    agg = {}
    for r in rows:
        key = (r[0], r[1] or "")
        a = agg.setdefault(key, [0, 0, []])
        a[1] += 1
        if r[2] == "pass":
            a[0] += 1
        if r[3]:
            a[2].append(r[3])
    out.append("| 任务类型 | 难度 | 实测 | 通过 | 通过率 | 证据 | 状态 |")
    out.append("|---|---|---|---|---|---|---|")
    for (t, d), (p, n, ev) in sorted(agg.items()):
        rate = p / n * 100
        st = "✅ 已验证" if rate >= 80 else "⚠️ 失败区"
        out.append(f"| {t} | {d or '—'} | {n} | {p} | {rate:.0f}% | {';'.join(ev[:3])} | {st} |")
    out.append("\n> ❓ 未列出的类型＝未测试＝能力未知（铁律⑪）。")
    return "\n".join(out) + "\n"


def cmd_render(root, which):
    conn, d = db_connect(root)
    files = {"总账": ("知识总账.md", render_coverage), "登记簿": ("缺口登记簿.md", render_gaps),
             "画像": ("能力画像.md", render_profile)}
    todo = files.items() if which == "all" else [(which, files[which])]
    for name, (fn, f) in todo:
        path = os.path.join(d, fn)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f(conn))
        print(f"rendered: {path}")
    conn.close()


# ---------- 子命令 ----------
def cmd_init(root):
    conn, d = db_connect(root)
    conn.close()
    cmd_render(root, "all")
    print(f"initialized at: {os.path.join(root, '研究档案')}（DB + 三件渲染视图）")
    print("下一步：coverage set 逐区登记权威普查工件条目，算出覆盖率。")


def cmd_coverage(args):
    conn, _ = db_connect(args.root)
    if args.cmd == "set":
        if args.status not in COV_STATUS:
            sys.exit(f"非法状态 {args.status}；合法：{'/'.join(COV_STATUS)}")
        conn.execute("""INSERT INTO coverage(zone, source_item, status, archive_ref, updated)
                        VALUES(?,?,?,?,?)
                        ON CONFLICT(zone, source_item) DO UPDATE SET
                        status=excluded.status, archive_ref=excluded.archive_ref, updated=excluded.updated""",
                     (args.zone, args.item, args.status, args.ref, now()))
        conn.commit()
        print(f"coverage: {args.zone}/{args.item} -> {args.status}")
    conn.close()
    cmd_render(args.root, "总账")


def cmd_gap(args):
    conn, _ = db_connect(args.root)
    if args.cmd == "add":
        cur = conn.execute("INSERT INTO gaps(what, signal, action, cost, blocks, created) VALUES(?,?,?,?,?,?)",
                           (args.what, args.signal, args.action, args.cost, args.blocks, now()))
        conn.commit()
        print(f"gap #{cur.lastrowid} 已登记：{args.what}")
    elif args.cmd == "list":
        q = "SELECT id, status, what, blocks FROM gaps"
        rows = conn.execute(q).fetchall()
        if args.status:
            rows = [r for r in rows if r[1] == args.status]
        for r in rows:
            print(f"#{r[0]}\t[{r[1]}]\t{r[2]}\t阻塞:{r[3] or '—'}")
        if not rows:
            print("（无）")
    elif args.cmd in ("close", "start", "shelve"):
        m = {"close": "已复测销账", "start": "补缺中", "shelve": "存而不论"}
        conn.execute("UPDATE gaps SET status=?, closed=? WHERE id=?", (m[args.cmd], now() if args.cmd != "start" else None, args.id))
        conn.commit()
        print(f"gap #{args.id} -> {m[args.cmd]}")
    conn.close()
    cmd_render(args.root, "登记簿")


def cmd_profile(args):
    conn, _ = db_connect(args.root)
    if args.cmd == "record":
        if args.result not in ("pass", "fail"):
            sys.exit("result 必须是 pass|fail")
        conn.execute("INSERT INTO profile(task_type, difficulty, result, evidence, created) VALUES(?,?,?,?,?)",
                     (args.type, args.difficulty, args.result, args.evidence, now()))
        conn.commit()
        print(f"profile +1: {args.type}/{args.difficulty} {args.result}")
    conn.close()
    cmd_render(args.root, "画像")


def cmd_gate(root, task_type, difficulty=None):
    """答前门控三问（铁律⑪的机械执行体）"""
    conn, _ = db_connect(root)
    q = "SELECT result FROM profile WHERE task_type=?"
    par = [task_type]
    if difficulty:
        q += " AND difficulty=?"
        par.append(difficulty)
    rows = [r[0] for r in conn.execute(q, par).fetchall()]
    blocking = conn.execute(
        "SELECT id, what FROM gaps WHERE blocks LIKE ? AND status IN ('待办','补缺中')",
        (f"%{task_type}%",)).fetchall()
    q2 = conn.execute("SELECT COUNT(*), SUM(status='已覆盖') FROM coverage").fetchone()
    conn.close()

    tested, passed = len(rows), sum(1 for r in rows if r == "pass")
    print("== 答前门控三问 ==")
    print(f"问1 画像测过吗：", end="")
    if tested == 0:
        print(f" ❓ 未测试＝未知（{task_type} 无记录）")
    else:
        print(f" {passed}/{tested} 通过（{passed/tested*100:.0f}%）")
    print(f"问2 总账覆盖了吗：{q2[1] or 0}/{q2[0]} 区已覆盖" + ("" if (q2[0] and (q2[1] or 0) == q2[0]) else "（存在未覆盖区，输出须带缺口声明）"))
    print("问3 哪些论断只是模型记忆：请逐条标〔模型记忆·待核对〕（机械不可判，靠三级标注纪律）")
    print("-- 裁决 --")
    if blocking:
        print(f"⛔ 缺口阻塞（{len(blocking)}条未销账，如 #{blocking[0][0]} {blocking[0][1]}）→ 补缺先行或存而不论")
        sys.exit(2)
    if tested == 0:
        print("❓ 未测试 → 至少降档作答＋触发缺口登记，禁止自信完答")
        sys.exit(1)
    if passed / tested < 0.8:
        print("⚠️ 失败区（<80%）→ 降档作答＋登记覆盖债")
        sys.exit(1)
    print("✅ 放行（输出仍须三级标注＋缺口声明两节）")


def cmd_check(path):
    """研究卡机械校验：必备节 / 置信词表 / 三级标注存在性（语义层仍靠独立审核）"""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    heads = [l for l in text.splitlines() if l.startswith("#")]
    missing = [k for k in CARD_KEYWORDS if not any(k in h for h in heads)]
    has_conf = any(c in text for c in CONF)
    has_mark = any(m in text for m in MARKS)
    print(f"check: {path}")
    if missing:
        print(f"  ✗ 缺必备节：{'、'.join(missing)}")
    else:
        print("  ✓ 必备节齐（建档材料/证据链/候选与裁决/已排除假设/缺口清单）")
    print("  ✓ 置信分档词表" if has_conf else "  ✗ 未发现置信分档词（确/较可信/存疑/弱假说/存而不论）")
    print("  ✓ 三级来源标注/待核对标记" if has_mark else "  ✗ 未发现任何来源标注（〔已验证/〔模型记忆/〔未知/待核对）")
    if missing or not has_conf or not has_mark:
        print("  → 机械校验未过：先修格式，再交独立审核（节省审核注意力给语义层）")
        sys.exit(1)
    print("  → 机械校验通过：可交独立审核（语义层：证据是否属实、引文是否逐字、是否 overclaim）")


def cmd_stats(root):
    conn, _ = db_connect(root)
    cov = conn.execute("SELECT COUNT(*), SUM(status='已覆盖'), SUM(status='部分覆盖') FROM coverage").fetchone()
    gp = conn.execute("SELECT COUNT(*), SUM(status IN ('待办','补缺中')), SUM(status='已复测销账') FROM gaps").fetchone()
    pr = conn.execute("SELECT COUNT(*), SUM(result='pass') FROM profile").fetchall()
    pf = conn.execute("SELECT task_type, difficulty, COUNT(*), SUM(result='pass') FROM profile GROUP BY task_type, difficulty").fetchall()
    conn.close()
    t = cov[0] or 0
    rate = ((cov[1] or 0) + 0.5 * (cov[2] or 0)) / t * 100 if t else 0
    g0 = gp[0] or 0
    burn = (gp[2] or 0) / g0 * 100 if g0 else 0
    p0 = pr[0][0] or 0
    print(f"覆盖率：{rate:.0f}%（{t} 区）")
    print(f"缺口燃尽：{burn:.0f}%（登记 {g0}，未销 {gp[1] or 0}）")
    print(f"画像实测：{p0} 次，通过 {(pr[0][1] or 0)}")
    for r in pf:
        print(f"  {r[0]}/{r[1] or '—'}: {r[3] or 0}/{r[2]} ({(r[3] or 0)/r[2]*100:.0f}%)")


def main():
    ap = argparse.ArgumentParser(description="领域学徒配套工具箱 v0.1")
    sub = ap.add_subparsers(dest="group", required=True)

    sub.add_parser("init").add_argument("root")

    c = sub.add_parser("coverage"); c.add_argument("cmd", choices=["set"]); c.add_argument("root")
    c.add_argument("zone"); c.add_argument("item"); c.add_argument("status"); c.add_argument("ref", nargs="?")

    g = sub.add_parser("gap"); g.add_argument("cmd", choices=["add", "list", "close", "start", "shelve"])
    g.add_argument("root"); g.add_argument("id", nargs="?", type=int)
    g.add_argument("--what"); g.add_argument("--signal"); g.add_argument("--action")
    g.add_argument("--cost"); g.add_argument("--blocks"); g.add_argument("--status")

    p = sub.add_parser("profile"); p.add_argument("cmd", choices=["record"])
    p.add_argument("root"); p.add_argument("type"); p.add_argument("difficulty", nargs="?")
    p.add_argument("result"); p.add_argument("--evidence")

    gt = sub.add_parser("gate"); gt.add_argument("root"); gt.add_argument("type")
    gt.add_argument("--difficulty", choices=DIFFS)

    ck = sub.add_parser("check"); ck.add_argument("card")

    st = sub.add_parser("stats"); st.add_argument("root")
    rd = sub.add_parser("render"); rd.add_argument("root"); rd.add_argument("which", choices=["总账", "登记簿", "画像", "all"])

    a = ap.parse_args()
    if a.group == "init":
        cmd_init(a.root)
    elif a.group == "coverage":
        cmd_coverage(a)
    elif a.group == "gap":
        cmd_gap(a)
    elif a.group == "profile":
        cmd_profile(a)
    elif a.group == "gate":
        cmd_gate(a.root, a.type, a.difficulty)
    elif a.group == "check":
        cmd_check(a.card)
    elif a.group == "stats":
        cmd_stats(a.root)
    elif a.group == "render":
        cmd_render(a.root, a.which)


if __name__ == "__main__":
    main()
