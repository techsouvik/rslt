import { useEffect, useRef } from 'react';
import { X, Zap, User, Loader2 } from 'lucide-react';
import type { ChatMessage } from '@/api/client';
import MarkdownRenderer from '@/components/MarkdownRenderer';

interface ChatDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  messages: ChatMessage[];
  loading: boolean;
  activeChatId: string;
}

export default function ChatDrawer({
  isOpen,
  onClose,
  messages,
  loading,
  activeChatId,
}: ChatDrawerProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, isOpen, loading]);



  return (
    <>
      {/* Backdrop overlay for mobile views */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-30 md:hidden"
          onClick={onClose}
        />
      )}

      {/* Sliding Panel */}
      <div
        className={`fixed right-0 top-0 h-screen w-full sm:w-[420px] flex flex-col glass-panel-heavy border-l border-glass-border z-40 shadow-2-xl transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="px-5 py-4 flex items-center justify-between border-b border-white/[0.06] bg-white/[0.01]">
          <div className="flex items-center gap-2.5">
            <div className="flex items-center justify-center w-7 h-7 rounded-md bg-gradient-to-tr from-primary to-blue-500 shadow-sm-glow">
              <Zap className="w-3.5 h-3.5 text-white" />
            </div>
            <div>
              <h3 className="text-label-md font-semibold text-text-primary">Assistant Chat</h3>
              <p className="text-[10px] uppercase text-text-tertiary tracking-wider font-semibold">
                {activeChatId ? `Session #${activeChatId.slice(-6)}` : 'No active session'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/[0.06] text-text-secondary hover:text-text-primary transition-colors duration-150"
          >
            <X className="w-[18px] h-[18px]" />
          </button>
        </div>

        {/* Message Feed */}
        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-5 py-6 space-y-5 no-scrollbar scroll-smooth"
        >
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center max-w-[280px] mx-auto opacity-70">
              <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-4 border border-primary/20">
                <Zap className="w-5 h-5 text-primary animate-pulse" />
              </div>
              <p className="text-headline-md text-text-primary mb-1">Interactive UGC Chat</p>
              <p className="text-body-md text-text-tertiary">
                Ask about token count, external APIs used, or prompt the assistant to draft visual scripts!
              </p>
            </div>
          ) : (
            messages.map((msg, index) => {
              const isUser = msg.role === 'user';
              return (
                <div
                  key={index}
                  className={`flex gap-3 max-w-[85%] animate-fade-in ${
                    isUser ? 'ml-auto flex-row-reverse' : 'mr-auto'
                  }`}
                >
                  {/* Avatar */}
                  <div
                    className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center border shadow-inner-glow ${
                      isUser
                        ? 'bg-secondary border-white/[0.08] text-text-secondary'
                        : 'bg-gradient-to-tr from-primary/20 to-blue-500/20 border-primary/30 text-primary'
                    }`}
                  >
                    {isUser ? (
                      <User className="w-3.5 h-3.5" />
                    ) : (
                      <Zap className="w-3.5 h-3.5" />
                    )}
                  </div>

                  {/* Bubble */}
                  <div
                    className={`px-4 py-3 rounded-2xl text-body-md leading-relaxed shadow-sm border transition-all duration-150 ${
                      isUser
                        ? 'bg-primary/[0.12] border-primary/25 text-text-primary rounded-tr-none'
                        : 'glass-panel border border-white/[0.06] text-text-primary rounded-tl-none'
                    }`}
                  >
                    {isUser ? (
                      <p className="whitespace-pre-wrap">{msg.content}</p>
                    ) : (
                      <MarkdownRenderer content={msg.content} />
                    )}
                  </div>
                </div>
              );
            })
          )}

          {/* Typing Loading Indicator */}
          {loading && (
            <div className="flex gap-3 max-w-[85%] mr-auto">
              <div className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center border bg-gradient-to-tr from-primary/10 to-blue-500/10 border-primary/10 text-primary">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              </div>
              <div className="px-4 py-3 rounded-2xl glass-panel border border-white/[0.04] text-text-tertiary rounded-tl-none flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-1.5 h-1.5 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
