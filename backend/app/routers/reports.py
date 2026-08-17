"""报表生成路由"""

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.reimbursement import Reimbursement
from app.routers.admin_auth import get_current_admin, get_current_admin_or_boss
from app.services.report_generator import ReportGenerator

router = APIRouter(dependencies=[Depends(get_current_admin_or_boss)])


@router.post("/generate/{reimbursement_id}")
async def generate_reports(
    reimbursement_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: dict = Depends(get_current_admin),
):
    """生成报销包（Excel + PDF + ZIP）"""
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimbursement_id)
    )
    reimbursement = result.scalars().first()
    if not reimbursement:
        raise HTTPException(status_code=404, detail="Reimbursement not found")

    generator = ReportGenerator(db)
    paths = await generator.generate_all(reimbursement_id)
    return {"status": "ok", "files": paths}


@router.get("/download/{reimbursement_id}/{file_type}")
async def download_report(
    reimbursement_id: int,
    file_type: str,  # xlsx / pdf / zip
    db: AsyncSession = Depends(get_db),
):
    """下载报表文件"""
    result = await db.execute(
        select(Reimbursement).where(Reimbursement.id == reimbursement_id)
    )
    reimbursement = result.scalars().first()
    if not reimbursement:
        raise HTTPException(status_code=404, detail="Not found")

    path_map = {
        "xlsx": reimbursement.excel_path,
        "pdf": reimbursement.pdf_path,
        "zip": reimbursement.zip_path,
    }
    file_path = path_map.get(file_type)
    if not file_path:
        raise HTTPException(status_code=404, detail=f"{file_type} file not generated")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="报表文件不存在，请重新生成")

    return FileResponse(
        file_path,
        filename=f"reimbursement_{reimbursement_id}.{file_type}",
        media_type="application/octet-stream",
    )
