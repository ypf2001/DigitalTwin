"""
TIA Portal 项目读取器 — 使用 Openness API
============================================

功能：
- 读取 TIA 项目结构（PLC、HMI、DB块、标签表）
- 导出 PLC 程序源码和配置
- 分析 DB 块变量定义
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 添加 plc_openness_v21 到路径
OPENNESS_ROOT = Path(__file__).parent.parent / "plc_openness_v21"
sys.path.insert(0, str(OPENNESS_ROOT))

from openness_loader import load_openness, start_tia
from plc_programming import (
    attach_to_open_project,
    open_project,
    get_plc_software,
    iter_plc_softwares,
    find_plc_block,
    export_plc_block_xml,
    compile_plc_software,
)


class TIAProjectReader:
    """TIA Portal 项目读取器"""

    def __init__(self, project_path: str, with_ui: bool = True):
        """
        初始化项目读取器

        参数:
            project_path: .ap21 项目文件路径
            with_ui: 是否启动 TIA Portal UI
        """
        self.project_path = Path(project_path).resolve()
        self.with_ui = with_ui
        self._tia = None
        self._project = None
        self._attached = False

    def connect(self) -> bool:
        """连接到 TIA Portal 项目"""
        load_openness()

        # 尝试附加到已打开的项目
        self._tia, self._project = attach_to_open_project(str(self.project_path))
        self._attached = self._project is not None

        if self._tia is None:
            print(f"[Openness] 启动 TIA Portal...")
            self._tia = start_tia(with_ui=self.with_ui)

        if self._project is None:
            print(f"[Openness] 打开项目: {self.project_path}")
            self._project = open_project(self._tia, str(self.project_path))

        print(f"[Openness] 已连接到项目: {self._project.Name}")
        return True

    def disconnect(self):
        """断开连接"""
        if self._project is not None and not self._attached:
            self._project.Close()
        if self._tia is not None:
            self._tia.Dispose()
        print("[Openness] 已断开连接")

    def list_plcs(self) -> list:
        """列出项目中所有 PLC"""
        plcs = []
        for software in iter_plc_softwares(self._project):
            plcs.append({
                "name": software.Name,
                "type": str(software.GetType().Name),
            })
        return plcs

    def get_plc_software(self, plc_name: Optional[str] = None):
        """获取 PLC 软件对象"""
        return get_plc_software(self._project, plc_name)

    def list_tag_tables(self, plc_name: Optional[str] = None) -> list:
        """列出 PLC 标签表"""
        plc = self.get_plc_software(plc_name)
        tables = []
        for table in plc.TagTableGroup.TagTables:
            tags = []
            for tag in table.Tags:
                tags.append({
                    "name": tag.Name,
                    "address": getattr(tag, "Address", ""),
                    "data_type": str(tag.DataType) if hasattr(tag, "DataType") else "",
                })
            tables.append({
                "name": table.Name,
                "tags": tags,
            })
        return tables

    def list_blocks(self, plc_name: Optional[str] = None) -> list:
        """列出 PLC 程序块"""
        plc = self.get_plc_software(plc_name)
        blocks = []
        for block in plc.BlockGroup.Blocks:
            blocks.append({
                "name": block.Name,
                "type": str(block.GetType().Name),
            })
        return blocks

    def export_block(self, block_name: str, output_path: str, plc_name: Optional[str] = None) -> str:
        """导出程序块为 XML"""
        plc = self.get_plc_software(plc_name)
        return str(export_plc_block_xml(plc, block_name, output_path))

    def compile_plc(self, plc_name: Optional[str] = None) -> dict:
        """编译 PLC 程序"""
        plc = self.get_plc_software(plc_name)
        result = compile_plc_software(plc)
        return {
            "state": str(result.State),
            "errors": result.ErrorCount,
            "warnings": result.WarningCount,
            "messages": [str(m.Description) for m in result.Messages],
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def read_xiaweiji_project():
    """读取 xiaweiji 项目示例"""
    project_path = r"D:\dw_plc\xiaweiji\xiaweiji.ap21"

    with TIAProjectReader(project_path) as reader:
        # 列出所有 PLC
        plcs = reader.list_plcs()
        print(f"\n=== PLC 列表 ===")
        for plc in plcs:
            print(f"  - {plc['name']} ({plc['type']})")

        # 列出标签表
        print(f"\n=== 标签表 ===")
        tables = reader.list_tag_tables()
        for table in tables[:5]:  # 只显示前5个
            print(f"  表: {table['name']}")
            for tag in table['tags'][:5]:  # 每个表只显示前5个标签
                print(f"    - {tag['name']} @ {tag['address']}")

        # 列出程序块
        print(f"\n=== 程序块 ===")
        blocks = reader.list_blocks()
        for block in blocks:
            print(f"  - {block['name']} ({block['type']})")

    return True


if __name__ == "__main__":
    read_xiaweiji_project()