"""对话引擎包 — 对话式AI报销智能体核心

模块职责:
    - intent_registry: 33个意图定义（员工15/管理员14/老板10/通用6）
    - nlu_router: L1关键词 → L2语义 → L3 LLM 三级路由
    - role_gate: 三角色权限矩阵（员工/管理员/老板）
    - dialog_fsm: 对话状态机 + 多轮槽位填充
    - context_store: Redis/内存上下文持久化
    - dialog_engine: 主引擎编排器
"""
