import {
  Plus,
  MessageSquare,
  Zap,
  Loader2,
  PanelLeft,
  PanelLeftClose,
} from 'lucide-react';
import type { Conversation } from '@/api/client';

interface SidebarProps {
  onNewVideo: () => void;
  onConversationClick: (chatId: string) => void;
  conversations: Conversation[];
  loading: boolean;
  activeChatId: string;
  isOpen: boolean;
  onToggle: () => void;
}

export default function Sidebar({
  onNewVideo,
  onConversationClick,
  conversations,
  loading,
  activeChatId,
  isOpen,
  onToggle,
}: SidebarProps) {
  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const handleNewVideo = () => {
    onNewVideo();
    onToggle();
  };

  const handleConvClick = (chatId: string) => {
    onConversationClick(chatId);
    onToggle();
  };

  return (
    <>
      {/* Toggle button — always visible */}
      <button
        onClick={onToggle}
        className="fixed top-4 left-4 z-50 w-9 h-9 flex items-center justify-center rounded-lg glass-panel text-text-secondary hover:text-text-primary transition-all duration-150"
        title={isOpen ? 'Close sidebar' : 'Open sidebar'}
      >
        {isOpen ? <PanelLeftClose className="w-[18px] h-[18px]" /> : <PanelLeft className="w-[18px] h-[18px]" />}
      </button>

      {/* Sidebar overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-30"
          onClick={onToggle}
        />
      )}

      {/* Sidebar panel */}
      <aside
        className={`fixed left-0 top-0 h-screen w-[260px] flex-col glass-panel-heavy border-r border-glass-border z-40 shadow-inner-glow transition-transform duration-300 ease-out flex ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand */}
        <div className="px-5 pt-5 pb-4 flex items-center gap-2">
          <div className="flex items-center justify-center w-7 h-7 rounded-md bg-primary">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <span className="text-label-md font-semibold text-text-primary">UGC Studio AI</span>
        </div>

        {/* New Video */}
        <div className="px-4 mb-5">
          <button
            onClick={handleNewVideo}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-white rounded-md text-label-md font-medium transition-all duration-150 hover:bg-primary-hover hover:scale-[1.02] active:scale-[0.98]"
          >
            <Plus className="w-4 h-4" />
            New Video
          </button>
        </div>

        {/* Conversations */}
        <div className="px-4 flex-1 overflow-y-auto no-scrollbar">
          <div className="text-label-sm uppercase text-text-tertiary tracking-wider mb-2 px-2">
            History
          </div>
          {loading && conversations.length === 0 ? (
            <div className="flex items-center gap-2 px-3 py-2 text-text-tertiary">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span className="text-body-md">Loading...</span>
            </div>
          ) : (
            <div className="space-y-0.5">
              {conversations.map((conv) => (
                <button
                  key={conv.chat_id}
                  onClick={() => handleConvClick(conv.chat_id)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-left transition-all duration-150 ${
                    activeChatId === conv.chat_id
                      ? 'bg-primary-light/30 text-primary border-l-[3px] border-primary'
                      : 'text-text-secondary hover:bg-white/[0.04] hover:text-text-primary'
                  }`}
                >
                  <MessageSquare className="w-4 h-4 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="text-body-md truncate">{conv.title || 'Untitled'}</div>
                    <div className="text-label-sm text-text-tertiary">
                      {conv.video_count} video{conv.video_count !== 1 ? 's' : ''} &middot; {formatDate(conv.updated_at)}
                    </div>
                  </div>
                </button>
              ))}
              {conversations.length === 0 && !loading && (
                <div className="px-3 py-6 text-body-md text-text-tertiary text-center">
                  No videos yet.
                  <br />
                  Create your first!
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
