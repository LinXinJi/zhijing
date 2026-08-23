# -*- coding: utf-8 -*-
"""
知径 · 终端教学 Agent（本地实现）
================================
用法:
  python zhijing.py                交互式会话（说"我想学习 X"开始）
  python zhijing.py /status        单条命令（脚本化）
  python zhijing.py --check        环境自检

可选: 设置环境变量 DEEPSEEK_API_KEY 后, 讲解/提问/解答自动交给 DeepSeek;
      未设置时用图谱内置内容讲解(同样可用)。

数据位置: 默认把「学习记录/读书札记/背景知识.md」放在当前目录(若当前目录有
AGENTS.md 或 学习记录), 否则放在本文件上级目录。可用 --base 覆盖。
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.abspath(__file__))

spec = importlib.util.spec_from_file_location(
    "graph_ops", os.path.join(REPO, "tools", "graph_ops.py"))
GO = importlib.util.module_from_spec(spec)
spec.loader.exec_module(GO)

MASTERED = GO.MASTERED


def run_ops(*args):
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["graph_ops"] + list(args)
    try:
        with contextlib.redirect_stdout(buf):
            GO.main()
    finally:
        sys.argv = old
    return buf.getvalue()


def workspace():
    cwd = os.getcwd()
    # 1) 当前目录就是工作区
    if os.path.isdir(os.path.join(cwd, "学习记录")):
        return cwd
    # 2) 本仓库嵌在工作区内（如 F:\个人成长\AI共学系统）→ 用父目录
    parent = os.path.dirname(REPO)
    if os.path.isdir(os.path.join(parent, "学习记录")):
        return parent
    # 3) 独立克隆：仓库根即工作区（学习数据被 .gitignore 排除）
    if os.path.exists(os.path.join(REPO, "AGENTS.md")):
        return REPO
    return cwd


_EOF = [False]


def input_(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        _EOF[0] = True
        return ""


def llm(prompt, system="你是知径，一个严谨的教学 AI。用中文回答，简洁、准确、带来源意识。"):
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return None
    body = {
        "model": os.environ.get("ZHIJING_MODEL", "deepseek-chat"),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": 0.3, "max_tokens": 1500,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"  [LLM 调用失败: {e}] 已改用图谱内置内容。")
        return None


# ---------- 目标发现 ----------
def find_goals(base):
    ongoing = os.path.join(base, "学习记录", "正在学习")
    if not os.path.isdir(ongoing):
        return []
    out = []
    for name in sorted(os.listdir(ongoing)):
        gp = os.path.join(ongoing, name, "graph.json")
        if os.path.isfile(gp):
            out.append(name)
    return out


def choose_goal(base):
    goals = find_goals(base)
    if len(goals) == 1:
        return goals[0]
    if not goals:
        print("学习记录\\正在学习 里还没有目标——说「我想学习 X」开始第一条学习线。")
        return None
    print("进行中的目标:")
    for i, g in enumerate(goals, 1):
        print(f"  {i}. {g}")
    s = input_("继续哪个? (序号): ")
    if s.isdigit() and 1 <= int(s) <= len(goals):
        return goals[int(s) - 1]
    return None


def graph_path(base, goal):
    return os.path.join(base, "学习记录", "正在学习", goal, "graph.json")


def load_graph(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_graph(path, g):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1)


def append_file(path, lines):
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------- 探寻 ----------
def explore(base, goal):
    gp = graph_path(base, goal)
    g = load_graph(gp)
    print("\n== 探寻 · 一阶段 ==")
    print("(宽) 这个主题你以前学过吗? 什么时候、什么场景? 一句话:")
    ans = input_("> ")
    if ans:
        g["meta"]["explore_brief"] = ans
    print("(中) 列出与目标相关的子主题, 逐个打标「会 / 见过 / 不会」, 输入「结束」停止:")
    while True:
        topic = input_("  主题: ")
        if not topic or topic in ("结束", "end", "q"):
            break
        mark = input_("  打标(会/见过/不会): ")
        d = {"m": 0.1, "type": "概念", "def": f"（待 AI 完善）{topic}",
             "source": "用户自述（探寻阶段）", "fact_level": "L5", "views": ["主流"],
             "history": []}
        if mark == "会":
            print("  (细) 合上材料, 用自己的话讲一遍「%s」:" % topic)
            talk = input_("  > ")
            if talk:
                d["m"] = 0.8
                measured = "讲得出"
            else:
                d["m"] = 0.6
                measured = "犹豫"
            d["def"] = talk or d["def"]
            d["history"].append({"ts": GO.now(), "evt": "explore",
                                 "self_report": "会", "measured": measured, "m": d["m"]})
            g["meta"].setdefault("process", []).append(
                {"ts": GO.now(), "evt": "explore", "node": topic,
                 "self_report": "会", "measured": measured, "m": d["m"]})
        elif mark == "见过":
            d["m"] = 0.3
            g["meta"]["process"].append(
                {"ts": GO.now(), "evt": "explore", "node": topic,
                 "self_report": "见过", "measured": "见过", "m": 0.3})
        else:
            d["m"] = 0.1
            g["meta"]["process"].append(
                {"ts": GO.now(), "evt": "explore", "node": topic,
                 "self_report": "不会", "measured": "不会", "m": 0.1})
        g["nodes"].setdefault(topic, d)
    interest = input_("兴趣评分(0-100, 回车跳过): ")
    if interest.isdigit():
        g["meta"].setdefault("interest", {})[g.get("goal", goal)] = int(interest)
    save_graph(gp, g)
    # 背景知识摘要
    lines = [f"\n## 探寻记录（追加于 {GO.now()}）", f"- 目标: {g.get('goal', goal)}",
             "- 新标定点: " + ", ".join(list(g["nodes"].keys()))
             + " (m: " + ", ".join(f"{k}={v['m']:.2f}" for k, v in g["nodes"].items()) + ")"]
    append_file(os.path.join(base, "背景知识.md"), lines)
    print("\n探寻完成。下一步: /plan 看学习路径 → 确认后开课。")


# ---------- 教学 ----------
def lesson(base, goal):
    gp = graph_path(base, goal)
    out = run_ops("--graph", gp, "teach-next")
    print(out)
    if "回炉" in out or "找不到" in out:
        return
    g = load_graph(gp)
    # 最近一次 teach 事件
    taught = [p for p in g["meta"].get("process", []) if p.get("evt") == "teach"]
    if not taught:
        return
    p = taught[-1]
    node = g["nodes"][p["b"]]
    print("\n== 讲解 ==")
    prompt = (
        f"你是知径教学 AI。给用户讲知识点「{p['b']}」：\n"
        f"定义: {node['def']}\n来源: [{node.get('fact_level','L5')}] {node.get('source','')}\n"
        f"视角: {'; '.join(node.get('views', []))}\n"
        f"要求: 只用用户已掌握的锚点「{p['a']}」作类比讲解, 不引入第二个新概念; 最后给出一个检验理解的变式问题。200字内。")
    text = llm(prompt)
    if text:
        print(text)
    else:
        print(f"  核心定义: {node['def']}")
        print(f"  连接: 把它看作「{p['a']}」的推广/类比（r={p['r']:.2f}, {p['type']}）")
        print(f"  来源: [{node.get('fact_level', 'L5')}] {node.get('source', '-')}")
        for v in node.get("views", [])[1:]:
            print(f"  多视角: {v}")
    quiz_flow(base, goal, p["b"])
    feel_flow(base, goal)


def quiz_flow(base, goal, node):
    gp = graph_path(base, goal)
    g = load_graph(gp)
    d = g["nodes"].get(node)
    if not d:
        return
    print(f"\n== 练习 · {node} ==")
    q = llm(f"出一个生成式回忆题: 让用户合上材料、用自己的话讲「{node}」（定义: {d['def']}）。只出题, 不要给答案。")
    print(q or f"合上材料, 用自己的话写出「{node}」的含义（不许抄）:")
    conf = input_("先自评信心(0-100): ")
    ans = input_("你的回答: ")
    print(f"参考答案: {d['def']}")
    print(f"来源: [{d.get('fact_level', 'L5')}] {d.get('source', '-')}")
    gr = input_("自评: 对(1)/犹豫(0.5)/错(0): ")
    if gr not in ("1", "0.5", "0"):
        gr = "0.5"
    if not conf.isdigit():
        conf = "50"
    print(run_ops("--graph", gp, "quiz", node, "--grade", gr, "--conf", conf))


def feel_flow(base, goal):
    gp = graph_path(base, goal)
    print("\n== 30 秒收口 ==")
    a = input_("今天哪里最卡? (回车跳过): ")
    b = input_("哪个类比/讲法没懂? (回车跳过): ")
    c = input_("负荷(轻/正好/重): ")
    parts = [x for x in (a, b, c) if x]
    if parts:
        print(run_ops("--graph", gp, "feel", "；".join(parts)))
    if b:
        print("(若某个类比没懂, 可稍后对 pi 说 'r(A,B) 调低' 换锚点)")


def commit_flow(base, goal):
    gp = graph_path(base, goal)
    msg = input_("一句话概述这节课学了什么(回车用自动摘要): ")
    if msg:
        print(run_ops("--graph", gp, "commit", "-m", msg))
    else:
        print(run_ops("--graph", gp, "commit"))


# ---------- 复习 ----------
def review_flow(base, goal, node):
    gp = graph_path(base, goal)
    print(run_ops("--graph", gp, "review-node", node))
    g = load_graph(gp)
    d = g["nodes"].get(node)
    if not d:
        return
    q = llm(f"设计三个复习提问(无提示回忆/变式反例/连接抽问), 针对「{node}」(定义: {d['def']}), 邻居: " +
            ", ".join(f"{e['b']}" for e in g["edges"] if e["a"] == node) + "; 只出题不给答案。")
    print("\n== 三轮复习 ==")
    print(q or "1) 不提示: 用自己的话讲一遍  2) 变式: 如果换个场景/反过来呢?  3) 连接: 它和邻居知识点什么关系?")
    quiz_flow(base, goal, node)
    print(run_ops("--graph", gp, "assess", node))
    print(run_ops("--graph", gp, "review-log", node))
    commit_flow(base, goal)


# ---------- 读书札记 ----------
def capture_flow(base, kind, content):
    title = input_("标题(几个字): ") or content[:12]
    print(run_ops("capture", "--type", kind, "--title", title, "-m", content, "--base", base))
    if kind == "疑问" and content:
        ans = llm(f"用户读书时遇到疑问: {content}。用通俗语言解答, 若有多个可能解释给出最主流的一种, 并说明依据(来源)。300字内。")
        if ans:
            print("\n[立即解答]\n" + ans)
            print("(若这个疑问涉及学习目标, 对 pi 说 '把这个疑问补进 <目标> 的学习路径' 即可)")
        else:
            print("(未配置 DEEPSEEK_API_KEY, 解答留给 pi/稍后处理)")
    if kind == "感悟" and content:
        ref = llm(f"用户读书感悟: {content}。提炼它像不像是两个已知概念之间的关系/类比? 用一句话概括, 并给出'建议建边: X-Y, 类型'。100字内。")
        if ref:
            print("\n[提炼]\n" + ref)
        print("  确认后建边入图: 对知径说  add-edge <A> <B> --r 0.9 --type 类比 --source 我的感悟")
        print("  （若涉及新概念, 先 add-node <名称> --def 一句话定义）")
    if kind == "疑问" and content:
        print("  若这个疑问揭示了知识缺口, 可用 add-node / add-edge 补进某个学习目标")


# ---------- 主流程 ----------
def cmd_new(base, topic):
    name = input_(f"目录名(回车用「{topic}」): ") or topic
    print(run_ops("init-goal", name, "--goal", topic, "--base", base))
    explore(base, name)
    return name


def auto_finalize(base, goal):
    """直接退出后：下次继续时检测上一课未收尾，自动补摘要 + 提交。"""
    gp = graph_path(base, goal)
    g = load_graph(gp)
    procs = g["meta"].get("process", [])
    if not procs or procs[-1]["evt"] != "teach":
        return
    taught = procs[-1]
    print("（检测到上次课未收尾即退出，自动补记）")
    append_file(os.path.join(base, "学习记录", "正在学习", goal, "会话记录.md"),
                [f"- [自动收尾] 上次课「{taught.get('b')}」未完成收口即退出（{taught.get('ts')}），"
                 f"本课状态已保存，缺 /feel 与课末提交。"])
    print(run_ops("--graph", gp, "commit", "-m", f"上次课「{taught.get('b')}」中断退出，自动收尾"))


def cmd_continue(base):
    goal = choose_goal(base)
    if not goal:
        return
    auto_finalize(base, goal)
    gp = graph_path(base, goal)
    print(run_ops("--graph", gp, "status"))
    lesson(base, goal)
    commit_flow(base, goal)


def cmd_review(base, rest):
    goal = choose_goal(base)
    if not goal:
        return
    gp = graph_path(base, goal)
    if rest:
        review_flow(base, goal, rest)
    else:
        print(run_ops("--graph", gp, "review"))
        x = input_("要复习哪个点? (留空=结束): ")
        if x:
            review_flow(base, goal, x)


def cmd_graduate(base):
    goal = choose_goal(base)
    if not goal:
        return
    gp = graph_path(base, goal)
    print(run_ops("--graph", gp, "graduate"))
    print(run_ops("finish", goal, "--base", base))
    print(f"已归档到 学习记录\\已经学完\\{goal}（完成档案已永久写进 背景知识.md）")


def dispatch(base, line):
    s = line.strip()
    if not s:
        return True
    if s in ("退出", "quit", "exit", "/quit", "q"):
        return False
    if s.startswith("我想学习") or s.startswith("我要学习"):
        topic = s.split("我想学习", 1)[-1].split("我要学习", 1)[-1].strip(" :：")
        if topic:
            cmd_new(base, topic)
        else:
            print("想学什么? 例如: 我想学习 Python 装饰器")
        return True
    if s.startswith("继续学习"):
        cmd_continue(base)
        return True
    if s.startswith("我要复习") or s.startswith("复习一下"):
        rest = s.replace("我要复习", "").replace("复习一下", "").strip()
        cmd_review(base, rest)
        return True
    if s.startswith("学到哪了") or s.startswith("学习进度"):
        print(run_ops("progress-all", "--base", base))
        return True
    if s.startswith("看计划") or s.startswith("看看计划") or s.startswith("规划"):
        goal = choose_goal(base)
        if goal:
            print(run_ops("--graph", graph_path(base, goal), "roadmap"))
        return True
    if s.startswith("找联系") or s.startswith("连接建议") or s.startswith("有什么联系"):
        goal = choose_goal(base)
        if goal:
            print(run_ops("--graph", graph_path(base, goal), "find-links"))
        return True
    if s.startswith("我学完了") or s.startswith("学完了"):
        cmd_graduate(base)
        return True
    if s.startswith("记录个疑问") or s.startswith("这看不懂") or s.startswith("有个疑问"):
        content = s.replace("记录个疑问", "").replace("这看不懂", "").replace("有个疑问", "").strip(" :：")
        capture_flow(base, "疑问", content)
        return True
    if s.startswith("有个感悟") or s.startswith("我有感悟") or s.startswith("感悟"):
        content = s.replace("有个感悟", "").replace("我有感悟", "").replace("感悟", "").strip(" :：")
        capture_flow(base, "感悟", content)
        return True
    if s.startswith("看看我的札记") or s.startswith("我的札记"):
        print(run_ops("captures", "--base", base))
        return True
    # 裸工具名直通（脚本化用）
    bare = s.split()[0]
    if bare in ("progress-all", "captures"):
        print(run_ops(bare, "--base", base))
        return True
    if bare in ("status", "plan", "roadmap", "find-links", "teach-next", "quiz", "review", "feel", "calibrate",
                "graph", "graduate", "source", "import-headings", "undo", "progress",
                "assess", "assess-all", "commit", "log", "timeline",
                "review-node", "review-log", "add-node", "add-edge"):
        goal = choose_goal(base)
        if not goal:
            return True
        gp = graph_path(base, goal)
        print(run_ops("--graph", gp, bare, *s.split()[1:]))
        return True
    if s.startswith("/"):
        goal = None
        parts = s.split()
        cmd = parts[0]
        # 需要图谱的命令
        graph_cmds = ("/status", "/plan", "/teach", "/quiz", "/review", "/feel", "/graph",
                      "/calibrate", "/graduate", "/source", "/import", "/undo", "/progress",
                      "/assess", "/commit", "/log", "/timeline")
        if cmd in graph_cmds:
            goal = choose_goal(base)
            if not goal:
                return True
            gp = graph_path(base, goal)
            args = ["--graph", gp]
            if cmd == "/quiz" and len(parts) >= 2:
                node = parts[1]
                g = load_graph(gp)
                if node in g["nodes"]:
                    quiz_flow(base, goal, node)
                    return True
            if cmd == "/assess" and len(parts) >= 2:
                args += ["assess", parts[1]]
            else:
                args += [cmd[1:].replace("/", "")]
                args += parts[1:]
            print(run_ops(*args))
            return True
        if cmd == "/help" or s == "help":
            print(HELP)
            return True
        print(f"未知命令: {cmd}（/help 看全部）")
        return True
    print("没听懂。试试: 我想学习 X / 继续学习 / 我要复习 X / 学到哪了 / 我学完了 / 记录个疑问 / 有个感悟 / /help")
    return True


HELP = """
== 知径 · 终端教学 Agent ==
自然语言:  我想学习 X   继续学习   我要复习 X   学到哪了   我学完了
           记录个疑问…  有个感悟…  看看我的札记
斜杠命令:  /status /plan /teach /quiz <点> /review /feel /graph /calibrate
           /graduate /source <点> /import <路径> /undo /progress /assess <点>
           /commit /log /timeline /help /quit
说明:      说「继续学习」= 下一课(讲解+练习+收口+提交);
           说「我要复习 X」= 三轮复习(回忆/变式/连接)+成绩单;
           未配置 DEEPSEEK_API_KEY 时讲解用图谱内置内容(同样可用)。
"""


def main():
    base = None
    for a in sys.argv[1:]:
        if a.startswith("--base="):
            base = a.split("=", 1)[1]
    base = base or workspace()
    if "--check" in sys.argv:
        print("知径自检:")
        print(f"  Python: {sys.version.split()[0]}")
        print(f"  工作区: {base}")
        print(f"  图谱工具: {'OK' if GO else 'FAIL'}")
        print(f"  DeepSeek: {'已配置' if os.environ.get('DEEPSEEK_API_KEY') else '未配置(用内置内容讲解)'}")
        print(f"  进行中目标: {find_goals(base) or '无'}")
        return
    if len(sys.argv) > 1:
        dispatch(base, " ".join(sys.argv[1:]))
        return
    print("知径 · 以知为径，与 AI 同行。")
    print("说「我想学习 X」开始 / 「/help」看命令 / 「退出」结束")
    run_ops("sync-background", "--base", base)  # 启动时同步背景知识
    while True:
        try:
            line = input_("知径> ")
        except KeyboardInterrupt:
            print()
            continue
        if not line:
            if _EOF[0]:
                print("(输入结束) 再见。你的进度都保存在文件里。")
                break
            continue
        if not dispatch(base, line):
            print("再见。你的进度都保存在文件里, 下次说「继续学习」。")
            break
    run_ops("sync-background", "--base", base)  # 退出时同步背景知识


if __name__ == "__main__":
    main()
