/**
 * MarkdownRenderer - 轻量级 Markdown 渲染组件
 * 支持：表格、加粗、换行
 */
interface MarkdownRendererProps {
  content: string;
}

/** 解析内联样式（加粗） */
function parseInline(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  const boldRegex = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match;

  while ((match = boldRegex.exec(text)) !== null) {
    // 添加加粗前的普通文本
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    // 添加加粗文本
    parts.push(<strong key={`bold-${match.index}`}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
  }

  // 添加剩余文本
  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

/** 解析 Markdown 表格 */
function parseTable(lines: string[]): React.ReactElement | null {
  // 至少需要 3 行：表头、分隔符、一行数据
  if (lines.length < 3) return null;

  const parseRow = (line: string): string[] => {
    return line
      .split("|")
      .slice(1, -1) // 去掉首尾空元素
      .map((cell) => cell.trim());
  };

  const headerCells = parseRow(lines[0]);
  const separatorLine = lines[1];
  const dataRows = lines.slice(2).map(parseRow);

  // 验证分隔符行
  if (!separatorLine.match(/^\|[\s\-:|]+\|$/)) {
    return null;
  }

  return (
    <table className="md-table my-2">
      <thead>
        <tr>
          {headerCells.map((cell, i) => (
            <th key={i}>{parseInline(cell)}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {dataRows.map((row, rowIdx) => (
          <tr key={rowIdx}>
            {row.map((cell, cellIdx) => (
              <td key={cellIdx}>{parseInline(cell)}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const lines = content.split("\n");
  const elements: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // 检查是否为表格开始（包含 | 且下一行是分隔符）
    if (line.includes("|") && i + 1 < lines.length && lines[i + 1].includes("|---")) {
      // 收集连续的表格行
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].includes("|")) {
        tableLines.push(lines[i]);
        i++;
      }

      const table = parseTable(tableLines);
      if (table) {
        elements.push(table);
      } else {
        // 解析失败，作为普通文本
        tableLines.forEach((tl, idx) => {
          elements.push(
            <div key={`fallback-${i}-${idx}`}>
              {parseInline(tl)}
            </div>
          );
        });
      }
    } else if (line.trim() === "") {
      // 空行
      elements.push(<div key={`empty-${i}`} className="h-2" />);
      i++;
    } else {
      // 普通文本行
      elements.push(
        <div key={`text-${i}`}>
          {parseInline(line)}
        </div>
      );
      i++;
    }
  }

  return <div className="space-y-1">{elements}</div>;
}
