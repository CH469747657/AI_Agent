"""项目归属引擎

技术路线:
  1. 用户描述中直接提及项目名 → LLM实体抽取 + 精确匹配
  2. 用户负责的项目只有一个 → 自动归属
  3. 销售方在项目供应商映射中 → 关联匹配
  4. 无法确定 → 返回候选列表，询问用户
"""

import logging
from sqlalchemy import select, cast, Text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus
from app.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


class ProjectMatcher:
    """项目归属匹配引擎"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.llm = get_llm_service()

    async def match_project(
        self,
        invoice_data: dict,
        user_desc: str,
        user_id: str,
    ) -> dict:
        """
        返回:
        {
            "project_id": int | None,
            "project_name": str | None,
            "source": "description" | "auto_single" | "supplier_match" | "need_input",
            "confidence": float,
            "candidates": list  # 当需要用户选择时
        }
        """
        # Step 1: 从用户描述中提取项目名
        if user_desc:
            project = await self._extract_project_from_desc(user_desc)
            if project:
                logger.info(f"Project matched from description: {project.name}")
                return {
                    "project_id": project.id,
                    "project_name": project.name,
                    "source": "description",
                    "confidence": 1.0,
                    "candidates": [],
                }

        # Step 2: 查用户绑定的项目
        user_projects = await self._get_user_projects(user_id)
        if len(user_projects) == 1:
            logger.info(f"Auto-matched to single user project: {user_projects[0].name}")
            return {
                "project_id": user_projects[0].id,
                "project_name": user_projects[0].name,
                "source": "auto_single",
                "confidence": 0.8,
                "candidates": [],
            }

        # Step 3: 销售方关联
        seller = invoice_data.get("seller_name")
        if seller:
            project = await self._find_by_supplier(seller)
            if project:
                logger.info(f"Project matched by supplier: {project.name}")
                return {
                    "project_id": project.id,
                    "project_name": project.name,
                    "source": "supplier_match",
                    "confidence": 0.7,
                    "candidates": [],
                }

        # Step 4: 返回候选，询问用户
        candidates = [{"id": p.id, "name": p.name} for p in user_projects]
        return {
            "project_id": None,
            "project_name": None,
            "source": "need_input",
            "confidence": 0.0,
            "candidates": candidates,
        }

    async def _extract_project_from_desc(self, desc: str) -> Project | None:
        """用 LLM 从描述中提取项目名，再用数据库精确匹配"""
        # 获取所有活跃项目名
        result = await self.db.execute(
            select(Project).where(Project.status == ProjectStatus.active)
        )
        projects = result.scalars().all()
        project_names = [p.name for p in projects]

        if not project_names:
            return None

        # LLM 提取
        extracted_name = await self.llm.extract_project_name(desc, project_names)
        if not extracted_name:
            # 退化：简单的字符串包含匹配
            for p in projects:
                if p.name in desc:
                    return p
            return None

        # 精确匹配（支持模糊）
        for p in projects:
            if extracted_name in p.name or p.name in extracted_name:
                return p

        return None

    async def _get_user_projects(self, user_id: str) -> list[Project]:
        """获取用户关联的活跃项目"""
        result = await self.db.execute(
            select(Project).where(
                Project.status == ProjectStatus.active,
                cast(Project.member_ids, Text).contains(user_id),
            )
        )
        projects = result.scalars().all()
        # 如果用户没有绑定项目，返回所有活跃项目
        if not projects:
            result = await self.db.execute(
                select(Project).where(Project.status == ProjectStatus.active)
            )
            projects = result.scalars().all()
        return list(projects)

    async def _find_by_supplier(self, seller_name: str) -> Project | None:
        """通过销售方名称关联项目"""
        result = await self.db.execute(
            select(Project).where(
                Project.status == ProjectStatus.active,
                cast(Project.supplier_names, Text).contains(seller_name),
            )
        )
        return result.scalars().first()
