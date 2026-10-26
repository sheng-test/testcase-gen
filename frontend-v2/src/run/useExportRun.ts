// 运行导出：Excel / Markdown 下载状态与错误提示（用例页、报告页共用）。

import { useState } from "react";
import { downloadRunExport, type ExportFormat } from "../api/v2";
import { useToast } from "../components/Toast";

export function useExportRun(runId: string) {
  const toast = useToast();
  const [exporting, setExporting] = useState<ExportFormat | null>(null);

  const exportRun = async (format: ExportFormat) => {
    setExporting(format);
    try {
      await downloadRunExport(runId, format);
      toast(`已导出 ${format === "xlsx" ? "Excel" : "Markdown"}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "导出失败", "error");
    } finally {
      setExporting(null);
    }
  };

  return { exporting, exportRun };
}
