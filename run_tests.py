"""Run all 39 NL test questions through the OAG endpoint and record results."""
import requests
import json
import subprocess
import time
import sys

BASE_URL = "http://localhost:8000"

QUESTIONS = [
    # Low difficulty
    ("L1", "现在系统里有哪些学生？"),
    ("L2", "张三今年多大，在哪个班？"),
    ("L3", "有哪些女学生？"),
    ("L4", "2024-春学期开了哪些课程？"),
    ("L5", "高等数学是多少学分？是哪学期开的？"),
    ("L6", "大学英语是谁教的？"),
    ("L7", "信息学院有哪些老师？"),
    ("L8", "王五的所有成绩分别是多少？"),
    ("L9", "张三的平均分是多少？"),
    ("L10", "Python编程这门课的通过率是多少？"),
    # Medium difficulty
    ("M1", "名字里带'张'的对象有哪些？包括学生、老师和课程。"),
    ("M2", "张教授现在教哪些课？这些课总共有多少学分？"),
    ("M3", "高等数学成绩最高的学生是谁，分数是多少？"),
    ("M4", "数据结构这门课前 3 名是谁？"),
    ("M5", "当前有哪些优秀学生？"),
    ("M6", "当前有哪些及格课程？"),
    ("M7", "计算机2201班的学生按平均分从高到低怎么排？"),
    ("M8", "孙七有哪些课程没及格？"),
    ("M9", "王五修过 Python编程 吗？如果修过，成绩是多少？"),
    ("M10", "2024-春学期里，张教授教授了哪些课程？"),
    ("M11", "哪门课平均分最高？哪门课通过率最低？"),
    ("M12", "把张三的成绩单列出来，并显示每门课对应的授课老师。"),
    # High difficulty
    ("H1", "哪些学生的平均分高于自己所在班级的平均水平？"),
    ("H2", "有没有学生在自己所有已修课程里都及格？把他们按平均分从高到低列出来。"),
    ("H3", "2024-春学期里，由数学学科老师授课且通过率超过 80% 的课程有哪些？"),
    ("H4", "同时上了高等数学和数据结构，而且这两门都超过 80 分的学生有哪些？"),
    ("H5", "找出至少修了 3 门课且平均分超过 85 分的学生。"),
    ("H6", "先给李四补录一条 Python编程 78 分、考试日期为 2024-12-20 的成绩，再告诉我他新的平均分是多少。"),
    ("H7", "把赵六的高等数学成绩改成 90 分后，他会不会进入优秀学生集合？"),
    ("H8", "删除李四的数据结构成绩后，他还剩下几门不及格课程？分别是什么？"),
    ("H9", "把 Python编程 改为由张教授授课后，张教授名下共有几门课，总学分是多少？"),
    ("H10", "哪位老师名下课程的平均分最高？同时列出这位老师所教每门课的平均分。"),
    ("H11", "对每个班级，找出平均分最高的学生，并说明他成绩最高的一门课是什么。"),
    ("H12", "如果搜索关键词\u201c王\u201d，结果里会出现哪些学生、老师和课程？请按对象类型分组展示。"),
    # Extra
    ("X1", "帮我比较张三和王五的成绩结构，谁更偏科？请给出依据。"),
    ("X2", "哪些课程是计算机2201班学生整体表现更好、但其他班表现一般的？"),
    ("X3", "如果把所有低于 60 分的成绩都视为待补考，当前最需要重点关注的学生是谁？为什么？"),
    ("X4", "哪位老师的课程覆盖学生最广？请同时列出涉及的学生班级。"),
    ("X5", "现在有哪些课程还没有被任何英语2201班学生修读？"),
    # Super Hard - subquery / set operations / cross-aggregation
    ("S1", "哪些学生的平均分高于所有成绩的全局平均分？全局平均分是多少？"),
    ("S2", "找出在自己所修的每门课中，成绩都高于该课程平均分的学生。"),
    ("S3", "哪些学生没有选修过李教授的任何课程？"),
    ("S4", "张三和王五有哪些共同的授课老师？在每位共同老师的课上，谁的表现更好？"),
    ("S5", "哪个班级的加权平均分（按学分加权）最高？分别是多少？"),
    ("S6", "哪些学生在王教授的课上比在张教授的课上表现更好？"),
    ("S7", "每门课中排名第一的学生分别是谁？有没有某个学生在多门课中都排第一？"),
    ("S8", "如果只看4学分的课程（高等数学和数据结构），哪个学生的两门课分差最小（最稳定）？"),
]

# Questions that modify data - need seed_data reset before each
WRITE_QUESTIONS = {"H6", "H7", "H8", "H9"}

def reset_db():
    subprocess.run(["python", "seed_data.py"], capture_output=True, cwd="/Users/haoyuzhang/Documents/杂乱代码/tiny-ontology")
    time.sleep(0.5)

def ask_question(question: str) -> str:
    resp = requests.post(f"{BASE_URL}/ontology/nl-query-oag", json={"query": question}, timeout=120)
    if resp.status_code == 200:
        data = resp.json()
        return data.get("answer", str(data))
    else:
        return f"ERROR {resp.status_code}: {resp.text}"

def main():
    results = []
    
    # Determine which questions to run
    if len(sys.argv) > 1:
        ids_to_run = set(sys.argv[1:])
        questions = [(qid, q) for qid, q in QUESTIONS if qid in ids_to_run]
    else:
        questions = QUESTIONS
    
    for i, (qid, question) in enumerate(questions):
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(questions)}] {qid}: {question}")
        print(f"{'='*60}")
        
        # Reset DB before write operations
        if qid in WRITE_QUESTIONS:
            print("  [resetting database...]")
            reset_db()
        
        try:
            answer = ask_question(question)
            print(f"\n  答案: {answer[:500]}")
            results.append({"id": qid, "question": question, "answer": answer})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"id": qid, "question": question, "answer": f"ERROR: {e}"})
    
    # Save results
    with open("/Users/haoyuzhang/Documents/杂乱代码/tiny-ontology/test_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n{'='*60}")
    print(f"Done! {len(results)} questions tested. Results saved to test_results.json")

if __name__ == "__main__":
    main()
