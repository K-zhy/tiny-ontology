# Ontology Semantic Layer Demo

A student grade management system demo built on **Palantir Ontology** design principles. Raw SQLite tables (student/teacher/course/score) are wrapped into an Ontology semantic layer of Object/Link/Action/Function, exposing business semantics rather than SQL to upper layers.

**Core philosophy**: LLMs and applications only perceive business objects (Student, Course, Score) — they never touch raw table schemas.

![Frontend Screenshot](assets/image.png)

## Quick Start

```bash
# 1. Install dependencies
pip install fastapi uvicorn httpx

# 2. Initialize database and load seed data
python seed_data.py

# 3. Start the server
python server.py
```

Visit http://localhost:8000 for the frontend graph UI, http://localhost:8000/docs for Swagger API docs.

## Architecture

```
SQLite Raw Tables (student / teacher / course / score)
        │
        ▼  Mapping config (registry.py)
Ontology Semantic Layer
  ├── Object Types:  Student, Teacher, Course, Score
  ├── Link Types:    earnedBy, forCourse, taughtBy
  ├── Action Types:  createScore, updateScore, deleteScore, assignTeacher
  ├── Functions:     getAvgScore, getTopStudents, getPassRate ...
  └── Interfaces:    Nameable, Scoreable
        │
        ▼  Exposure (server.py)
┌─────────────────────────────────────────────┐
│  REST API    │  Frontend Graph │  NL Query   │
│  CRUD endpoints │  vis.js       │  Graph Walk │
│  /docs       │  Force-directed │  + Batch    │
└─────────────────────────────────────────────┘
```

## Core Concepts

### Five-Element Model

| Concept | Role | Example |
|---------|------|---------|
| **Object Type** | Business entity (noun) | Student, Course |
| **Link Type** | Entity relationship (verb) | earnedBy (who the score belongs to), taughtBy (who teaches it) |
| **Action Type** | Write operation (imperative) | createScore (record a grade) |
| **Function** | Computation & reasoning | getAvgScore (calculate average) |
| **Interface** | Cross-object capability contract | Nameable (searchable by name) |

### Three Property Types

| Type | Description | Example |
|------|-------------|---------|
| Primary Key | Unique identifier | `id` |
| Regular | Stored business field | `name`, `age`, `credit` |
| Derived | Dynamically computed by Function | `avgScore`, `passRate` |

### Action Execution Pipeline

```
Param validation → Business validation → Transactional execution → Audit log → Commit/Rollback
```

All writes must go through Actions. Direct table writes are forbidden.

## Natural Language Query

Two NL query modes, sharing the underlying in-memory graph engine (`OntologyGraph`).

### Graph Walk Mode `POST /ontology/nl-query-graph` (Recommended)

The LLM explores the graph step-by-step through 7 graph-native tools. Each tool response includes node metadata (available traversals + bound functions), enabling the LLM to dynamically decide the next step:

| Tool | Function |
|------|----------|
| `list_object_types` | List all available object types and their metadata |
| `search_by_semantic` | Cross-type fuzzy search (substring match across all text properties) |
| `search_objects` | Search by type + property filters (supports exact/fuzzy matching) |
| `traverse` | Walk along a Link to neighbor nodes |
| `get_node_detail` | Get full node info including derived properties |
| `call_function` | Invoke bound functions (average, ranking, etc.) |
| `execute_action` | Execute write operations (create/update scores, etc.) |

### Batch Planning Mode `POST /ontology/nl-query`

The LLM outputs a complete JSON operation sequence in one shot. The engine executes it step by step, then generates a natural language answer.

### Example Queries

| Query | Steps | Path |
|-------|-------|------|
| "What's Zhang San's average score?" | 2 | search_objects → call_function getAvgScore |
| "Who got the highest in Advanced Mathematics?" | 3 | search_objects → traverse scores → call_function getTopStudents |
| "Find anything computer-related" | 1 | search_by_semantic("计算机") |
| "What object types are available?" | 1 | list_object_types |
| "Record Zhang San's Advanced Math score as 85" | 1 | execute_action createScore |

## API Endpoints

### Schema Metadata

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ontology/schema` | Full Schema definition (frontend graph + LLM tool definitions) |
| GET | `/ontology/graph/schema` | Type-level graph (Object Types + Link Types) |
| GET | `/ontology/graph` | Full instance graph data (nodes + edges) |
| GET | `/ontology/interfaces` | All Interface definitions |

### Object Queries

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ontology/objects/{type}` | Query objects (fuzzy name match, sorting, pagination) |
| GET | `/ontology/objects/{type}/{id}` | Get single object (with derived properties) |
| GET | `/ontology/objects/{type}/{id}/links/{link}` | Traverse Link to get related objects |

### Compute & Actions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/ontology/functions/{funcName}` | Call a Function |
| POST | `/ontology/actions/{actionName}` | Execute an Action |

### Natural Language Query

| Method | Path | Description |
|--------|------|-------------|
| POST | `/ontology/nl-query-graph` | Graph Walk mode (recommended) |
| POST | `/ontology/nl-query` | Batch Planning mode |

## Project Structure

```
ontology/
├── server.py                       # FastAPI entry point
├── seed_data.py                    # Seed data (3 teachers, 5 courses, 5 students, 20 scores)
├── static/
│   └── index.html                  # Single-page frontend (vis.js force-directed graph + NL query)
├── ontology_engine/
│   ├── schema.py                   # Core dataclass definitions
│   ├── registry.py                 # Mapping config hub (add new Object/Link/Action/Function here)
│   ├── database.py                 # SQLite connection management + table creation
│   ├── graph.py                    # In-memory graph engine (adjacency list, O(1) traversal)
│   ├── query.py                    # Query engine (semantic operations → SQL translation)
│   ├── action.py                   # Action engine (validation → transaction → audit)
│   └── functions.py                # Function engine (SQL computation logic)
└── Palantir_Ontology_详解.md       # Palantir Ontology design reference (Chinese)
```

## Adding New Ontology Elements

1. Create table in `database.py:init_db()` (if needed)
2. Add `ObjectTypeDef` / `LinkTypeDef` / `FunctionDef` / `ActionTypeDef` in `registry.py`
3. New Function → add logic in `functions.py:call_function()`
4. New Action → add logic in `action.py:_run_action()`
5. The graph engine auto-reads from registry and builds the graph structure
6. Add seed data in `seed_data.py`

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_BASE_URL` | LLM API URL | `https://api.deepseek.com/anthropic` |
| `ANTHROPIC_AUTH_TOKEN` | LLM API key | — |
| `ANTHROPIC_MODEL` | Model name | `deepseek-v4-pro[1m]` |

## Contributions Welcome

This is an open community project — anyone interested is welcome to contribute! Whether you are a:

- **Learner**: Curious about Ontology semantic layer concepts and want to learn through real code
- **Developer**: Want to add new Object/Link/Action/Function types or improve existing implementations
- **Researcher**: Have deep insights into Palantir Ontology design principles and want to share your understanding
- **User**: Found a bug or have feature suggestions

### How to Contribute

- **Issues**: Discussions on Ontology design philosophy, architecture improvements, feature requests
- **Pull Requests**: Code improvements, new features, documentation, bug fixes
- **Ideas**: Share your thoughts on Ontology semantic layers, OAG (Ontology Augmented Generation), AI Agent + Knowledge Graph integration in Discussions

All contributors will be credited in the project's contributor list.

## References

- [Palantir Foundry - Ontology Overview](https://www.palantir.com/docs/foundry/ontology/overview/)
- [Building with Palantir AIP: Data Tools for RAG/OAG](https://blog.palantir.com/building-with-palantir-aip-data-tools-for-rag-oag-b3b509c8b0f3)
- [Building with Palantir AIP: Logic Tools for RAG/OAG](https://blog.palantir.com/building-with-palantir-aip-logic-tools-for-rag-oag-fdaf8938d02e)

## Disclaimer

This project is an independent open-source study and implementation of [Palantir Ontology](https://www.palantir.com/docs/foundry/ontology/overview/) design principles. All code is independently written. This project is not affiliated with, sponsored by, or endorsed by Palantir Technologies Inc. in any way. "Palantir" and "Foundry" are trademarks of Palantir Technologies Inc.
