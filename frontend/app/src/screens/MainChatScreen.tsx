import { useEffect, useRef } from 'react';
import { User, Zap, Loader2 } from 'lucide-react';
import type { ChatMessage } from '@/api/client';
import MarkdownRenderer from '@/components/MarkdownRenderer';
import InlineJobRenderer from '@/components/InlineJobRenderer';

interface MainChatScreenProps {
  messages: ChatMessage[];
  loading: boolean;
  currentJobId: string | null;
  jobProgress?: {
    progress: number;
    status: string;
    message: string;
    connected: boolean;
  };
}

export default function MainChatScreen({
  messages,
  loading,
  currentJobId,
  jobProgress,
}: MainChatScreenProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to the bottom of the feed when messages change or loading state triggers
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, loading]);

  return (
    <div className="w-full max-w-[800px] mx-auto px-4 py-8 flex flex-col gap-6">
      {messages.map((msg, index) => {
        const isUser = msg.role === 'user';
        
        // Find if this assistant message triggered a video generation job
        const jobMatch = !isUser && msg.content.match(/job_[a-fA-F0-9]{8}/i);
        const jobId = jobMatch ? jobMatch[0] : null;

        return (
          <div key={index} className="flex flex-col gap-3">
            <div
              className={`flex gap-4 max-w-[85%] animate-fade-in ${
                isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
              }`}
            >
              {/* Avatar */}
              <div
                className={`flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center border shadow-inner-glow ${
                  isUser
                    ? 'bg-secondary border-white/[0.08] text-text-secondary'
                    : 'bg-gradient-to-tr from-primary/20 to-blue-500/20 border-primary/30 text-primary'
                }`}
              >
                {isUser ? (
                  <User className="w-4 h-4" />
                ) : (
                  <Zap className="w-4 h-4" />
                )}
              </div>

              {/* Message Bubble */}
              <div
                className={`px-5 py-3.5 rounded-2xl text-body-md leading-relaxed shadow-sm border transition-all duration-150 ${
                  isUser
                    ? 'bg-primary/[0.12] border-primary/25 text-text-primary rounded-tr-none'
                    : 'glass-panel border-white/[0.06] text-text-primary rounded-tl-none'
                }`}
              >
                {isUser ? (
                  <p className="whitespace-pre-wrap">{msg.content}</p>
                ) : (
                  <MarkdownRenderer content={msg.content} />
                )}
              </div>
            </div>

            {/* Chronological Inline Video Player / Progress Tracker */}
            {jobId && (
              <div className="w-full max-w-[85%] pl-[52px] animate-fade-in">
                <InlineJobRenderer
                  jobId={jobId}
                  currentJobId={currentJobId}
                  currentJobProgress={jobProgress}
                />
              </div>
            )}
          </div>
        );
      })}

      {/* Typing Loading State */}
      {loading && (
        <div className="flex gap-4 max-w-[85%] mr-auto animate-fade-in">
          <div className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center border bg-gradient-to-tr from-primary/10 to-blue-500/10 border-primary/10 text-primary">
            <Loader2 className="w-4 h-4 animate-spin" />
          </div>
          <div className="px-5 py-3.5 rounded-2xl glass-panel border border-white/[0.04] text-text-tertiary rounded-tl-none flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </div>
        </div>
      )}

      {/* Anchor for Auto-Scroll */}
      <div ref={bottomRef} className="h-4" />
    </div>
  );
}
