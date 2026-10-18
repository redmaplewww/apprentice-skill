#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lrv.py — 学述验闭环（LRV Loop）状态机 v0.1

作用：LRV 轮次账本 + 验证基准期别（E共识/M混合/L自主）解锁的机械强制 + 日志五节校验。
存储：SQLite（研究档案/.lrv_state.db）；日志：研究档案/LRV/<模块>.md（骨架自动生成）。
仅标准库单文件，不依赖 apprentice（可独立运行；产物格式与 apprentice 资产对齐以便回喂）。

用法：
  lrv.py init <根>
  lrv.py round add <根> <模块> --basis E|M|L --coverage 0.8 --major 0 --minor 2 --missing 1 [--learned <文件> --restated <文件>]
  lrv.py round pass <根> <模块> [--seq <轮次号>]     # 默认锁最新轮
  lrv.py status <根> [--module <模块>]
  lrv.py check <LRV日志.md>
解锁规则（可调常量）：M 期=全项目 ≥PASS_M 个模块通过；L 期=≥PASS_L 个模块通过 且 本模块有 M 期轮次。
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

DB_NAME = ".lrv_state.db"
PASS_M, PASS_L = 2, 5
MODULE_STATUS = ["未开始", "循环中", "已通过"]
LOG_SECTIONS = ["学习输入", "复述稿", "验证diff", "失配清单与归因", "裁决与下一轮靶点"]
BASIS_DESC = {"E": "共识期（基准=权威源原文）", "M": "混合期（基准=已验证自库+权威源）", "L": "自主期（基准=自主结论体系）"}
SKELETON = """# LRV 日志 · {module}

> 学述验闭环轮次记录。每轮固定五节；红线：复述合卷、记不起显式标注、逐条对源、失配必归因、无日志不认轮次。

"""


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def db_connect(root):
    d = os.path.join(root, "研究档案")
    os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(os.path.join(d, DB_NAME))
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS modules(
        name TEXT PRIMARY KEY, status TEXT DEFAULT '未开始', created TEXT);
    CREATE TABLE IF NOT EXISTS rounds(
        id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT NOT NULL, seq INTEGER,
        basis TEXT, coverage REAL, major INTEGER, minor INTEGER, missing INTEGER,
        learned_ref TEXT, restated_ref TEXT, verdict TEXT, created TEXT);
    """)
    return conn, d


def unlock_state(conn):
    passed = conn.execute("SELECT COUNT(*) FROM modules WHERE status='已通过'").fetchone()[0]
    return {"passed": passed, "M": passed >= PASS_M, "L_count": passed >= PASS_L}


def basis_allowed(conn, module, basis):
    u = unlock_state(conn)
    if basis == "E":
        return True, ""
    if basis == "M":
        if not u["M"]:
            return False, "M 混合期未解锁：需 ≥%d 个模块经 E 期验证通过（当前 %d）" % (PASS_M, u["passed"])
        return True, ""
    if basis == "L":
        if not u["L_count"]:
            return False, "L 自主期未解锁：需 ≥%d 个模块通过（当前 %d）" % (PASS_L, u["passed"])
        has_m = conn.execute("SELECT COUNT(*) FROM rounds WHERE module=? AND basis='M'", (module,)).fetchone()[0]
        if not has_m:
            return False, "L 自主期要求本模块先有 M 期轮次记录（%s 无）" % module
        return True, ""
    return False, "basis 必须是 E|M|L"


def scaffold(d, module, seq):
    ldir = os.path.join(d, "LRV")
    os.makedirs(ldir, exist_ok=True)
    path = os.path.join(ldir, module + ".md")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write(SKELETON.format(module=module))
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n## 第 %d 轮（%s）\n\n" % (seq, now()))
        for sec in LOG_SECTIONS:
            f.write("### %s\n\n（待填）\n\n" % sec)
    return path


def cmd_round_add(a):
    conn, d = db_connect(a.root)
    if a.basis not in ("E", "M", "L"):
        sys.exit("basis 必须是 E|M|L")
    ok, why = basis_allowed(conn, a.module, a.basis)
    if not ok:
        print("⛔ " + why)
        sys.exit(2)
    if not 0 <= a.coverage <= 1:
        sys.exit("coverage 取 0~1")
    conn.execute("INSERT INTO modules(name, status, created) VALUES(?,?,?) "
                 "ON CONFLICT(name) DO NOTHING", (a.module, "未开始", now()))
    seq = (conn.execute("SELECT COUNT(*) FROM rounds WHERE module=?", (a.module,)).fetchone()[0]) + 1
    verdict = "通过候选（零关键失配且覆盖率≥80%）" if (a.major == 0 and a.coverage >= 0.8) else "继续（失配转下一轮靶点）"
    conn.execute("INSERT INTO rounds(module, seq, basis, coverage, major, minor, missing, learned_ref, restated_ref, verdict, created) "
                 "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                 (a.module, seq, a.basis, a.coverage, a.major, a.minor, a.missing, a.learned, a.restated, verdict, now()))
    conn.execute("UPDATE modules SET status='循环中' WHERE name=?", (a.module,))
    conn.commit()
    path = scaffold(d, a.module, seq)
    print("round %d ｜%s｜ [%s] 覆盖率%.0f%% 关键失配%d 次要%d 遗漏%d → %s" %
          (seq, a.module, a.basis, a.coverage * 100, a.major, a.minor, a.missing, verdict))
    print("日志骨架已追加：" + path)
    conn.close()


def cmd_round_pass(a):
    conn, d = db_connect(a.root)
    row = (conn.execute("SELECT id, seq, verdict FROM rounds WHERE module=? ORDER BY seq DESC LIMIT 1", (a.module,)).fetchone()
           if not a.seq else conn.execute("SELECT id, seq, verdict FROM rounds WHERE module=? AND seq=?", (a.module, a.seq)).fetchone())
    if not row:
        sys.exit("模块 %s 无轮次记录，先 round add" % a.module)
    if "继续" in (row[2] or ""):
        sys.exit("最新轮 verdict=继续（存在关键失配或覆盖率不足），不得 pass；先补轮次")
    conn.execute("UPDATE rounds SET verdict='已通过(锁档)' WHERE id=?", (row[0],))
    conn.execute("UPDATE modules SET status='已通过' WHERE name=?", (a.module,))
    conn.commit()
    u = unlock_state(conn)
    conn.close()
    print("模块 %s 第 %d 轮已锁档通过。已通过模块 %d → M期%s / L期%s" %
          (a.module, row[1], u["passed"], "解锁" if u["M"] else "未解锁", "计数达标" if u["L_count"] else "未达标"))


def cmd_status(a):
    conn, _ = db_connect(a.root)
    u = unlock_state(conn)
    print("解锁状态：已通过模块 %d ｜ M 混合期：%s ｜ L 自主期计数：%s" %
          (u["passed"], "已解锁" if u["M"] else "未解锁（需≥%d）" % PASS_M, "达标（需≥%d）" % PASS_L if u["L_count"] else "未达标（需≥%d）" % PASS_L))
    q = "SELECT name, status FROM modules"
    mods = conn.execute(q).fetchall() if not a.module else conn.execute(q + " WHERE name=?", (a.module,)).fetchall()
    for m in mods:
        rounds = conn.execute("SELECT seq, basis, coverage, major, minor, missing, verdict FROM rounds WHERE module=? ORDER BY seq", (m[0],)).fetchall()
        print("\n◆ %s［%s］%d 轮" % (m[0], m[1], len(rounds)))
        for r in rounds:
            print("  #%d [%s] 覆盖%.0f%% 失配 关键%d/次要%d/遗漏%d → %s" % (r[0], r[1], r[2] * 100, r[3], r[4], r[5], r[6]))
    conn.close()


def cmd_check(path):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    rounds = [r for r in text.split("\n## ") if r.strip() and not r.startswith("#")]
    bad = 0
    print("check: %s（%d 轮）" % (path, len(rounds)))
    for i, r in enumerate(rounds, 1):
        missing = [s for s in LOG_SECTIONS if s not in r]
        if missing:
            bad += 1
            print("  ✗ 第%d轮缺节：%s" % (i, "、".join(missing)))
        else:
            print("  ✓ 第%d轮五节齐全" % i)
        if "（待填）" in r:
            print("  △ 第%d轮仍有占位'（待填）'——轮次未完成" % i)
    if bad:
        sys.exit(1)
    print("→ 日志结构校验通过")


def main():
    ap = argparse.ArgumentParser(description="学述验闭环 LRV 状态机 v0.1")
    sub = ap.add_subparsers(dest="group", required=True)
    sub.add_parser("init").add_argument("root")
    r = sub.add_parser("round"); r.add_argument("cmd2", choices=["add", "pass"]); r.add_argument("root"); r.add_argument("module")
    r.add_argument("--basis", choices=["E", "M", "L"]); r.add_argument("--coverage", type=float)
    r.add_argument("--major", type=int); r.add_argument("--minor", type=int); r.add_argument("--missing", type=int)
    r.add_argument("--learned"); r.add_argument("--restated"); r.add_argument("--seq", type=int)
    s = sub.add_parser("status"); s.add_argument("root"); s.add_argument("--module")
    c = sub.add_parser("check"); c.add_argument("log")

    a = ap.parse_args()
    if a.group == "init":
        conn, d = db_connect(a.root)
        conn.close()
        os.makedirs(os.path.join(d, "LRV"), exist_ok=True)
        print("initialized: %s（状态库+LRV日志目录）" % os.path.join(d, DB_NAME))
    elif a.group == "round":
        if a.cmd2 == "add":
            if None in (a.basis, a.coverage, a.major, a.minor, a.missing):
                sys.exit("round add 需要 --basis --coverage --major --minor --missing")
            cmd_round_add(a)
        else:
            cmd_round_pass(a)
    elif a.group == "status":
        cmd_status(a)
    elif a.group == "check":
        cmd_check(a.log)


if __name__ == "__main__":
    main()
