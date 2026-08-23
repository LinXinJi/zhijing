# -*- coding: utf-8 -*-
"""
知径 · 最小权重学习路径算法原型（终端演示）
==========================================
用法:  python demo_path.py

验证七个核心机制（示例主题: 从"斜率/函数"出发学"导数"）:
  1  加权图与步进代价公式
  2  最优路径 (多源 Dijkstra): 直连 vs 中转的权衡
  3  备选路径代价对比 (直连 / 一个新点中转 / 两个新点中转)
  4  教学顺序 (贪心前沿扩张: 每步新点都挂在已知区上)
  5  练习巩固: 成绩反馈更新掌握度 m -> 权重逐步减小
  6  感受反馈: 修正关联度 r -> 自动换锚点重规划
  7  终局知识图谱导出 (Mermaid, 描述学习过程)
"""
import heapq

LAMBDA = 3.0          # 新知识点惩罚系数 λ
MASTERED = 0.8        # m >= 该值视为已掌握
MASTERED_COST = 0.7   # 已掌握目标点的步进代价系数

# ---------- 图谱定义 ----------
NODES = {
    "算术":   0.95,
    "方程":   0.90,
    "函数":   0.85,
    "函数图像": 0.80,
    "斜率":   0.80,   # ↑ 以上为已知区 S (m >= 0.8)
    "切线":   0.30,
    "瞬时速度": 0.20,
    "极限":   0.10,
    "连续":   0.15,
    "导数":   0.10,   # ← 目标
}

# (a, b, 关联度 r, 边类型)
EDGES = [
    ("函数",   "极限",   0.70, "前提"),
    ("方程",   "极限",   0.50, "前提"),
    ("极限",   "连续",   0.90, "前提"),
    ("连续",   "导数",   0.75, "前提"),
    ("连续",   "函数",   0.60, "对比"),
    ("斜率",   "切线",   0.90, "类比"),
    ("函数图像", "切线",   0.80, "类比"),
    ("函数",   "切线",   0.60, "类比"),
    ("切线",   "导数",   0.90, "前提"),
    ("斜率",   "导数",   0.45, "类比"),
    ("斜率",   "瞬时速度", 0.60, "类比"),
    ("函数",   "瞬时速度", 0.50, "类比"),
    ("瞬时速度", "导数",   0.80, "类比"),
    ("极限",   "导数",   0.65, "前提"),
    ("算术",   "方程",   0.70, "前提"),
]


class Graph:
    def __init__(self, nodes, edges):
        self.m = dict(nodes)
        self.adj = {}
        for a, b, r, t in edges:
            self.adj.setdefault(a, []).append((b, r, t))
            self.adj.setdefault(b, []).append((a, r, t))

    def cost(self, a, b, r):
        """步进代价: 从 a 学 b。b 已掌握则只付"连接价"，否则付新知识点代价。"""
        if self.m[b] >= MASTERED:
            return MASTERED_COST / r
        return (1.0 + LAMBDA * (1.0 - self.m[b])) / r

    def starts(self):
        return [k for k, v in self.m.items() if v >= MASTERED]

    def dijkstra(self, goal):
        """多源 Dijkstra: 从已知区 S 到目标的最小权重路径"""
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
            for v, r, t in self.adj.get(u, []):
                nd = d + self.cost(u, v, r)
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = (u, r, t)
                    heapq.heappush(pq, (nd, v))
        if goal not in prev:
            return None
        path = []
        cur = goal
        while cur in prev:
            u, r, t = prev[cur]
            path.append((u, cur, r, t))
            cur = u
        path.reverse()
        return path

    def path_cost(self, path):
        return sum(self.cost(u, v, r) for u, v, r, t in path)

    def teach_order(self, goal):
        """贪心前沿扩张: 每步只引入一个与已知区直接相邻、代价最低的新点。"""
        mastered = set(self.starts())
        steps = []
        while goal not in mastered:
            best = None
            for u in mastered:
                for v, r, t in self.adj.get(u, []):
                    if v in mastered:
                        continue
                    c = self.cost(u, v, r)
                    if best is None or c < best[0]:
                        best = (c, u, v, r, t)
            if best is None:
                return None  # 图不连通: 缺"桥梁"知识, 需回探寻补图
            c, u, v, r, t = best
            steps.append((u, v, r, t, c))
            mastered.add(v)
            self.m[v] = 0.9  # 上完课 + 练习通过 -> 掌握
        return steps


def show_path(g, title, goal):
    path = g.dijkstra(goal)
    if not path:
        print("  (不可达)")
        return
    print(title)
    for i, (u, v, r, t) in enumerate(path, 1):
        c = g.cost(u, v, r)
        tag = "已掌握" if g.m[v] >= MASTERED else f"m={g.m[v]:.2f}"
        print(f"  {i}. {u} -> {v}    r={r:.2f} ({t})    代价 {c:.2f}  [{tag}]")
    print(f"  总代价 = {g.path_cost(path):.2f}")
    return path


def route_cost(g, seq):
    total = 0.0
    for a, b in zip(seq, seq[1:]):
        r = next(r for (v, r, t) in g.adj[a] if v == b)
        total += g.cost(a, b, r)
    return total


print("=" * 66)
print("1. 加权图与步进代价公式")
print(f"   c(a->b) = (1 + λ·(1-m_b)) / r(a,b)     λ={LAMBDA}")
print(f"   m_b >= {MASTERED} 时 c = {MASTERED_COST}/r (已知点之间 = 纯连接价)")
g0 = Graph(NODES, EDGES)
print(f"   已知区 S = {g0.starts()}")
print(f"   目标 = 导数 (m=0.10)")

print("\n" + "=" * 66)
print("2. 最优路径 (多源 Dijkstra)")
show_path(Graph(NODES, EDGES), "   最优路径:", "导数")

print("\n" + "=" * 66)
print("3. 备选路径代价对比")
g3 = Graph(NODES, EDGES)
routes = [
    ("直连 (1跳): 斜率→导数", ["斜率", "导数"]),
    ("高关联中转 (2跳): 斜率→切线→导数", ["斜率", "切线", "导数"]),
    ("两个新点中转 (3跳): 函数→极限→连续→导数", ["函数", "极限", "连续", "导数"]),
]
for name, seq in routes:
    print(f"   {name:<38} 总代价 = {route_cost(g3, seq):.2f}")
print("   结论: 最优不是跳数最少, 而是关联度与掌握度权衡后的总代价最小。")

print("\n" + "=" * 66)
print("4. 教学顺序 (贪心前沿扩张: 每步新点都直接挂在已知区上)")
steps = Graph(NODES, EDGES).teach_order("导数")
for i, (u, v, r, t, c) in enumerate(steps, 1):
    print(f"   第{i}课: {u} -> {v}   (r={r:.2f}, {t})   代价 {c:.2f}   -> 上完后 m({v})=0.9")

print("\n" + "=" * 66)
print("5. 练习巩固: 成绩反馈更新 m -> 权重逐步减小")
g5 = Graph(NODES, EDGES)
before = g5.path_cost(g5.dijkstra("导数"))
g5.m["切线"] = 0.95   # 练习全对 -> m 升
g5.m["导数"] = 0.60   # 测验 80% -> 半掌握
after = g5.path_cost(g5.dijkstra("导数"))
print(f"   练习前 最优路径总代价 = {before:.2f}")
print(f"   练习后 最优路径总代价 = {after:.2f}   (切线 m=0.95 进入已知区, 路径变为 切线→导数)")
g5.m["导数"] = 0.85
print(f"   导数掌握后 斜率->导数 仅为 {g5.cost('斜率', '导数', 0.45):.2f}"
      f" (已知点之间 = 权重最小)")

print("\n" + "=" * 66)
print("6. 感受反馈: 修正关联度 r -> 自动换锚点重规划")
print("   反馈: 「切线的'斜率'类比没听懂; '函数图像上的切线'这个类比懂了」")
print("   -> r(斜率,切线) 0.90->0.70, r(函数图像,切线) 0.80->0.85")
print("   校准前最优: 斜率 -> 切线 -> 导数   (总代价 7.56)")
edges6 = []
for a, b, r, t in EDGES:
    if (a, b) == ("斜率", "切线"):
        edges6.append((a, b, 0.70, t))
    elif (a, b) == ("函数图像", "切线"):
        edges6.append((a, b, 0.85, t))
    else:
        edges6.append((a, b, r, t))
show_path(Graph(NODES, edges6), "   校准后最优:", "导数")
print("   结论: 感受反馈只改 r(怎么教), m(学会没有)仍由成绩决定 —— 08 的分工。")

print("\n" + "=" * 66)
print("7. 终局知识图谱导出 (Mermaid, 描述学习过程)")
print("```mermaid")
print("graph LR")
print("  斜率((斜率<br/>m=0.80)) -->|r=0.9 · 第1课| 切线((切线<br/>m=0.95))")
print("  切线 -->|r=0.9 · 第2课| 导数((导数<br/>m=0.88))")
print("  函数图像((函数图像<br/>m=0.80)) -.->|r=0.85 · 感受反馈换锚点| 切线")
print("  斜率 -.->|r=0.45 · 我自己发现的类比| 导数")
print("  函数((函数<br/>m=0.85)) -.->|计划备选路线 · 未走| 极限((极限<br/>m=0.10))")
print("  极限 -.->|未走| 连续((连续<br/>m=0.15))")
print("  导数 -.->|半知 · 待回炉| 瞬时速度((瞬时速度<br/>m=0.50))")
print("```")
print("   同时可导出 JSON / GraphML / Markdown 学习报告 (见 docs/10)。")
