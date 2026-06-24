import React from 'react';

interface MarkdownRendererProps {
  content: string;
}

export default function MarkdownRenderer({ content }: MarkdownRendererProps) {
  if (!content) return null;

  // 1. Block Parsing
  const lines = content.split('\n');
  const blocks: React.ReactNode[] = [];
  
  let currentList: { type: 'ul' | 'ol'; items: string[] } | null = null;
  let inCodeBlock = false;
  let codeBlockLanguage = '';
  let codeBlockLines: string[] = [];

  const flushList = (key: string | number) => {
    if (!currentList) return;
    const ListTag = currentList.type;
    const listItems = currentList.items.map((item, idx) => {
      const isOrdered = currentList?.type === 'ol';
      return (
        <li 
          key={idx} 
          className={`pl-1 text-text-primary my-1.5 ${
            isOrdered ? 'list-decimal ml-6' : 'list-disc ml-5'
          }`}
        >
          {renderInlineMarkdown(item)}
        </li>
      );
    });
    blocks.push(
      <ListTag key={`list-${key}`} className="my-3 space-y-1">
        {listItems}
      </ListTag>
    );
    currentList = null;
  };

  // Process line by line
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Handle Code Blocks
    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        // End of code block
        const codeText = codeBlockLines.join('\n');
        blocks.push(
          <div key={`code-${i}`} className="my-4 rounded-xl overflow-hidden border border-white/[0.08] bg-[#0d0e14] font-code animate-fade-in">
            {codeBlockLanguage && (
              <div className="px-4 py-1.5 border-b border-white/[0.04] bg-white/[0.02] flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-wider font-semibold text-text-tertiary">
                  {codeBlockLanguage}
                </span>
              </div>
            )}
            <pre className="p-4 overflow-x-auto text-[13px] text-text-primary leading-relaxed font-mono">
              <code>{codeText}</code>
            </pre>
          </div>
        );
        inCodeBlock = false;
        codeBlockLines = [];
        codeBlockLanguage = '';
      } else {
        // Start of code block
        inCodeBlock = true;
        codeBlockLanguage = line.trim().slice(3).trim();
      }
      continue;
    }

    if (inCodeBlock) {
      codeBlockLines.push(line);
      continue;
    }

    // Handle bullet lists (* or -)
    const bulletMatch = line.match(/^(?:\s*[-*]\s+)(.+)$/);
    if (bulletMatch) {
      if (!currentList || currentList.type !== 'ul') {
        flushList(i);
        currentList = { type: 'ul', items: [] };
      }
      currentList.items.push(bulletMatch[1]);
      continue;
    }

    // Handle numbered lists (1. 2. etc)
    const olMatch = line.match(/^(?:\s*\d+\.\s+)(.+)$/);
    if (olMatch) {
      if (!currentList || currentList.type !== 'ol') {
        flushList(i);
        currentList = { type: 'ol', items: [] };
      }
      currentList.items.push(olMatch[1]);
      continue;
    }

    // Line is not a list item, so flush any active lists
    if (currentList) {
      flushList(i);
    }

    const trimmed = line.trim();

    // Skip empty lines (render vertical spacing)
    if (!trimmed) {
      blocks.push(<div key={`spacer-${i}`} className="h-2.5" />);
      continue;
    }

    // Handle Headers
    if (trimmed.startsWith('### ')) {
      blocks.push(
        <h3 key={`h3-${i}`} className="text-base font-semibold text-text-primary mt-5 mb-2">
          {renderInlineMarkdown(trimmed.slice(4))}
        </h3>
      );
      continue;
    }
    if (trimmed.startsWith('## ')) {
      blocks.push(
        <h2 key={`h2-${i}`} className="text-lg font-semibold text-text-primary mt-6 mb-3 border-b border-white/[0.04] pb-1">
          {renderInlineMarkdown(trimmed.slice(3))}
        </h2>
      );
      continue;
    }
    if (trimmed.startsWith('# ')) {
      blocks.push(
        <h1 key={`h1-${i}`} className="text-xl font-bold text-text-primary mt-6 mb-4">
          {renderInlineMarkdown(trimmed.slice(2))}
        </h1>
      );
      continue;
    }

    // Handle Horizontal Rule
    if (trimmed === '---' || trimmed === '***') {
      blocks.push(<hr key={`hr-${i}`} className="my-5 border-white/[0.08]" />);
      continue;
    }

    // Handle Blockquotes
    if (trimmed.startsWith('> ')) {
      blocks.push(
        <blockquote key={`quote-${i}`} className="my-3 pl-4 border-l-2 border-primary/50 text-text-primary/90 italic">
          {renderInlineMarkdown(trimmed.slice(2))}
        </blockquote>
      );
      continue;
    }

    // Regular Paragraph
    blocks.push(
      <p key={`p-${i}`} className="mb-2.5 last:mb-0 text-text-primary leading-relaxed">
        {renderInlineMarkdown(line)}
      </p>
    );
  }

  // Flush unfinished code blocks (crucial for streaming / in-progress responses)
  if (inCodeBlock && codeBlockLines.length > 0) {
    const codeText = codeBlockLines.join('\n');
    blocks.push(
      <div key="code-unfinished" className="my-4 rounded-xl overflow-hidden border border-white/[0.08] bg-[#0d0e14] font-code animate-fade-in">
        <div className="px-4 py-1.5 border-b border-white/[0.04] bg-white/[0.02] flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wider font-semibold text-text-tertiary flex items-center gap-1.5">
            {codeBlockLanguage || 'code'}
            <span className="w-1.5 h-1.5 bg-primary rounded-full animate-pulse" />
          </span>
        </div>
        <pre className="p-4 overflow-x-auto text-[13px] text-text-primary leading-relaxed font-mono">
          <code>{codeText}</code>
        </pre>
      </div>
    );
  }

  // Flush any final list
  if (currentList) {
    flushList('final');
  }

  return <div className="prose prose-invert max-w-none text-text-primary">{blocks}</div>;
}

// 2. Inline Parsing Helper
function renderInlineMarkdown(text: string): React.ReactNode[] {
  if (!text) return [];

  // Robustly parse inline markers: bold, italic, code, and links.
  const regex = /(\*\*.*?\*\*|\*.*?\*|`.*?`|\[.*?\]\(.*?\))/g;
  const parts = text.split(regex);

  return parts.map((part, index) => {
    // Bold: **text**
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={index} className="font-semibold text-text-primary">
          {part.slice(2, -2)}
        </strong>
      );
    }
    // Italic: *text*
    if (part.startsWith('*') && part.endsWith('*')) {
      return (
        <em key={index} className="italic text-text-primary/90">
          {part.slice(1, -1)}
        </em>
      );
    }
    // Inline Code: `code`
    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={index} className="bg-white/10 px-1.5 py-0.5 rounded font-mono text-primary text-[13px]">
          {part.slice(1, -1)}
        </code>
      );
    }
    // Link: [text](url)
    if (part.startsWith('[') && part.includes('](') && part.endsWith(')')) {
      const closeBracketIndex = part.indexOf('](');
      if (closeBracketIndex !== -1) {
        const linkText = part.slice(1, closeBracketIndex);
        const linkUrl = part.slice(closeBracketIndex + 2, -1);
        return (
          <a
            key={index}
            href={linkUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary hover:text-blue-400 hover:underline transition-colors duration-150 font-medium"
          >
            {linkText}
          </a>
        );
      }
    }
    // Plain Text
    return part;
  });
}
