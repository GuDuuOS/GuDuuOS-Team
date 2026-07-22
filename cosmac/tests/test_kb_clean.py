# -*- coding: utf-8 -*-
"""知识库上传清洗单测(负责人实报:上传"空"CSV 却提示太长 20845字>20000)。

Excel 把空工作表另存 CSV 会导出上万行纯逗号(空单元格分隔符)——视觉空文件按
原文计数误报超限。clean_upload_text 在计数/入库前清洗:CSV/TSV 剔除纯分隔符行,
所有文件去行尾空白+压缩连续空行。另验上限已放宽 2万→5万。

运行:.venv/bin/python -m unittest cosmac.tests.test_kb_clean
"""

from __future__ import annotations

import unittest

from cosmac.db.kb_cmd import MAX_DOC_CHARS, clean_upload_text


class TestCleanUploadText(unittest.TestCase):
    def test_empty_excel_csv_cleans_to_nothing(self) -> None:
        """线上原样:Excel 导出的"空"表——上万行纯逗号,清洗后应为空。"""
        text = "\n".join([","*40] * 500)   # 500 行×40 个逗号 ≈ 20500 字
        self.assertGreater(len(text), 20000)  # 未清洗时确实会触发旧报错
        self.assertEqual(clean_upload_text(text, "新建 XLS 工作表.csv"), "")

    def test_real_csv_rows_survive(self) -> None:
        """有真实数据的 CSV:内容行保留,空单元格行剔除。"""
        text = "名称,价格,备注\n白金系列,4520,高端抗老\n,,,\n,,,\n晶钻系列,8900,"
        out = clean_upload_text(text, "价格表.csv")
        self.assertIn("白金系列,4520,高端抗老", out)
        self.assertIn("晶钻系列,8900,", out)
        self.assertNotIn(",,,", out.split("\n"))

    def test_non_csv_keeps_commas_but_squashes_blanks(self) -> None:
        """非 CSV 文件:逗号行不剔除(可能是正文),只压缩连续空行/去行尾空白。"""
        text = "第一段,含逗号\n\n\n\n第二段   \n"
        out = clean_upload_text(text, "笔记.md")
        self.assertIn("第一段,含逗号", out)
        self.assertIn("第二段", out)
        self.assertNotIn("\n\n\n", out)
        self.assertNotIn("第二段   ", out)  # 行尾空白去掉

    def test_limit_raised_to_50k(self) -> None:
        """上限放宽:2万字的产品手册不再被拒(负责人:2万对知识库场景偏小)。"""
        self.assertEqual(MAX_DOC_CHARS, 50000)


if __name__ == "__main__":
    unittest.main()
