# Ontology Demo 需求文档

## 1. 项目目标

基于 student、teacher、course、score 四张原始数据表，构建一个符合 Ontology 定义的语义层 demo。核心演示：

- 如何把关系型数据库的 **表/列/外键** 封装为 Ontology 的 **Object/Link/Action/Function**
- 语义表示层用 Ontology，计算层用 SQL 的混合架构可行性
- 上层应用（REST API、Python SDK、AI Agent）通过业务语义访问数据，而非直接写 SQL
- **知识图谱可视化**：将 Object 和 Link 渲染为交互式节点-边图
- **自然语言查询**：用户输入自然语言，系统自动翻译为 Ontology 操作

## 2. 原始数据表

### 2.1 student（学生表）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 学生唯一标识 |
| name | TEXT | 姓名 |
| age | INTEGER | 年龄 |
| gender | TEXT | 性别（M/F） |
| class_name | TEXT | 班级名称 |

### 2.2 teacher（教师表）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 教师唯一标识 |
| name | TEXT | 姓名 |
| subject | TEXT | 所教科目 |
| department | TEXT | 所属院系 |

### 2.3 course（课程表）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 课程唯一标识 |
| name | TEXT | 课程名称 |
| teacher_id | INTEGER FK→teacher.id | 授课教师 |
| credit | INTEGER | 学分 |
| semester | TEXT | 开课学期（如 2024-春） |

### 2.4 score（成绩表）

| 列名 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 成绩记录唯一标识 |
| student_id | INTEGER FK→student.id | 学生 |
| course_id | INTEGER FK→course.id | 课程 |
| score_value | REAL | 成绩分值（0-100） |
| exam_date | TEXT | 考试日期 |

### 2.5 ER 关系

```
student ──(score)── course ──(teacher_id)── teacher
  │         │            │                        │
  │    student_id    course_id              taught_by
  │    score_value    name                  name
  │    exam_date      credit                subject
  name                semester              department
  age
  gender
  class_name
```

## 3. Ontology 语义层映射

### 3.1 Object Type

共 4 个 Object Type，每个原始表映射为一个 Object：

#### Student

| 属性 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| id | Primary Key | student.id | 唯一标识 |
| name | Regular | student.name | 姓名 |
| age | Regular | student.age | 年龄 |
| gender | Regular | student.gender | 性别 |
| className | Regular | student.class_name | 班级 |
| avgScore | Derived（由 Function 计算） | — | 平均成绩 |

#### Teacher

| 属性 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| id | Primary Key | teacher.id | 唯一标识 |
| name | Regular | teacher.name | 姓名 |
| subject | Regular | teacher.subject | 所教科目 |
| department | Regular | teacher.department | 所属院系 |

#### Course

| 属性 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| id | Primary Key | course.id | 唯一标识 |
| name | Regular | course.name | 课程名称 |
| credit | Regular | course.credit | 学分 |
| semester | Regular | course.semester | 开课学期 |
| passRate | Derived（由 Function 计算） | — | 课程通过率 |

#### Score

| 属性 | 类型 | 来源列 | 说明 |
|------|------|--------|------|
| id | Primary Key | score.id | 唯一标识 |
| scoreValue | Regular | score.score_value | 成绩分值（0-100） |
| examDate | Regular | score.exam_date | 考试日期 |

### 3.2 Link Type

共 3 个 Link Type：

| API Name | 源 Object | 目标 Object | 基数 | 说明 |
|----------|-----------|-------------|------|------|
| earnedBy | Score | Student | 多对一 | 成绩属于哪个学生 |
| forCourse | Score | Course | 多对一 | 成绩对应哪门课程 |
| taughtBy | Course | Teacher | 多对一 | 课程由哪位教师讲授 |

Link 的图遍历方向：
```
Score ──[earnedBy]──▶ Student
Score ──[forCourse]──▶ Course
Course ──[taughtBy]──▶ Teacher
```

反向遍历（隐式）：
```
Student ◀── scores（Score.earnedBy 的反向）
Course  ◀── scores（Score.forCourse 的反向）
Teacher ◀── courses（Course.taughtBy 的反向）
```

### 3.3 Action Type

共 4 个 Action：

#### createScore — 录入成绩

| 维度 | 说明 |
|------|------|
| 类型 | Object Action（绑定 Score） |
| 输入 | studentId, courseId, scoreValue, examDate |
| 校验 | validateScore：成绩 0-100、同学生同课程不重复录入 |
| 执行 | 创建 Score 对象 + 建立 earnedBy Link + 建立 forCourse Link（事务性） |
| 审计 | 记录操作人、时间、参数、结果 |

#### updateScore — 修改成绩

| 维度 | 说明 |
|------|------|
| 类型 | Object Action（绑定 Score） |
| 输入 | scoreId, newScoreValue, newExamDate（可选） |
| 校验 | 成绩 0-100 |
| 执行 | 更新 Score 对象的 scoreValue / examDate |

#### deleteScore — 删除成绩

| 维度 | 说明 |
|------|------|
| 类型 | Object Action（绑定 Score） |
| 输入 | scoreId |
| 执行 | 删除 Score 对象，自动断开 earnedBy 和 forCourse 两条 Link |

#### assignTeacher — 分配教师

| 维度 | 说明 |
|------|------|
| 类型 | Link Action（绑定 Course→Teacher 的 taughtBy） |
| 输入 | courseId, teacherId |
| 执行 | 修改 Course 的 taughtBy Link 指向新的 Teacher |

### 3.4 Function

共 4 个 Function：

#### getAvgScore — 学生平均成绩

| 维度 | 说明 |
|------|------|
| 类型 | Object Function（Student 的派生属性 avgScore） |
| 输入 | studentId |
| 实现 | `SELECT AVG(score_value) FROM score WHERE student_id = ?` |
| 输出 | 数值（保留一位小数） |

#### getPassRate — 课程通过率

| 维度 | 说明 |
|------|------|
| 类型 | Object Function（Course 的派生属性 passRate） |
| 输入 | courseId |
| 实现 | `SELECT COUNT(CASE WHEN score_value >= 60 THEN 1 END) * 100.0 / COUNT(*) FROM score WHERE course_id = ?` |
| 输出 | 百分比字符串（如 "85.0%"） |

#### getTopStudents — 课程排名

| 维度 | 说明 |
|------|------|
| 类型 | Object Set Function |
| 输入 | courseId, limit（默认 10） |
| 实现 | `SELECT s.id, s.name, sc.score_value FROM score sc JOIN student s ON sc.student_id = s.id WHERE sc.course_id = ? ORDER BY sc.score_value DESC LIMIT ?` |
| 输出 | Student 对象列表（按成绩降序） |

#### validateScore — 录入校验

| 维度 | 说明 |
|------|------|
| 类型 | Action Validation Function（createScore 提交前触发） |
| 输入 | studentId, courseId, scoreValue |
| 实现 | 检查成绩范围 0-100、同学生同课程是否已存在成绩 |
| 输出 | `{ valid: boolean, message: string }` |

## 4. 对外接口

### 4.1 层级结构

```
AI Agent / LLM
      │
      ▼
Python SDK（链式调用）
      │
      ▼
REST API（FastAPI）
      │
      ▼
Ontology 引擎
  ├── Schema 注册表（Object/Link/Action/Function 元数据）
  ├── 查询引擎（Object/Link 遍历 → SQL 翻译）
  ├── Action 引擎（校验 → 事务 → 审计）
  └── Function 引擎（SQL 计算 → 派生属性）
      │
      ▼
SQLite 数据库
```

### 4.2 REST API 端点

#### 查询类

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/ontology/objects/{objectType}/{id}` | 获取单个对象 |
| GET | `/ontology/objects/{objectType}` | 查询对象列表（支持 where/orderBy/limit） |
| GET | `/ontology/objects/{objectType}/{id}/links/{linkName}` | 遍历 Link 获取关联对象 |
| GET | `/ontology/objects/{objectType}/{id}/functions/{funcName}` | 调用 Object Function |
| GET | `/ontology/functions/{funcName}` | 调用 Object Set Function |

#### 操作类

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/ontology/actions/createScore` | 录入成绩 |
| PUT | `/ontology/actions/updateScore` | 修改成绩 |
| DELETE | `/ontology/actions/deleteScore` | 删除成绩 |
| PUT | `/ontology/actions/assignTeacher` | 分配教师 |

### 4.3 Python SDK 示例（目标体验）

```python
from ontology import OntologyClient

client = OntologyClient("sqlite:///demo.db")

# 查询学生
student = client.objects("Student").get(1)
print(student.name, student.avgScore)  # avgScore 是派生属性

# 遍历 Link
for score in student.scores():  # 隐式反向 Link
    course = score.forCourse.get()
    print(f"{course.name}: {score.scoreValue}")

# 查询课程排名
top = client.functions("getTopStudents")(courseId=1, limit=5)

# 执行 Action
client.actions("createScore").execute(
    studentId=1, courseId=1, scoreValue=95, examDate="2024-06-15"
)
```

### 4.4 AI Agent 入口

将 Ontology Schema 导出为 LLM Function Definitions（OpenAI 格式）：

```json
{
  "name": "ontology_query_student",
  "description": "查询学生对象。Student 有 id, name, age, gender, className 属性，avgScore 为派生属性（平均成绩）。可通过 earnedBy Link 反向遍历获取该学生的所有 Score 记录。",
  "parameters": {
    "type": "object",
    "properties": {
      "studentId": {"type": "integer", "description": "学生ID"}
    }
  }
}
```

Agent 感知的是 `Student`、`Course`、`Score` 等业务对象，不需要理解底层 SQL 表结构。

## 5. 知识图谱可视化

### 5.1 图谱结构

将 Ontology 中的 Object（节点）和 Link（边）渲染为交互式力导向图：

```
      ┌──────────┐         ┌──────────┐
      │ Teacher  │         │ Teacher  │
      │  张老师   │         │  李老师   │
      └────┬─────┘         └────┬─────┘
           │ taughtBy           │ taughtBy
           ▼                    ▼
      ┌──────────┐         ┌──────────┐
      │  Course   │         │  Course   │
      │  数学     │         │  英语     │
      └────┬─────┘         └────┬─────┘
           │ forCourse          │ forCourse
           ▼                    ▼
      ┌──────────┐         ┌──────────┐
      │  Score    │         │  Score    │
      │  95分     │         │  82分     │
      └────┬─────┘         └────┬─────┘
           │ earnedBy           │ earnedBy
           ▼                    ▼
      ┌──────────────────────────────┐
      │         Student 张三          │
      └──────────────────────────────┘
```

### 5.2 交互功能

| 功能 | 说明 |
|------|------|
| **全景图** | 默认展示所有 Object 节点，按 Object Type 着色分类 |
| **节点悬停** | 显示对象关键属性（如 Student 显示 name、avgScore） |
| **Link 展示** | 节点间连线标注 Link 名称和方向 |
| **聚焦展开** | 点击节点，展开/收起相邻的一跳（1-hop）关联对象 |
| **按类型筛选** | 侧边栏切换显示 Student / Teacher / Course / Score |
| **搜索定位** | 输入名称搜索，高亮对应节点 |

## 6. 前端页面

### 6.1 页面布局

```
┌─────────────────────────────────────────────────────┐
│  Ontology Demo — 学生成绩管理系统                      │
├──────────────────┬──────────────────────────────────┤
│                  │                                  │
│   知识图谱面板     │      自然语言查询面板               │
│   (力导向图)      │                                  │
│                  │   ┌──────────────────────────┐   │
│   ● Student      │   │ 🔍 输入自然语言查询...     │   │
│   ● Teacher      │   │                          │   │
│   ● Course       │   │ 例：查张三所有课程的平均分  │   │
│   ● Score        │   └──────────────────────────┘   │
│                  │                                  │
│   节点可拖拽      │   ┌─ 查询结果 ─────────────────┐  │
│   滚轮缩放        │   │ 张三 平均分: 88.5          │  │
│   点击展开关系    │   │ 数学: 95  英语: 82         │  │
│                  │   └────────────────────────────┘  │
│                  │                                  │
├──────────────────┴──────────────────────────────────┤
│  操作面板: [录入成绩] [修改成绩] [分配教师]             │
└─────────────────────────────────────────────────────┘
```

### 6.2 页面清单

| 页面 | 路由 | 说明 |
|------|------|------|
| 主页（图谱+NL查询） | `/` | 左侧知识图谱，右侧自然语言查询 + 结果展示 |
| Object 详情页 | `/objects/{type}/{id}` | 单个对象的所有属性、关联对象、可执行 Action |

## 7. 自然语言查询

### 7.1 工作流程

```
用户输入自然语言
      │
      ▼
LLM 理解意图 + Ontology Schema 作为 context
      │
      ▼
生成 Ontology 操作序列（query Object → traverse Link → call Function）
      │
      ▼
Ontology 引擎执行（翻译为 SQL → 查询 SQLite）
      │
      ▼
结果返回 + 前端渲染
```

### 7.2 示例查询

| 自然语言 | 对应 Ontology 操作 |
|----------|-------------------|
| 「查张三的所有成绩」 | `Student.where(name="张三").get()` → `scores` Link 遍历 |
| 「数学课谁考了最高分」 | `Course.where(name="数学").get()` → `getTopStudents(limit=1)` |
| 「张三的平均分是多少」 | `Student.where(name="张三").get().avgScore`（派生属性） |
| 「哪些学生数学不及格」 | `Course.where(name="数学").get()` → `scores` Link → `where(scoreValue < 60)` |
| 「给张三的数学课录入 95 分」 | `createScore(studentId=?, courseId=?, scoreValue=95)` |

### 7.3 LLM 集成

- 使用用户已配置的 DeepSeek API
- 将 Ontology Schema（Object/Link/Action/Function）作为 System Prompt + Tool Definitions 传给 LLM
- LLM 返回的不是 SQL，而是 Ontology 操作指令，由引擎执行
- 关键：LLM 不接触底层表结构，只感知 Ontology 语义

## 8. 非功能需求

- **零外部依赖安装**：优先 SQLite，不需要用户安装 PostgreSQL
- **可运行在单机**：整个 demo 在本地一键启动
- **审计日志**：所有 Action 操作记录到 audit_log 表
- **种子数据**：预置 3-5 个学生、2-3 个教师、3-5 门课程、若干成绩，开箱可演示

## 9. 技术栈

| 层 | 选型 | 说明 |
|---|------|------|
| 后端框架 | Python + FastAPI | REST API，自动生成 Swagger 文档 |
| 数据库 | SQLite | 零依赖，单文件，开发阶段可随时重建 |
| 前端 | 纯 HTML/CSS/JS（单页面） | 不引入前端框架，由 FastAPI 直接 serve |
| 图谱可视化 | vis.js | 力导向图开箱即用，API 简洁 |
| 自然语言查询 | DeepSeek API | 已配置，LLM 感知 Ontology Schema |
| Ontology 引擎 | 纯 Python 模块 | Schema 注册、查询翻译、Action 执行、Function 计算 |
