# -*- coding: utf-8 -*-
"""
知径 · 确定性计算工具（graph_ops.py）
====================================
协议命令的数值内核：路径规划、掌握度/间隔更新、校准统计、图谱与终局导出。
设计原则：**LLM 只讲解、不口算**——所有数值计算由本工具承担，
教学 Agent（Pi + DeepSeek V4 Pro）通过 run_command 调用。

用法示例：
  python tools/graph_ops.py status      --graph graph.json
  python tools/graph_ops.py plan        --graph graph.json
  python tools/graph_ops.py teach-next  --graph graph.json
  python tools/graph_ops.py quiz 切线 --grade 1 --conf 80 --graph graph.json
  python tools/graph_ops.py review      --graph graph.json
  python tools/graph_ops.py feel "斜率类比没听懂" --r 斜率 切线 0.70 --graph graph.json
  python tools/graph_ops.py calibrate   --graph graph.json
  python tools/graph_ops.py graph       --graph graph.json
  python tools/graph_ops.py graduate    --graph graph.json
  python tools/graph_ops.py import-headings 笔记 --commit --graph graph.json

状态：--graph 指向图谱文件（默认 ./graph.json）；日志与导出写在其所在目录
（quiz_log.jsonl / feedback.jsonl / audit.log / 图谱导出/）。
"""
import argparse
import datetime as dt
import heapq
import json
import os
import shutil
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LAMBDA = 3.0
MASTERED = 0.8
MASTERED_COST = 0.7

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "templates", "graph.模板.json")


def now():
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return dt.date.today()


# ---------- 文件 ----------
def load_graph(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_graph(path, g):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1)


def append_jsonl(path, rec):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def audit(state_dir, line):
    with open(os.path.join(state_dir, "audit.log"), "a", encoding="utf-8") as f:
        f.write(f"[{now()}] {line}\n")


def process(g, evt, **kw):
    rec = {"ts": now(), "evt": evt}
    rec.update(kw)
    g.setdefault("meta", {}).setdefault("process", []).append(rec)


# ---------- 图引擎 ----------
class G:
    def __init__(self, g):
        self.g = g
        self.adj = {}
        for e in g["edges"]:
            a, b = e["a"], e["b"]
            self.adj.setdefault(a, []).append((b, e))
            self.adj.setdefault(b, []).append((a, e))

    def m(self, n):
        return self.g["nodes"][n]["m"]

    def cost(self, a, b, r):
        if self.m(b) >= MASTERED:
            return MASTERED_COST / r
        return (1.0 + LAMBDA * (1.0 - self.m(b))) / r

    def starts(self):
        return [n for n, d in self.g["nodes"].items() if d["m"] >= MASTERED]

    def dijkstra(self, goal):
        """从已知区 S 到 goal 的最小权重路径 -> (edges[], total)"""
        starts = self.starts()
        dist = {s: 0.0 for s in starts}
        prev = {}
        pq = [(0.0, s) for s in starts]
        heapq.heapify(pq)
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, float("inf")):
                continue
            if u == goal:
                break
            for v, e in self.adj.get(u, []):
                nd = d + self.cost(u, v, e["r"])
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, e)
                    heapq.heappush(pq, (nd, v))
        if goal not in prev:
            return None
        edges, cur = [], goal
        while cur in prev:
            u, e = prev[cur]
            edges.append((u, cur, e))
            cur = u
        edges.reverse()
        return edges, dist[goal]

    def dist_to_goal(self, v, goal):
        """从 v 到 goal 的当前最短代价（单源 Dijkstra）"""
        dist = {v: 0.0}
        pq = [(0.0, v)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist.get(u, float("inf")):
                continue
            if u == goal:
                return d
            for w, e in self.adj.get(u, []):
                nd = d + self.cost(u, w, e["r"])
                if nd < dist.get(w, float("inf")):
                    dist[w] = nd
                    heapq.heappush(pq, (nd, w))
        return float("inf")

    def enumerate_paths(self, goal, max_len=4):
        """枚举从 S 到 goal 的长度<=max_len 的简单路径，按总代价排序"""
        results = []

        def dfs(cur, path, cost):
            if len(path) > max_len:
                return
            if cur == goal and len(path) >= 2:
                results.append((list(path), cost))
                return
            for w, e in self.adj.get(cur, []):
                if w in path:
                    continue
                dfs(w, path + [w], cost + self.cost(cur, w, e["r"]))

        for s in self.starts():
            dfs(s, [s], 0.0)
        results.sort(key=lambda x: x[1])
        return results

    def taught_nodes(self):
        seen = set()
        for p in self.g.get("meta", {}).get("process", []):
            if p.get("evt") == "teach":
                seen.add(p["b"])
        return seen


def find_edge(g, a, b):
    for e in g["edges"]:
        if {e["a"], e["b"]} == {a, b}:
            return e
    return None


def fmt_m(m):
    return f"{m:.2f}"


def load_quiz_records(state_dir, node):
    """读取某节点的有效测验记录（排除 undo 标记）。"""
    path = os.path.join(state_dir, "quiz_log.jsonl")
    recs = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("node") == node and not r.get("undo_of"):
                    recs.append(r)
    return recs


def assess_node(g, node, records):
    """分数 + 多标签评价。
    分数 = m×50 + 复习×15(6次封顶) + 最近表现×20(平均成绩) + 校准×15(信心与成绩一致度)。
    """
    d = g["nodes"][node]
    m = d["m"]
    reviews = d.get("reviews", 0)
    confs = [r["conf"] for r in records]
    grades = [r["grade"] for r in records]
    s_m = m * 50
    s_r = min(reviews, 6) / 6 * 15
    s_g = (sum(grades[-5:]) / len(grades[-5:]) * 20) if grades else 0.0
    s_c = 0.0
    if confs and grades:
        err = abs(sum(confs) / len(confs) - 100 * sum(grades) / len(grades))
        s_c = max(0.0, (1 - err / 100) * 15)
    score = round(min(100, s_m + s_r + s_g + s_c))
    tags = []
    diff = d.get("difficulty", 2)
    tags.append("高阶" if diff >= 4 else ("进阶" if diff >= 2 else "基础"))
    tags.append("已掌握" if m >= MASTERED else ("半知" if m >= 0.3 else "未知"))
    tags.append("熟练" if reviews >= 6 else ("熟悉" if reviews >= 3 else ("生疏" if reviews >= 1 else "未练")))
    if grades:
        recent = grades[-3:]
        if len(recent) >= 2 and all(x >= 0.8 for x in recent):
            tags.append("稳定")
        elif any(x == 0 for x in recent):
            tags.append("波动")
    ms = [h.get("m_new") for h in d.get("history", []) if "m_new" in h]
    if len(ms) >= 2 and ms[-1] < ms[0]:
        tags.append("退化中")
    for e in g["edges"]:
        if e["a"] == node and e["type"] == "前提" and g["nodes"].get(e["b"], {}).get("m", 0) < MASTERED:
            tags.append("关键前提")
            break
    if any((r.get("conf", 0) >= 80 and r["grade"] <= 0.5) or r["grade"] == 0 for r in records):
        tags.append("卡点")
    else:
        tags.append("流畅")
    interest = g["meta"].get("interest", {}).get(node)
    if interest is not None:
        tags.append("兴趣高" if interest >= 70 else ("兴趣低" if interest < 40 else "兴趣中"))
    return score, tags


# ---------- 子命令 ----------
def cmd_status(g, G_, args):
    nodes = g["nodes"]
    known = [n for n in nodes if nodes[n]["m"] >= MASTERED]
    half = [n for n in nodes if 0.3 <= nodes[n]["m"] < MASTERED]
    unknown = [n for n in nodes if nodes[n]["m"] < 0.3]
    goal = g.get("goal", "")
    print(f"目标: {goal}")
    print(f"已知区({len(known)}): {', '.join(known) or '-'}")
    print(f"半知区({len(half)}): {', '.join(half) or '-'}")
    print(f"未知区({len(unknown)}): {', '.join(unknown) or '-'}")
    if goal in nodes:
        path = G_.dijkstra(goal)
        if path:
            edges, total = path
            route = " → ".join([edges[0][0]] + [b for _, b, _ in edges])
            print(f"当前最优路径: {route}   总代价 {total:.2f}")
    due = due_nodes(g)
    print(f"到期复习: {len(due)} 个 {('(' + ', '.join(due) + ')') if due else ''}")
    taught = G_.taught_nodes()
    if taught:
        print(f"已教未过门禁: {[n for n in taught if nodes[n]['m'] < MASTERED] or '-'}")


def due_nodes(g):
    t = today()
    due = []
    for n, d in g["nodes"].items():
        if d["m"] >= MASTERED:
            continue
        lr = d.get("last_review")
        if not lr:
            due.append(n)
            continue
        try:
            last = dt.datetime.strptime(lr, "%Y-%m-%d %H:%M").date()
            nxt = last + dt.timedelta(days=int(d.get("interval", 1)))
            if nxt <= t:
                due.append(n)
        except ValueError:
            due.append(n)
    return due


def cmd_plan(g, G_, args):
    goal = g.get("goal", "")
    res = G_.dijkstra(goal)
    if not res:
        print(f"目标 {goal} 暂不可达：图谱缺边或已知区为空，请先探寻补点/补边。")
        return
    edges, total = res
    if "initial_cost" not in g.get("meta", {}):
        g.setdefault("meta", {})["initial_cost"] = total
        save_graph(args.graph, g)
    print(f"最优路径 (总代价 {total:.2f}):")
    for i, (a, b, e) in enumerate(edges, 1):
        c = G_.cost(a, b, e["r"])
        tag = "已掌握" if g["nodes"][b]["m"] >= MASTERED else f"m={fmt_m(g['nodes'][b]['m'])}"
        print(f"  {i}. {a} → {b}   r={e['r']:.2f} {e['type']}   代价 {c:.2f}  [{tag}]")
    print("备选路径 (top3):")
    for i, (path, cost) in enumerate(G_.enumerate_paths(goal)[:3], 1):
        marker = " ← 最优" if abs(cost - total) < 1e-9 else ""
        print(f"  {i}. {'→'.join(path)}   总代价 {cost:.2f}{marker}")


def cmd_teach_next(g, G_, args):
    nodes = g["nodes"]
    goal = g.get("goal", "")
    taught = G_.taught_nodes()
    # 门禁: 已教未掌握、且仍在当前最优路径上的点 -> 回炉
    # (被感受反馈淘汰、不再在路径上的点, 不挡路)
    gate = []
    path = G_.dijkstra(goal)
    if path:
        path_nodes = {e[0] for e in path[0]} | {e[1] for e in path[0]}
        gate = [n for n in taught if nodes[n]["m"] < MASTERED and n in path_nodes]
    if gate:
        print(f"门禁未过，先回炉: {'、'.join(gate)} (m 需 ≥ {MASTERED})")
        print("  请执行 /quiz <点> 直到 m ≥ 0.8")
        return
    # 前沿候选: 与已知区相邻的未掌握点, 评分 = 步进代价 + 到目标的剩余代价
    S = set(G_.starts())
    best = None
    for a in S:
        for b, e in G_.adj.get(a, []):
            if b in S:
                continue
            c = G_.cost(a, b, e["r"])
            score = c + G_.dist_to_goal(b, goal)
            if best is None or score < best[0]:
                best = (score, a, b, e, c)
    if best is None:
        print("找不到与已知区相连的未掌握点（图不连通或目标已掌握）。")
        return
    score, a, b, e, c = best
    n = len([p for p in g["meta"].get("process", []) if p.get("evt") == "teach"]) + 1
    node = nodes[b]
    print(f"【第 {n} 课】{b}    (新知识点, m={fmt_m(node['m'])})")
    print(f"  锚点: {a}  (r={e['r']:.2f}, {e['type']}) —— 你已掌握")
    print(f"  讲解: {node['def']}")
    print(f"  连接: {e.get('why', '')}  [已在图谱建边]")
    print(f"  来源: [{node.get('fact_level', 'L5')}] {node.get('source', '无')}")
    for v in node.get("views", [])[1:]:
        print(f"  多视角: {v}")
    print(f"  练习: 学完立刻 /quiz {b}")
    process(g, "teach", a=a, b=b, lesson=n, r=e["r"])
    save_graph(args.graph, g)
    print(f"  [已记录 process: teach {a}→{b}]")


def cmd_quiz(g, G_, args):
    nodes = g["nodes"]
    if args.node not in nodes:
        print(f"节点不存在: {args.node}")
        return
    d = nodes[args.node]
    old = d["m"]
    old_interval = d.get("interval", 0)
    old_ef = d.get("ef", 2.5)
    old_reviews = d.get("reviews", 0)
    old_last = d.get("last_review")
    gr = args.grade
    if gr >= 1:
        d["m"] = min(1.0, d["m"] + 0.25 * (1 - d["m"]))
    elif gr == 0.5:
        d["m"] = min(1.0, d["m"] + 0.10 * (1 - d["m"]))
    else:
        d["m"] = max(0.0, d["m"] - 0.30 * d["m"])
    # SM-2-lite
    ef = d.get("ef", 2.5)
    interval = d.get("interval", 0) or 1
    if gr >= 1:
        ef = min(3.0, ef + 0.1)
        interval = max(1, round(interval * ef))
    elif gr == 0.5:
        interval = max(1, round(interval * 1.3))
    else:
        ef = max(1.3, ef - 0.2)
        interval = 1
    d["ef"], d["interval"] = ef, interval
    d["reviews"] = d.get("reviews", 0) + 1
    d["last_review"] = now()
    nxt = today() + dt.timedelta(days=interval)
    d.setdefault("history", []).append({
        "ts": now(), "evt": "quiz", "conf": args.conf, "grade": gr,
        "m_old": round(old, 4), "m_new": round(d["m"], 4)})
    process(g, "quiz", node=args.node, conf=args.conf, grade=gr,
            old_m=old, old_interval=old_interval, old_ef=old_ef,
            old_reviews=old_reviews, old_last_review=old_last)
    save_graph(args.graph, g)
    append_jsonl(os.path.join(args.state, "quiz_log.jsonl"), {
        "ts": now(), "node": args.node, "conf": args.conf, "grade": gr,
        "m_old": round(old, 4), "m_new": round(d["m"], 4)})
    print(f"[测验] {args.node}: 信心 {args.conf}, 自评 {gr}")
    print(f"  m: {fmt_m(old)} → {fmt_m(d['m'])}   间隔: {interval} 天   下次复习: {nxt}")
    if d["m"] >= MASTERED:
        print(f"  ✓ 门禁通过, 可以 /teach-next 进入下一个新点")
    else:
        print(f"  ✗ 门禁未过 (需 ≥ {MASTERED}), 继续 /quiz {args.node}")


def cmd_init(g, G_, args):
    """新建学习目标：学习记录/正在学习/<名称>/ 含模板图谱、会话记录、产物与素材目录。"""
    base = os.path.abspath(args.base)
    zhengzai = os.path.join(base, "正在学习")
    os.makedirs(zhengzai, exist_ok=True)
    target = os.path.join(zhengzai, args.name)
    os.makedirs(os.path.join(target, "图谱导出"), exist_ok=True)
    os.makedirs(os.path.join(target, "素材"), exist_ok=True)
    os.makedirs(os.path.join(target, "复习"), exist_ok=True)
    tpl = load_graph(TEMPLATE)
    tpl["goal"] = args.goal
    tpl["meta"]["created"] = f"知径学习图谱：目标 = {args.goal}"
    out = os.path.join(target, "graph.json")
    save_graph(out, tpl)
    with open(os.path.join(target, "会话记录.md"), "w", encoding="utf-8") as f:
        f.write(f"# 会话记录 · {args.goal}\n")
    print(f"已创建学习目标目录: {target}")
    print(f"  图谱: {out}")
    print(f"  过程: 会话记录.md   产物: 图谱导出/   素材: 素材/   复习记录: 复习/<知识点>/")
    print(f"  之后: python tools/graph_ops.py <子命令> --graph {out}")


def cmd_finish(g, G_, args):
    """学完收档：把 学习记录/正在学习/<名称> 移到 学习记录/已经学完/<名称>。"""
    base = os.path.abspath(args.base)
    src = os.path.join(base, "正在学习", args.name)
    if not os.path.isdir(src):
        print(f"未找到 正在学习\\{args.name}")
        return
    dst_root = os.path.join(base, "已经学完")
    os.makedirs(dst_root, exist_ok=True)
    dst = os.path.join(dst_root, args.name)
    if os.path.exists(dst):
        print(f"已经学完\\{args.name} 已存在，请先改名或合并")
        return
    shutil.move(src, dst)
    print(f"已归档: 正在学习\\{args.name} → 已经学完\\{args.name}")


def cmd_progress(g, G_, args):
    """单目标进度面板。综合 = 0.6×目标掌握度(归一) + 0.4×路径完成度。"""
    nodes = g["nodes"]
    goal = g.get("goal", "")
    gm = nodes.get(goal, {}).get("m", 0.0) if goal in nodes else 0.0
    m_norm = min(gm / MASTERED, 1.0)
    done = 0.0
    path_txt = ""
    remaining = None
    res = G_.dijkstra(goal) if goal in nodes else None
    if res:
        edges, total = res
        remaining = total
        seq = [edges[0][0]] + [b for _, b, _ in edges]
        parts = []
        acc = 0.0
        for n in seq:
            mn = nodes.get(n, {}).get("m", 0.0)
            acc += min(mn / MASTERED, 1.0)
            tag = "✓" if mn >= MASTERED else f"m={mn:.2f}"
            parts.append(f"{n}({tag})")
        done = acc / len(seq)
        path_txt = " → ".join(parts)
    init = g["meta"].get("initial_cost", 0.0)
    if init <= 0 and remaining is not None:
        g.setdefault("meta", {})["initial_cost"] = remaining
        save_graph(args.graph, g)
        init = remaining
    red = 0.0
    if init > 0 and remaining is not None:
        red = max(0.0, 1.0 - remaining / init)
    overall = 100 * (0.6 * m_norm + 0.4 * done)
    bar = "▓" * int(round(overall / 5)) + "░" * (20 - int(round(overall / 5)))
    qlog = os.path.join(args.state, "quiz_log.jsonl")
    quizzes, confs, grades = 0, [], []
    if os.path.exists(qlog):
        with open(qlog, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("undo_of"):
                    continue
                quizzes += 1
                confs.append(r["conf"])
                grades.append(r["grade"])
    calib = (sum(confs) / len(confs) - 100 * sum(grades) / len(grades)) if confs else 0.0
    due = due_nodes(g)
    procs = g["meta"].get("process", [])
    last = procs[-1]["ts"] if procs else "-"
    print(f"目标: {goal}")
    print(f"综合进度: {bar} {overall:.0f}%")
    print(f"  目标掌握度 m={gm:.2f} (达标线 {MASTERED:.1f})   路径完成度 {done*100:.0f}%   权重减小率 {red*100:.0f}%")
    if path_txt:
        print(f"  当前路径: {path_txt}")
        print(f"  剩余总代价: {remaining:.2f} (初始 {init:.2f})")
    else:
        print("  当前路径: 暂不可达（缺边/缺锚点，先探寻）")
    print(f"  练习: 测验 {quizzes} 次 · 到期复习 {len(due)} 个 · 校准误差 {calib:+.1f}% (正值=高估自己)")
    print(f"  最近活动: {last}")


def cmd_progress_all(g, G_, args):
    """全部学习进度总览：扫描 正在学习 下所有目标 + 已经学完 清单。"""
    base = os.path.abspath(args.base)
    ongoing = os.path.join(base, "正在学习")
    done_dir = os.path.join(base, "已经学完")
    rows = []
    if os.path.isdir(ongoing):
        for name in sorted(os.listdir(ongoing)):
            gp = os.path.join(ongoing, name, "graph.json")
            if not os.path.isfile(gp):
                continue
            with open(gp, encoding="utf-8") as f:
                gg = json.load(f)
            GG = G(gg)
            goal = gg.get("goal", name)
            nodes = gg["nodes"]
            gm = nodes.get(goal, {}).get("m", 0.0) if goal in nodes else 0.0
            m_norm = min(gm / MASTERED, 1.0)
            done = 0.0
            remaining = None
            res = GG.dijkstra(goal) if goal in nodes else None
            if res:
                edges, total = res
                remaining = total
                seq = [edges[0][0]] + [b for _, b, _ in edges]
                done = sum(min(nodes.get(n, {}).get("m", 0.0) / MASTERED, 1.0)
                           for n in seq) / len(seq)
            overall = 100 * (0.6 * m_norm + 0.4 * done)
            due = len(due_nodes(gg))
            procs = gg["meta"].get("process", [])
            last = procs[-1]["ts"] if procs else "-"
            rows.append((name, goal, overall, gm, remaining, due, last))
    print("=== 学习进度总览 ===")
    if not rows:
        print("(正在学习里还没有目标——说\"我想学习 X\"开始第一条线)")
    else:
        print(f"并行学习线: {len(rows)} 条")
        for name, goal, ov, gm, rem, due, last in rows:
            bar = "▓" * int(round(ov / 5)) + "░" * (20 - int(round(ov / 5)))
            rem_txt = "--" if rem is None else f"{rem:.2f}"
            print(f"  {goal:<14} 综合 {ov:>3.0f}%  目标m {gm:.2f}  剩余代价 {rem_txt:>6}  到期复习 {due}  最近 {last}")
            print(f"    [{name}] {bar}")
    if os.path.isdir(done_dir):
        done_names = sorted(os.listdir(done_dir))
        if done_names:
            print(f"已经学完: {len(done_names)} 个 → {', '.join(done_names)}")


def cmd_undo(g, G_, args):
    """回滚最近一次事件（误打分/误修正/误导入时用）。"""
    procs = g["meta"].get("process", [])
    if not procs:
        print("没有可撤销的事件。")
        return
    p = procs.pop()
    evt = p["evt"]
    if evt == "quiz":
        n = p["node"]
        d = g["nodes"].get(n)
        if d:
            d["m"] = p.get("old_m", d["m"])
            d["interval"] = p.get("old_interval", d.get("interval", 0))
            d["ef"] = p.get("old_ef", d.get("ef", 2.5))
            d["reviews"] = p.get("old_reviews", d.get("reviews", 0))
            d["last_review"] = p.get("old_last_review")
            if d.get("history"):
                d["history"].pop()
            append_jsonl(os.path.join(args.state, "quiz_log.jsonl"),
                         {"ts": now(), "node": n, "undo_of": p.get("ts")})
            print(f"已撤销测验: {n}  m 恢复为 {fmt_m(d['m'])}")
    elif evt == "adjust-r":
        e = find_edge(g, p["a"], p["b"])
        if e:
            e["r"] = p["old_r"]
            print(f"已撤销 r 修正: {p['a']}-{p['b']} 恢复为 {p['old_r']:.2f}")
    elif evt == "import-node":
        n = p["node"]
        if any(n in (e["a"], e["b"]) for e in g["edges"]):
            print(f"节点 {n} 已有关联边，仅移除事件记录，不删节点")
        else:
            g["nodes"].pop(n, None)
            print(f"已移除导入节点: {n}")
    else:
        print(f"已撤销事件: {evt}")
    save_graph(args.graph, g)


def cmd_assess(g, G_, args):
    """单项评价：分数 + 多标签，写回节点 score/tags。"""
    nodes = g["nodes"]
    if args.node not in nodes:
        print(f"节点不存在: {args.node}")
        return
    recs = load_quiz_records(args.state, args.node)
    score, tags = assess_node(g, args.node, recs)
    m = nodes[args.node]["m"]
    w = 1 + LAMBDA * (1 - m)
    print(f"评价 · {args.node}")
    print(f"  分数: {score}/100   (m×50 + 复习×15 + 表现×20 + 校准×15)")
    print(f"  标签: {' · '.join(tags)}")
    print(f"  权值系数 (1+λ(1−m)): {w:.2f}   (越熟悉越小, 复习后随 m 下降)")
    nodes[args.node]["score"] = score
    nodes[args.node]["tags"] = tags
    save_graph(args.graph, g)
    print("  [已写入节点 score/tags]")


def cmd_assess_all(g, G_, args):
    """全部知识点评价总览（写回每个节点的 score/tags）。"""
    print("=== 知识点评价总览 ===")
    for n in sorted(g["nodes"]):
        recs = load_quiz_records(args.state, n)
        score, tags = assess_node(g, n, recs)
        g["nodes"][n]["score"] = score
        g["nodes"][n]["tags"] = tags
        m = g["nodes"][n]["m"]
        print(f"  {n:<14} {score:>3}分  m={m:.2f}  {' · '.join(tags[:4])}")
    save_graph(args.graph, g)


def cmd_review_log(g, G_, args):
    """复习成绩单落盘：复习结束后必调。生成 复习/<点>/日期-第N次.md（确定性成绩单），问答逐字由 AI 补填。"""
    nodes = g["nodes"]
    if args.node not in nodes:
        print(f"节点不存在: {args.node}")
        return
    d = nodes[args.node]
    recs = load_quiz_records(args.state, args.node)
    last = recs[-1] if recs else None
    if last is None:
        print(f"{args.node} 还没有测验记录——先完成复习的 quiz 再落记录。")
        return
    m_before = last.get("m_old", d["m"])
    m_after = d["m"]
    conf, grade = last["conf"], last["grade"]
    score, tags = assess_node(g, args.node, recs)
    d["score"] = score
    d["tags"] = tags
    w_before = 1 + LAMBDA * (1 - m_before)
    w_after = 1 + LAMBDA * (1 - m_after)
    nxt = today() + dt.timedelta(days=int(d.get("interval", 1)))
    folder = os.path.join(args.state, "复习", args.node)
    os.makedirs(folder, exist_ok=True)
    nth = len([f for f in os.listdir(folder) if f.endswith(".md")]) + 1
    fname = f"{today().strftime('%Y-%m-%d')}-第{nth}次.md"
    path = os.path.join(folder, fname)
    lines = [
        f"# 复习记录 · {args.node} · 第 {nth} 次",
        "",
        f"- 时间: {now()}",
        f"- 复习前: m={fmt_m(m_before)}   间隔: {d.get('interval', '-')} 天",
        f"- 评分: 信心 {conf} / 成绩 {grade}",
        f"- 复习后: m={fmt_m(m_after)}   下次复习: {nxt}",
        f"- **成绩单**: 分数 {score}/100   标签: {' · '.join(tags)}",
        f"- 权值系数 (1+λ(1−m)): {w_before:.2f} → {w_after:.2f}",
        "",
        "## 三轮问答逐字记录（AI 补填）",
        "",
        "- 一轮 无提示回忆: 问: / 答:",
        "- 二轮 变式/反例: 问: / 答:",
        "- 三轮 连接抽问: 问: / 答:",
        "- 提示级别: 无 / 名词提醒 / 例子 / 重讲",
        "- 暴露问题 / 下次注意:",
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    save_graph(args.graph, g)
    print(f"已生成复习记录: {path}")
    print(f"  成绩单: {score}/100   {' · '.join(tags)}")
    print(f"  权值系数: {w_before:.2f} → {w_after:.2f}")
    print("  [AI 请把三轮问答逐字填入该文件的问答区]")


def _render_timeline(g):
    """把过程事件渲染成带时间戳的人类可读时间线。"""
    lines = ["# 学习时间线", ""]
    procs = g["meta"].get("process", [])
    if not procs:
        lines.append("（还没有学习事件）")
        return lines
    cur_date = None
    for p in procs:
        ts = p.get("ts", "-")
        date = ts[:10] if len(ts) >= 10 else "-"
        if date != cur_date:
            cur_date = date
            lines.append(f"\n## {date}")
        t = ts[11:16] if len(ts) >= 16 else ""
        evt = p.get("evt")
        if evt == "explore":
            lines.append(f"- {t} 探寻 · 标定「{p.get('node')}」 自评「{p.get('self_report')}」/实测「{p.get('measured')}」 → m={p.get('m')}")
        elif evt == "teach":
            lines.append(f"- {t} 第{p.get('lesson')}课 · 教学「{p.get('b')}」 锚点「{p.get('a')}」(r={p.get('r')})")
        elif evt == "quiz":
            h = None
            for hh in g["nodes"].get(p.get("node"), {}).get("history", []):
                if (hh.get("ts") == ts and hh.get("conf") == p.get("conf")
                        and hh.get("grade") == p.get("grade")):
                    h = hh
                    break
            if h:
                lines.append(f"- {t} 测验「{p.get('node')}」 信心{p.get('conf')} 成绩{p.get('grade')} → m {h['m_old']}→{h['m_new']}")
            else:
                lines.append(f"- {t} 测验「{p.get('node')}」 信心{p.get('conf')} 成绩{p.get('grade')}")
        elif evt == "feel":
            lines.append(f"- {t} 感受收口 · {p.get('text')}")
        elif evt == "adjust-r":
            lines.append(f"- {t} 感受反馈 · r({p.get('a')},{p.get('b')}) {p.get('old_r')}→{p.get('new_r')}")
        elif evt == "import-node":
            lines.append(f"- {t} 材料导入 · 入图「{p.get('node')}」（{p.get('source')}）")
        elif evt == "graduate":
            lines.append(f"- {t} 毕业 · 导出终局图谱与学习报告")
        elif evt == "commit":
            lines.append(f"- {t} ▸ 提交 c{p.get('seq')}: {p.get('msg')}")
        elif evt == "node-added":
            lines.append(f"- {t} 加点 · 「{p.get('node')}」（{p.get('source')}）")
        elif evt == "edge-added":
            lines.append(f"- {t} 建边 · {p.get('a')} —{p.get('r')} ({p.get('type')})→ {p.get('b')}（{p.get('source')}）")
        else:
            lines.append(f"- {t} {evt}")
    return lines


def cmd_timeline(g, G_, args):
    """渲染并导出学习时间线日志。"""
    lines = _render_timeline(g)
    print("\n".join(lines))
    export_dir = os.path.join(args.state, "图谱导出")
    os.makedirs(export_dir, exist_ok=True)
    with open(os.path.join(export_dir, "学习时间线.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n已导出: {os.path.join(export_dir, '学习时间线.md')}")


def cmd_commit(g, G_, args):
    """像 git commit 一样提交一笔学习记录：消息 + 自上次提交以来的变更摘要。"""
    commits = g["meta"].setdefault("commits", [])
    last_ts = commits[-1]["ts"] if commits else ""
    procs = [p for p in g["meta"].get("process", []) if p.get("ts", "") > last_ts]
    changes = []
    m_deltas = {}
    for p in procs:
        evt = p.get("evt")
        if evt == "teach":
            changes.append(f"教学「{p['b']}」(锚点「{p['a']}」)")
        elif evt == "quiz":
            key = p.get("node")
            if key not in m_deltas:
                h = None
                for hh in g["nodes"].get(key, {}).get("history", []):
                    if (hh.get("ts") == p.get("ts") and hh.get("conf") == p.get("conf")
                            and hh.get("grade") == p.get("grade")):
                        h = hh
                        break
                if h:
                    m_deltas[key] = (h["m_old"], h["m_new"])
        elif evt == "adjust-r":
            changes.append(f"r({p['a']},{p['b']}) {p['old_r']}→{p['new_r']}")
        elif evt == "import-node":
            changes.append(f"导入「{p['node']}」")
        elif evt == "explore":
            changes.append(f"探寻「{p['node']}」")
    quiz_lines = [f"「{k}」 m {a}→{b}" for k, (a, b) in m_deltas.items()]
    if quiz_lines:
        changes.append("测验 " + ", ".join(quiz_lines))
    seq = len(commits) + 1
    msg = args.message or (changes[0] if changes else "学习进度更新")
    rec = {"seq": seq, "ts": now(), "msg": msg, "changes": changes}
    commits.append(rec)
    process(g, "commit", seq=seq, msg=msg)
    save_graph(args.graph, g)
    print(f"[c{seq}] {rec['ts']}  {msg}")
    for ch in changes:
        print(f"      - {ch}")


def cmd_log(g, G_, args):
    """像 git log 一样回望提交历史。"""
    commits = g["meta"].get("commits", [])
    if not commits:
        print("还没有提交记录（每课/每次复习结束后 commit）。")
        return
    if args.ref:
        for c in commits:
            if str(c["seq"]) == args.ref or args.ref in c["msg"]:
                print(f"[c{c['seq']}] {c['ts']}")
                print(f"  消息: {c['msg']}")
                for ch in c.get("changes", []):
                    print(f"    - {ch}")
                return
        print(f"未找到提交: {args.ref}")
        return
    print("提交历史 (log):")
    for c in commits:
        print(f"  c{c['seq']:<4} {c['ts']}  {c['msg']}")


def cmd_capture(g, G_, args):
    """捕获读书札记：疑问/感悟 落为带时间戳的文件（base=工作区根，札记在其下 读书札记/）。"""
    folder = os.path.join(os.path.abspath(args.base), "读书札记")
    os.makedirs(folder, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    fname = f"{stamp}-{args.type}-{args.title}.md"
    path = os.path.join(folder, fname)
    note = args.note or "（待填）"
    if args.type == "疑问":
        body = [
            f"# 疑问 · {args.title}", "",
            f"- 时间: {now()}",
            "- 出处: （待填：书名/章节/页码）",
            "- 原文: > （待填摘录）",
            f"- 我的困惑: {note}",
            "- 状态: 待处理",
            "- 解答: （AI 填写：用已知作锚讲解，带 L1–L5 与来源）",
            "- 关联知识点: （待填：涉及哪个目标/哪个点；若缺前置知识 → 建议补进学习路径）",
            "",
        ]
    else:
        body = [
            f"# 感悟 · {args.title}", "",
            f"- 时间: {now()}",
            "- 出处: （待填：书名/章节/页码）",
            "- 原文: > （待填摘录）",
            f"- 我的想法: {note}",
            "- 状态: 待处理",
            "- AI 提炼: （待填：像不像 X 与 Y 的关系？还是全新洞见？）",
            "- 入图结果: （待填：建边 X-Y r=.. 类型=类比 来源=我的感悟 / 未入图原因）",
            "",
        ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    print(f"已捕获: {path}")
    print("  [疑问 → 立即尝试用已知作锚解答；感悟 → 提炼后提议建边]")


def cmd_captures(g, G_, args):
    """列出读书札记收件箱（base=工作区根，扫描其下 读书札记/）。"""
    folder = os.path.join(os.path.abspath(args.base), "读书札记")
    if not os.path.isdir(folder):
        print("读书札记还没有内容（说'记录个疑问'或'有个感悟'开始捕获）。")
        return
    files = sorted(f for f in os.listdir(folder) if f.endswith(".md"))
    if not files:
        print("读书札记还没有内容（说'记录个疑问'或'有个感悟'开始捕获）。")
        return
    counts = {}
    print(f"读书札记 ({len(files)} 条):")
    for fn in files:
        status = "待处理"
        with open(os.path.join(folder, fn), encoding="utf-8") as f:
            for line in f:
                if line.startswith("- 状态:"):
                    status = line.split("状态:")[-1].strip()
                    break
        counts[status] = counts.get(status, 0) + 1
        print(f"  [{status}] {fn}")
    print("  状态统计: " + ", ".join(f"{k} {v} 条" for k, v in sorted(counts.items())))


def cmd_add_node(g, G_, args):
    """手工加点：读书札记的疑问/感悟落地为知识点。"""
    if args.name in g["nodes"]:
        print(f"节点已存在: {args.name}")
        return
    g["nodes"][args.name] = {"m": args.m, "type": args.type, "def": args.def_,
                             "source": args.source, "fact_level": args.level,
                             "views": ["主流"], "history": []}
    process(g, "node-added", node=args.name, source=args.source)
    save_graph(args.graph, g)
    print(f"已加节点: {args.name} (m={args.m}, 来源={args.source})")


def cmd_add_edge(g, G_, args):
    """手工建边：感悟/疑问的连接落地（默认来源=我的感悟）。"""
    a, b = args.a, args.b
    for n in (a, b):
        if n not in g["nodes"]:
            print(f"节点不存在: {n}（先 add-node 或确认已入图）")
            return
    if find_edge(g, a, b):
        print(f"边 {a}-{b} 已存在")
        return
    g["edges"].append({"a": a, "b": b, "r": args.r, "type": args.type,
                       "why": args.why, "source": args.source})
    process(g, "edge-added", a=a, b=b, r=args.r, type=args.type, source=args.source)
    save_graph(args.graph, g)
    print(f"已建边: {a} —{args.r:.2f} ({args.type})→ {b}")
    print(f"  依据: {args.source}   说明: {args.why or '-'}")
    print("  这条边会显示在知识路径图/毕业图谱里为「我的连接」")


def cmd_review_node(g, G_, args):
    """复习卡：输出某点的定义/来源/复习史/邻居边，供 LLM 组织三轮复习提问。"""
    nodes = g["nodes"]
    if args.node not in nodes:
        print(f"节点不存在: {args.node}")
        return
    d = nodes[args.node]
    print(f"复习卡 · {args.node}   m={d['m']:.2f}")
    print(f"  定义: {d.get('def', '-')}")
    print(f"  来源: [{d.get('fact_level', 'L5')}] {d.get('source', '-')}")
    print(f"  复习史: {d.get('reviews', 0)} 次   上次: {d.get('last_review', '-')}   间隔: {d.get('interval', '-')} 天")
    for h in d.get("history", []):
        print(f"    - {h['ts']} 信心{h.get('conf', '-')} 成绩{h.get('grade', '-')}")
    print("  邻居（连接抽问题材）:")
    for e in g["edges"]:
        if e["a"] == args.node:
            print(f"    - {e['b']}  r={e['r']:.2f} ({e['type']})  {e.get('why', '')}")
        elif e["b"] == args.node:
            print(f"    - {e['a']}  r={e['r']:.2f} ({e['type']})  {e.get('why', '')}")
    print("  [复习课不重讲: 无提示回忆 → 变式/反例 → 连接抽问; 答不上才逐级提示]")


def cmd_review(g, G_, args):
    due = due_nodes(g)
    print("到期复习:" if due else "今天没有到期复习。")
    for n in due:
        d = g["nodes"][n]
        print(f"  - {n} (m={fmt_m(d['m'])})")


def cmd_feel(g, G_, args):
    text = " ".join(args.text)
    rec = {"ts": now(), "text": text}
    process(g, "feel", text=text[:80])
    if args.r:
        a, b, new_r = args.r[0], args.r[1], float(args.r[2])
        e = find_edge(g, a, b)
        if not e:
            print(f"边不存在: {a}-{b}")
            return
        old_r = e["r"]
        e["r"] = new_r
        rec["r_change"] = {"a": a, "b": b, "old": old_r, "new": new_r}
        process(g, "adjust-r", a=a, b=b, old_r=old_r, new_r=new_r)
    save_graph(args.graph, g)
    if args.r:
        print(f"[感受] 已记录。r({args.r[0]},{args.r[1]}): {rec['r_change']['old']:.2f} → {rec['r_change']['new']:.2f}")
        print("  建议 /plan 查看路径是否换锚点")
    else:
        print("[感受] 已记录。")
    append_jsonl(os.path.join(args.state, "feedback.jsonl"), rec)


def cmd_calibrate(g, G_, args):
    log = os.path.join(args.state, "quiz_log.jsonl")
    if not os.path.exists(log):
        print("暂无测验记录。")
        return
    agg = {}
    with open(log, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            a = agg.setdefault(r["node"], {"conf": [], "grade": []})
            a["conf"].append(r["conf"])
            a["grade"].append(r["grade"])
    print(f"{'节点':<8}{'次数':<6}{'平均信心':<10}{'平均成绩':<10}备注")
    for n, a in sorted(agg.items()):
        ac = sum(a["conf"]) / len(a["conf"])
        ag = sum(a["grade"]) / len(a["grade"])
        note = ""
        if ac >= 80 and ag <= 0.5:
            note = "⚠ 自欺风险: 信心高成绩低"
        elif ac <= 60 and ag >= 0.9:
            note = "保守低估, 可上调难度"
        elif ag < 0.8:
            note = "继续回炉"
        print(f"{n:<8}{len(a['conf']):<6}{ac:<10.1f}{ag:<10.2f}{note}")


def cmd_graph(g, G_, args):
    nodes = g["nodes"]
    for cond, name, mark in [
        (lambda n: nodes[n]["m"] >= MASTERED, "已知区", "✓"),
        (lambda n: 0.3 <= nodes[n]["m"] < MASTERED, "半知区", "◐"),
        (lambda n: nodes[n]["m"] < 0.3, "未知区", "○"),
    ]:
        items = [f"{mark}{n}({fmt_m(nodes[n]['m'])})" for n in nodes if cond(n)]
        print(f"{name}: {', '.join(items) or '-'}")
    print("边:")
    for e in g["edges"]:
        print(f"  {e['a']} --({e['r']:.2f},{e['type']})--> {e['b']}")
    goal = g.get("goal", "")
    path = G_.dijkstra(goal)
    if path:
        edges, total = path
        route = " → ".join([edges[0][0]] + [b for _, b, _ in edges])
        print(f"当前最优路径: {route}  (总代价 {total:.2f})")
    export_dir = os.path.join(args.state, "图谱导出")
    os.makedirs(export_dir, exist_ok=True)
    lines = ["graph LR"]
    for e in g["edges"]:
        lines.append(f"  {e['a']}(({e['a']}<br/>m={fmt_m(nodes[e['a']]['m'])}))"
                     f" -->|r={e['r']:.2f} {e['type']}|"
                     f" {e['b']}(({e['b']}<br/>m={fmt_m(nodes[e['b']]['m'])}))")
    with open(os.path.join(export_dir, "graph.mmd"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已导出: {os.path.join(export_dir, 'graph.mmd')}")


def cmd_graduate(g, G_, args):
    nodes = g["nodes"]
    export_dir = os.path.join(args.state, "图谱导出")
    os.makedirs(export_dir, exist_ok=True)
    procs = g["meta"].get("process", [])
    taught = [(p, p.get("lesson", 0)) for p in procs if p.get("evt") == "teach"]
    adjust_map = {frozenset((p["a"], p["b"])): p for p in procs if p.get("evt") == "adjust-r"}
    taught_pairs = {frozenset((p["a"], p["b"])) for p, _ in taught}
    imported = [p for p in procs if p.get("evt") == "import-node"]
    mmd = ["graph LR"]
    for p, lesson in taught:
        a, b = p["a"], p["b"]
        adj = adjust_map.get(frozenset((a, b)))
        if adj:
            label = f"r={adj['old_r']:.2f}→{adj['new_r']:.2f} · 第{lesson}课 · 感受修正"
        else:
            e = find_edge(g, a, b)
            r = e["r"] if e else p.get("r", 0)
            label = f"r={r:.2f} · 第{lesson}课"
        mmd.append(f"  {a}(({a}<br/>m={fmt_m(nodes[a]['m'])}))"
                   f" -->|{label}|"
                   f" {b}(({b}<br/>m={fmt_m(nodes[b]['m'])}))")
    for p in procs:
        if p.get("evt") != "adjust-r":
            continue
        a, b = p["a"], p["b"]
        if frozenset((a, b)) in taught_pairs:
            continue
        mmd.append(f"  {a}(({a}<br/>m={fmt_m(nodes[a]['m'])}))"
                   f" -.->|r={p['old_r']:.2f}→{p['new_r']:.2f} · 感受反馈修正|"
                   f" {b}(({b}<br/>m={fmt_m(nodes[b]['m'])}))")
    for e in g["edges"]:
        a, b = e["a"], e["b"]
        if frozenset((a, b)) in taught_pairs or frozenset((a, b)) in adjust_map:
            continue
        mmd.append(f"  {a}(({a}<br/>m={fmt_m(nodes[a]['m'])}))"
                   f" -.->|r={e['r']:.2f} · {e['type']}|"
                   f" {b}(({b}<br/>m={fmt_m(nodes[b]['m'])}))")
    for p in imported:
        n = p["node"]
        mmd.append(f"  {n}(({n}<br/>m={fmt_m(nodes[n]['m'])} · 来自笔记))")
    with open(os.path.join(export_dir, "graduate.mmd"), "w", encoding="utf-8") as f:
        f.write("\n".join(mmd) + "\n")

    save_graph(os.path.join(export_dir, "graduate.json"), g)

    rep = ["# 学习报告（知径）", "", f"生成时间: {now()}", ""]
    rep.append("\n## 学习时间线")
    tl = _render_timeline(g)
    rep.extend(tl[1:])
    commits = g["meta"].get("commits", [])
    if commits:
        rep.append("\n## 提交历史")
        for c in commits:
            rep.append(f"- [c{c['seq']}] {c['ts']}  {c['msg']}")
            for ch in c.get("changes", []):
                rep.append(f"    - {ch}")
    rep.append("\n## 成绩单")
    rep.append("| 知识点 | 分数 | m | 难度 | 掌握 | 熟练 | 稳定 | 卡点 | 复习次数 |")
    rep.append("|---|---|---|---|---|---|---|---|---|")
    scored = []
    for n, d in nodes.items():
        recs = load_quiz_records(args.state, n)
        score, tags = assess_node(g, n, recs)
        g["nodes"][n]["score"] = score
        g["nodes"][n]["tags"] = tags
        stab = next((t for t in tags if t in ("稳定", "波动", "退化中")), "-")
        kd = "卡点" if "卡点" in tags else "流畅"
        scored.append((n, d, score, tags, stab, kd))
    for n, d, score, tags, stab, kd in sorted(scored, key=lambda x: -x[2]):
        rep.append(f"| {n} | {score} | {fmt_m(d['m'])} | {tags[0]} | {tags[1]} | {tags[2]} | {stab} | {kd} | {d.get('reviews', 0)} |")
    rep.append("\n## 知识点")
    for n, d in nodes.items():
        rep.append(f"\n### {n}   (m={fmt_m(d['m'])})")
        rep.append(f"- 定义: {d.get('def', '-')}")
        rep.append(f"- 来源: [{d.get('fact_level', 'L5')}] {d.get('source', '-')}")
        rep.append(f"- 复习次数: {d.get('reviews', 0)}")
        recs = load_quiz_records(args.state, n)
        score, tags = assess_node(g, n, recs)
        g["nodes"][n]["score"] = score
        g["nodes"][n]["tags"] = tags
        rep.append(f"- 评价: {score}/100 分   标签: {' · '.join(tags)}")
        for h in d.get("history", []):
            rep.append(f"  - {h['ts']} 测验: 信心{h['conf']} 成绩{h['grade']}  m {h['m_old']}→{h['m_new']}")
    rep.append("\n## 关联")
    for e in g["edges"]:
        rep.append(f"- {e['a']} —{e['r']:.2f} ({e['type']})→ {e['b']}: {e.get('why', '')}")
    with open(os.path.join(export_dir, "学习报告.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")

    process(g, "graduate")
    save_graph(args.graph, g)
    print(f"已导出: {os.path.join(export_dir, 'graduate.mmd')}")
    print(f"已导出: {os.path.join(export_dir, 'graduate.json')}")
    print(f"已导出: {os.path.join(export_dir, '学习报告.md')}")


def cmd_import(g, G_, args):
    # 相对路径按图谱文件所在目录解析（与 /import 在终端里的使用习惯一致）
    scan_path = args.path
    if not os.path.isabs(scan_path):
        scan_path = os.path.join(args.state, scan_path)
    found = []
    for root, _, files in os.walk(scan_path):
        for fn in files:
            if not fn.lower().endswith((".md", ".txt")):
                continue
            fp = os.path.join(root, fn)
            with open(fp, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    s = line.strip()
                    if s.startswith("#"):
                        title = s.lstrip("#").strip()
                        if title and title not in g["nodes"]:
                            found.append((title, f"{os.path.relpath(fp, args.state)}:{i}"))
    print(f"候选知识点 ({len(found)}):")
    for title, src in found:
        print(f"  - {title}   ← {src}")
    if args.commit:
        added = 0
        for title, src in found:
            g["nodes"][title] = {
                "m": 0.0, "type": "概念", "def": title,
                "source": src, "fact_level": "L5", "views": [],
                "history": []}
            process(g, "import-node", node=title, source=src)
            added += 1
        save_graph(args.graph, g)
        print(f"已入图 {added} 个（m=0，待探寻/确认）。")


def main():
    ap = argparse.ArgumentParser(prog="graph_ops", description="知径确定性计算工具")
    ap.add_argument("--graph", default="graph.json")
    ap.add_argument("--state", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("plan")
    sub.add_parser("teach-next")
    q = sub.add_parser("quiz")
    q.add_argument("node")
    q.add_argument("--grade", type=float, required=True, choices=[0, 0.5, 1])
    q.add_argument("--conf", type=int, required=True)
    sub.add_parser("review")
    rn = sub.add_parser("review-node")
    rn.add_argument("node")
    rl = sub.add_parser("review-log")
    rl.add_argument("node")
    sub.add_parser("undo")
    sub.add_parser("progress")
    sub.add_parser("timeline")
    c = sub.add_parser("commit")
    c.add_argument("-m", "--message", default=None)
    l = sub.add_parser("log")
    l.add_argument("ref", nargs="?")
    cp = sub.add_parser("capture")
    cp.add_argument("--type", required=True, choices=["疑问", "感悟"])
    cp.add_argument("--title", required=True)
    cp.add_argument("-m", "--note", default="")
    cp.add_argument("--base", default=".")
    cs = sub.add_parser("captures")
    cs.add_argument("--base", default=".")
    an = sub.add_parser("add-node")
    an.add_argument("name")
    an.add_argument("--m", type=float, default=0.3)
    an.add_argument("--type", default="概念")
    an.add_argument("--def", dest="def_", default="")
    an.add_argument("--source", default="读书札记")
    an.add_argument("--level", default="L4")
    ae = sub.add_parser("add-edge")
    ae.add_argument("a")
    ae.add_argument("b")
    ae.add_argument("--r", type=float, default=0.8)
    ae.add_argument("--type", default="类比")
    ae.add_argument("--why", default="")
    ae.add_argument("--source", default="我的感悟")
    a = sub.add_parser("assess")
    a.add_argument("node")
    sub.add_parser("assess-all")
    pa = sub.add_parser("progress-all")
    pa.add_argument("--base", default="学习记录")
    n = sub.add_parser("init-goal")
    n.add_argument("name")
    n.add_argument("--goal", required=True)
    n.add_argument("--base", default="学习记录")
    f2 = sub.add_parser("finish")
    f2.add_argument("name")
    f2.add_argument("--base", default="学习记录")
    f = sub.add_parser("feel")
    f.add_argument("text", nargs="+")
    f.add_argument("--r", nargs=3, metavar=("A", "B", "NEW_R"))
    sub.add_parser("calibrate")
    sub.add_parser("graph")
    sub.add_parser("graduate")
    i = sub.add_parser("import-headings")
    i.add_argument("path")
    i.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    args.state = args.state or os.path.dirname(os.path.abspath(args.graph))
    if args.cmd == "init-goal":
        cmd_init(None, None, args)
        return
    if args.cmd == "finish":
        cmd_finish(None, None, args)
        return
    if args.cmd == "progress-all":
        cmd_progress_all(None, None, args)
        return
    if args.cmd == "capture":
        cmd_capture(None, None, args)
        return
    if args.cmd == "captures":
        cmd_captures(None, None, args)
        return
    g = load_graph(args.graph)
    G_ = G(g)
    audit(args.state, f"{args.cmd} {sys.argv[2:] if len(sys.argv) > 2 else ''}")

    {
        "status": cmd_status,
        "plan": cmd_plan,
        "teach-next": cmd_teach_next,
        "quiz": cmd_quiz,
        "review": cmd_review,
        "review-node": cmd_review_node,
        "review-log": cmd_review_log,
        "add-node": cmd_add_node,
        "add-edge": cmd_add_edge,
        "undo": cmd_undo,
        "progress": cmd_progress,
        "timeline": cmd_timeline,
        "commit": cmd_commit,
        "log": cmd_log,
        "assess": cmd_assess,
        "assess-all": cmd_assess_all,
        "feel": cmd_feel,
        "calibrate": cmd_calibrate,
        "graph": cmd_graph,
        "graduate": cmd_graduate,
        "import-headings": cmd_import,
    }[args.cmd](g, G_, args)


if __name__ == "__main__":
    main()
