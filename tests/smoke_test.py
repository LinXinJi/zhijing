# -*- coding: utf-8 -*-
"""
graph_ops 冒烟测试
==================
在临时目录用种子图谱跑关键路径，断言行为与设计一致：
  最优路径、教学顺序、门禁、m 更新、r 修正、换锚点、材料导入去重、终局导出。
用法:  python tests/smoke_test.py   (退出码 0 = 全部通过)
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

spec = importlib.util.spec_from_file_location(
    "graph_ops", os.path.join(REPO, "tools", "graph_ops.py"))
gops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gops)

passed = []


def check(name, cond):
    passed.append((name, bool(cond)))
    print(("PASS  " if cond else "FAIL  ") + name)


def run(tmp, *args):
    buf = io.StringIO()
    old = sys.argv
    sys.argv = ["graph_ops", "--graph", os.path.join(tmp, "graph.json")] + list(args)
    try:
        with contextlib.redirect_stdout(buf):
            gops.main()
    finally:
        sys.argv = old
    return buf.getvalue()


def load(tmp):
    with open(os.path.join(tmp, "graph.json"), encoding="utf-8") as f:
        return json.load(f)


tmp = os.path.join(REPO, "tests", ".smoke_tmp")
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp, exist_ok=True)
try:
    # 用独立夹具（不影响用户正在使用的真实 graph.json）
    shutil.copy(os.path.join(REPO, "tests", "fixtures", "seed_导数.json"),
                os.path.join(tmp, "graph.json"))

    out = run(tmp, "plan")
    check("plan 输出最优路径 斜率→切线→导数 (7.56)", "斜率 → 切线" in out and "7.56" in out)

    out = run(tmp, "roadmap")
    check("roadmap 分阶段网状规划",
          "阶段" in out and "主线" in out and "切线" in out and "支线" in out)

    out = run(tmp, "find-links")
    check("find-links 连接建议", "连接建议" in out and "切线" in out)

    run(tmp, "teach-next")
    g = load(tmp)
    check("teach 事件写入 meta.process",
          any(p.get("evt") == "teach" and p["b"] == "切线" for p in g["meta"]["process"]))

    run(tmp, "quiz", "切线", "--grade", "1", "--conf", "80")
    g = load(tmp)
    check("测验后 m=0.475 (0.30+0.25×0.70)", abs(g["nodes"]["切线"]["m"] - 0.475) < 1e-9)

    run(tmp, "undo")
    g = load(tmp)
    check("undo 恢复 m=0.30 且移除 quiz 事件",
          abs(g["nodes"]["切线"]["m"] - 0.30) < 1e-9 and
          not any(p.get("evt") == "quiz" for p in g["meta"]["process"]))
    run(tmp, "quiz", "切线", "--grade", "1", "--conf", "80")
    g = load(tmp)
    check("undo 后重打分 m=0.475", abs(g["nodes"]["切线"]["m"] - 0.475) < 1e-9)

    out = run(tmp, "teach-next")
    check("门禁拦住未掌握点 (回炉提示)", "回炉" in out)

    run(tmp, "feel", "斜率类比没听懂", "--r", "斜率", "切线", "0.70")
    g = load(tmp)
    r = next(e for e in g["edges"] if {e["a"], e["b"]} == {"斜率", "切线"})["r"]
    check("r 修正为 0.70", abs(r - 0.70) < 1e-9)

    out = run(tmp, "plan")
    check("感受反馈后换锚点 (函数图像→切线)", "函数图像 → 切线" in out)

    run(tmp, "undo")
    g = load(tmp)
    r2 = next(e for e in g["edges"] if {e["a"], e["b"]} == {"斜率", "切线"})["r"]
    check("undo 恢复 r=0.90", abs(r2 - 0.90) < 1e-9)
    out = run(tmp, "plan")
    check("undo 后路径回到 斜率→切线", "斜率 → 切线" in out)
    run(tmp, "feel", "斜率类比没听懂", "--r", "斜率", "切线", "0.70")

    for _ in range(4):
        run(tmp, "quiz", "切线", "--grade", "1", "--conf", "85")
    g = load(tmp)
    check("4 次练习后过门禁 m≥0.8", g["nodes"]["切线"]["m"] >= 0.8)

    out = run(tmp, "teach-next")
    check("下一课为导数", "导数" in out)

    out = run(tmp, "assess", "切线")
    check("assess 输出分数/标签/权值系数",
          "分数" in out and "已掌握" in out and "权值系数" in out)
    g = load(tmp)
    check("assess 写回节点 score/tags",
          "score" in g["nodes"]["切线"] and g["nodes"]["切线"]["tags"])
    out = run(tmp, "assess-all")
    check("assess-all 总览含导数", "导数" in out)

    run(tmp, "review-log", "切线")
    rlog = os.path.join(tmp, "复习", "切线")
    rfiles = [f for f in os.listdir(rlog) if f.endswith(".md")]
    check("review-log 生成复习成绩单记录",
          len(rfiles) == 1 and
          "成绩单" in open(os.path.join(rlog, rfiles[0]), encoding="utf-8").read())

    run(tmp, "commit", "-m", "切线复习+练习过关")
    g = load(tmp)
    check("commit 记录到 meta.commits",
          len(g["meta"].get("commits", [])) == 1 and
          g["meta"]["commits"][0]["msg"] == "切线复习+练习过关")
    out = run(tmp, "log")
    check("log 输出提交历史", "c1" in out and "切线复习" in out)
    out = run(tmp, "timeline")
    check("timeline 含提交标记", "提交" in out and "切线" in out)

    run(tmp, "capture", "--type", "疑问", "--title", "测试疑问", "--base", tmp)
    run(tmp, "capture", "--type", "感悟", "--title", "测试感悟", "--base", tmp)
    out = run(tmp, "captures", "--base", tmp)
    check("读书札记捕获与列表",
          "测试疑问" in out and "测试感悟" in out and "待处理" in out)
    check("札记落入 读书札记 子目录",
          os.path.isdir(os.path.join(tmp, "读书札记")) and
          len([f for f in os.listdir(os.path.join(tmp, "读书札记")) if f.endswith(".md")]) == 2)

    run(tmp, "add-edge", "方程", "导数", "--r", "0.9", "--type", "类比", "--source", "我的感悟")
    g = load(tmp)
    check("add-edge 感悟建边入图",
          any(e["a"] == "方程" and e["b"] == "导数" and e.get("source") == "我的感悟"
              for e in g["edges"]))
    run(tmp, "add-node", "新感悟点", "--def", "测试点", "--source", "读书札记")
    g = load(tmp)
    check("add-node 加点", "新感悟点" in g["nodes"])

    out = run(tmp, "progress")
    check("progress 面板含综合进度与导数", "综合进度" in out and "导数" in out)

    mat = os.path.join(REPO, "tests", "素材")
    run(tmp, "import-headings", mat, "--commit")
    g = load(tmp)
    check("导入新增 测试点A/测试点B", "测试点A" in g["nodes"] and "测试点B" in g["nodes"])
    check("导入去重 (斜率未重复)", list(g["nodes"].keys()).count("斜率") == 1)

    run(tmp, "undo")
    g = load(tmp)
    check("undo 移除最后导入节点 (测试点B)",
          "测试点A" in g["nodes"] and "测试点B" not in g["nodes"])
    run(tmp, "undo")
    g = load(tmp)
    check("undo 再移除 (测试点A)",
          "测试点A" not in g["nodes"] and "测试点B" not in g["nodes"])

    run(tmp, "init-goal", "测试目标", "--goal", "测试", "--base", tmp)
    g2path = os.path.join(tmp, "学习记录", "正在学习", "测试目标", "graph.json")
    check("init-goal 建到 学习记录/正在学习 且含模板图谱",
          os.path.exists(g2path) and
          json.load(open(g2path, encoding="utf-8"))["goal"] == "测试" and
          os.path.exists(os.path.join(tmp, "学习记录", "正在学习", "测试目标", "会话记录.md")) and
          os.path.isdir(os.path.join(tmp, "学习记录", "正在学习", "测试目标", "复习")))

    out = run(tmp, "progress-all", "--base", tmp)
    check("progress-all 总览含测试目标", "测试目标" in out)

    run(tmp, "sync-background", "--base", tmp)
    bg = os.path.join(tmp, "背景知识.md")
    check("sync-background 自动同步背景知识",
          os.path.exists(bg) and "测试" in io.open(bg, encoding="utf-8").read())

    run(tmp, "finish", "测试目标", "--base", tmp)
    check("finish 归档到 学习记录/已经学完",
          not os.path.exists(os.path.join(tmp, "学习记录", "正在学习", "测试目标")) and
          os.path.exists(os.path.join(tmp, "学习记录", "已经学完", "测试目标", "graph.json")))
    check("finish 写死完成档案到背景知识",
          "已完成档案" in io.open(os.path.join(tmp, "背景知识.md"), encoding="utf-8").read()
          and "测试" in io.open(os.path.join(tmp, "背景知识.md"), encoding="utf-8").read())

    out = run(tmp, "progress-all", "--base", tmp)
    check("finish 后总览列出已经学完", "已经学完" in out and "测试目标" in out)

    out = run(tmp, "review-node", "切线")
    check("review-node 输出复习卡与邻居", "复习卡" in out and "导数" in out)

    run(tmp, "graduate")
    ex = os.path.join(tmp, "图谱导出")
    check("graduate 三件套导出",
          all(os.path.exists(os.path.join(ex, f))
              for f in ["graduate.mmd", "graduate.json", "学习报告.md"]))
    with open(os.path.join(ex, "学习报告.md"), encoding="utf-8") as f:
        rep_text = f.read()
    check("学习报告含成绩单表格", "## 成绩单" in rep_text and "切线" in rep_text)
    check("学习报告含时间线与提交历史", "## 学习时间线" in rep_text and "## 提交历史" in rep_text)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

fails = [n for n, c in passed if not c]
print(f"\n{len(passed) - len(fails)}/{len(passed)} 通过")
sys.exit(1 if fails else 0)
