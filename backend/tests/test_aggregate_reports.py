"""归集后自动生成报表测试

验证 aggregate_pending_invoices 归集发票后，对生成的报销单调 ReportGenerator.generate_all，
确保对话触发和定时任务路径一致，报销单都有 Excel/PDF/ZIP 报表。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.aggregation_service import aggregate_pending_invoices
from app.models.invoice import Invoice, ReceiptType, InvoiceStatus
from app.models.reimbursement import Reimbursement, ReimbursementStatus


def _make_invoice(inv_id: int, user_id: str = "EMP002"):
    return Invoice(
        id=inv_id,
        receipt_type=ReceiptType.vat_normal,
        user_id=user_id,
        file_type="jpg",
        status=InvoiceStatus.reviewed,
        reimbursement_id=None,
    )


def _make_reimbursement(reimb_id: int, status=ReimbursementStatus.draft):
    return Reimbursement(
        id=reimb_id,
        applicant_id="EMP002",
        status=status,
    )


class TestAggregateGeneratesReports:
    """aggregate_pending_invoices 归集后生成报表"""

    async def test_generate_all_called_for_each_reimbursement(self, mock_db):
        """归集 2 张发票到 2 个报销单 → generate_all 被调 2 次"""
        inv1 = _make_invoice(101)
        inv2 = _make_invoice(102)

        reimb1 = _make_reimbursement(201)
        reimb2 = _make_reimbursement(202)

        # 第一次查询：游离发票
        # 第二次查询：草稿报销单（auto submit）
        # 第三次+查询：generate_all 内部查报销单
        inv_scalars = MagicMock()
        inv_scalars.all.return_value = [inv1, inv2]
        inv_result = MagicMock()
        inv_result.scalars.return_value = inv_scalars

        reimb_scalars = MagicMock()
        reimb_scalars.all.return_value = [reimb1, reimb2]
        reimb_result = MagicMock()
        reimb_result.scalars.return_value = reimb_scalars

        mock_db.execute = AsyncMock(side_effect=[inv_result, reimb_result])
        mock_db.commit = AsyncMock()

        # mock attach_invoice_to_cycle 返回报销单
        async def fake_attach(db, inv, today=None, cycle_end_day=None):
            return reimb1 if inv.id == 101 else reimb2

        # mock ReportGenerator.generate_all
        generate_all_mock = AsyncMock(return_value={
            "excel_path": "/tmp/test.xlsx",
            "pdf_path": "/tmp/test.pdf",
            "zip_path": "/tmp/test.zip",
        })

        with patch("app.services.aggregation_service.attach_invoice_to_cycle", fake_attach), \
             patch("app.services.report_generator.ReportGenerator.generate_all", generate_all_mock):
            result = await aggregate_pending_invoices(mock_db, user_id="EMP002", cycle_end_day=21)

        # 关键断言：generate_all 对每个报销单调用一次
        assert generate_all_mock.call_count == 2
        called_ids = [call.args[0] for call in generate_all_mock.call_args_list]
        assert 201 in called_ids
        assert 202 in called_ids
        # 返回结果含归集的报销单
        assert 201 in result["reimb_ids"]
        assert 202 in result["reimb_ids"]

    async def test_no_invoices_no_report_generation(self, mock_db):
        """无游离发票 → 不调 generate_all"""
        inv_scalars = MagicMock()
        inv_scalars.all.return_value = []
        inv_result = MagicMock()
        inv_result.scalars.return_value = inv_scalars
        mock_db.execute = AsyncMock(return_value=inv_result)

        generate_all_mock = AsyncMock()

        with patch("app.services.report_generator.ReportGenerator.generate_all", generate_all_mock):
            result = await aggregate_pending_invoices(mock_db, user_id="EMP002", cycle_end_day=21)

        assert result["total"] == 0
        generate_all_mock.assert_not_called()

    async def test_report_error_recorded_not_raised(self, mock_db):
        """generate_all 抛异常 → 记录到 errors，不中断"""
        inv1 = _make_invoice(101)
        reimb1 = _make_reimbursement(201)

        inv_scalars = MagicMock()
        inv_scalars.all.return_value = [inv1]
        inv_result = MagicMock()
        inv_result.scalars.return_value = inv_scalars

        reimb_scalars = MagicMock()
        reimb_scalars.all.return_value = [reimb1]
        reimb_result = MagicMock()
        reimb_result.scalars.return_value = reimb_scalars

        mock_db.execute = AsyncMock(side_effect=[inv_result, reimb_result])
        mock_db.commit = AsyncMock()

        async def fake_attach(db, inv, today=None, cycle_end_day=None):
            return reimb1

        # generate_all 抛异常
        generate_all_mock = AsyncMock(side_effect=Exception("report generation failed"))

        with patch("app.services.aggregation_service.attach_invoice_to_cycle", fake_attach), \
             patch("app.services.report_generator.ReportGenerator.generate_all", generate_all_mock):
            result = await aggregate_pending_invoices(mock_db, user_id="EMP002", cycle_end_day=21)

        # 关键断言：报表错误记录到 errors，不影响归集结果
        assert result["attached"] == 1
        assert 201 in result["reimb_ids"]
        assert len(result["errors"]) == 1
        assert result["errors"][0]["reimbursement_id"] == 201
