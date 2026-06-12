"""Run NL regression questions through the OAG endpoint and record results."""
import requests
import json
import subprocess
import time
import sys
import os

BASE_URL = "http://localhost:8000"
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

QUESTIONS = [
    # Low difficulty
    ("L1", "现在系统里有多少名学生？他们分别是谁？"),
    ("L2", "张三今年多大，在哪个班？"),
    ("L3", "计算机2201班有哪些学生？"),
    ("L4", "2024-春学期有哪些课程被开设？分别是谁教的？"),
    ("L5", "Python编程是多少学分？"),
    ("L6", "Python编程有哪些授课老师？属于哪个学期？"),
    ("L7", "信息学院有哪些老师？"),
    ("L8", "王五修了哪些课程，成绩分别是多少？"),
    ("L9", "张三的平均分是多少？"),
    ("L10", "数据库系统这门课的通过率是多少？"),
    # Medium difficulty
    ("M1", "名字里带'王'的对象有哪些？请按学生、老师、课程分组展示。"),
    ("M2", "王教授教授哪些课程？这些课程总学分是多少？"),
    ("M3", "2025-春学期有哪些课程是由多位老师共同授课的？教师分别是谁？"),
    ("M4", "当前有哪些优秀学生？请按平均分从高到低列出来。"),
    ("M5", "当前有哪些老员工教师？"),
    ("M6", "2024-春学期里，张教授教授了哪些课程？"),
    ("M7", "哪门课平均分最高？哪门课通过率最低？"),
    ("M8", "孙七有哪些课程没及格？"),
    ("M9", "王五修过机器学习导论吗？如果修过，成绩是多少？"),
    ("M10", "吴老师和王教授共同教授了哪些课程？这些课程是哪学期开设的？"),
    ("M11", "哪些学生没有修过大学英语？"),
    ("M12", "英语2201班还没有修过哪些课程？"),
    # High difficulty
    ("H1", "哪些学生的平均分高于自己所在班级的平均水平？"),
    ("H2", "有没有学生在自己所有已修课程里都及格？把他们按平均分从高到低列出来。"),
    ("H3", "2025-春学期里，由信息学院老师授课且通过率是 100% 的课程有哪些？"),
    ("H4", "同时上了高等数学和数据结构，而且这两门都超过 80 分的学生有哪些？"),
    ("H5", "找出至少修了 3 门课且平均分超过 85 分的学生。"),
    ("H6", "先给李四补录一条 Python编程 78 分、考试日期为 2024-12-20 的成绩，再告诉我他新的平均分是多少。"),
    ("H7", "把赵六的高等数学成绩改成 90 分后，他会不会进入优秀学生集合？"),
    ("H8", "删除李四的数据结构成绩后，他还剩下几门不及格课程？分别是什么？"),
    ("H9", "把 Python编程 也分配给张教授后，张教授名下共有几门不同课程？总学分是多少？"),
    ("H10", "哪位老师教授的不同课程数量最多？分别是哪些课程？"),
    ("H11", "哪位学生修课最多？一共修了多少门？"),
    ("H12", "哪些课程当前有两位授课老师？请同时给出课程名、老师名和学期。"),
    # Extra
    ("X1", "帮我比较张三和王五的成绩结构，谁更偏科？请给出依据。"),
    ("X2", "如果把所有低于 60 分的成绩都视为待补考，当前最需要重点关注的学生是谁？为什么？"),
    ("X3", "哪位老师的课程覆盖学生最广？请同时列出涉及的学生班级。"),
    ("X4", "现在有哪些课程还没有被任何英语2201班学生修读？"),
    ("X5", "哪些学生同时修过机器学习导论和数据库系统？"),
]

def reset_db():
    result = subprocess.run(
        ["python", "seed_data.py"],
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "seed_data.py failed")
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

        print("  [resetting database to seed state...]")
        try:
            reset_db()
            answer = ask_question(question)
            print(f"\n  答案: {answer[:500]}")
            results.append({"id": qid, "question": question, "answer": answer})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"id": qid, "question": question, "answer": f"ERROR: {e}"})
    
    # Save results
    with open(os.path.join(ROOT_DIR, "test_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n\n{'='*60}")
    print(f"Done! {len(results)} questions tested. Results saved to test_results.json")

if __name__ == "__main__":
    main()
