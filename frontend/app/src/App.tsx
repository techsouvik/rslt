import { useState, useRef, useCallback, useEffect } from 'react';
import gsap from 'gsap';
import type { ScreenState } from '@/types';
import { useConversations } from '@/hooks/useConversations';
import { useChat } from '@/hooks/useChat';
import { useJobSSE } from '@/hooks/useJobSSE';
import BackgroundCanvas from '@/components/BackgroundCanvas';
import Sidebar from '@/components/Sidebar';
import BottomInputBar from '@/components/BottomInputBar';
import WelcomeScreen from '@/screens/WelcomeScreen';
import MainChatScreen from '@/screens/MainChatScreen';

export default function App() {
  const [screen, setScreen] = useState<ScreenState>('welcome');
  const [transitioning, setTransitioning] = useState(false);
  const [currentChatId, setCurrentChatId] = useState<string>('');
  const [currentJobId, setCurrentJobId] = useState<string>('');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const contentRef = useRef<HTMLDivElement>(null);

  // ── API Hooks ──────────────────────────────────────────────
  const { conversations, loading: convLoading, refresh: refreshConversations } = useConversations();
  const { sendMessage, loading: chatLoading, messages, loadHistory, setMessages } = useChat();
  const { progress: jobProgress, disconnect: disconnectSSE } = useJobSSE(
    currentJobId || null
  );

  // ── Watch for SSE completion ───────────────────────────────
  // When a job completes, we refresh conversations and clear the active jobId after a 1s delay
  useEffect(() => {
    if (jobProgress.status === 'COMPLETED' && currentJobId) {
      const timer = setTimeout(() => {
        refreshConversations();
        setCurrentJobId('');
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [jobProgress.status, currentJobId, refreshConversations]);

  // ── Screen Transition ──────────────────────────────────────
  const transitionTo = useCallback(
    (target: ScreenState) => {
      if (transitioning) return;
      setTransitioning(true);

      const el = contentRef.current;
      if (!el) {
        setScreen(target);
        setTransitioning(false);
        return;
      }

      gsap.to(el, {
        opacity: 0,
        y: target === 'welcome' ? 10 : -20,
        duration: 0.25,
        ease: 'power2.in',
        onComplete: () => {
          setScreen(target);
          requestAnimationFrame(() => {
            gsap.fromTo(
              el,
              { opacity: 0, y: 20 },
              {
                opacity: 1,
                y: 0,
                duration: 0.3,
                textShadow: 'none',
                ease: 'power2.out',
                onComplete: () => setTransitioning(false),
              }
            );
          });
        },
      });
    },
    [transitioning]
  );

  // ── Handle Submit ──────────────────────────────────────────
  const handleSubmit = useCallback(
    async (text: string) => {
      if (!text.trim() || transitioning) return;

      // Reuse the active chat ID or create a fresh one
      const activeId = currentChatId || `chat_${Date.now()}`;
      setCurrentChatId(activeId);
      setSidebarOpen(false);

      // If we are not on the welcome screen, transition to it
      if (screen !== 'welcome') {
        transitionTo('welcome');
      }

      const response = await sendMessage(text, activeId);
      
      if (response?.job_id) {
        // Set the active job ID to connect real-time SSE progress
        setCurrentJobId(response.job_id);
      }

      refreshConversations();
    },
    [transitioning, sendMessage, refreshConversations, transitionTo, currentChatId, screen]
  );

  const handlePromptSelect = useCallback(
    (prompt: string) => handleSubmit(prompt),
    [handleSubmit]
  );

  const handleNewVideo = useCallback(() => {
    disconnectSSE();
    setCurrentJobId('');
    setCurrentChatId('');
    setSidebarOpen(false);
    setMessages([]); // Reset messages so welcome prompt cards show up
    transitionTo('welcome');
  }, [disconnectSSE, transitionTo, setMessages]);

  const handleConversationClick = useCallback(
    (chatId: string) => {
      const conv = conversations.find((c) => c.chat_id === chatId);
      setCurrentChatId(chatId);
      loadHistory(chatId);
      
      if (conv) {
        // Find if there is an active, non-completed job to reconnect live SSE progress
        const activeJob = conv.videos.find(
          (v) => v.status !== 'COMPLETED' && v.status !== 'FAILED'
        );
        if (activeJob) {
          setCurrentJobId(activeJob.job_id);
        } else {
          setCurrentJobId('');
        }
      } else {
        setCurrentJobId('');
      }

      if (screen !== 'welcome') {
        transitionTo('welcome');
      }
    },
    [conversations, screen, transitionTo, loadHistory]
  );

  return (
    <div className="relative w-screen h-screen overflow-hidden font-inter bg-[#08090e]">
      {/* Background Canvas */}
      <BackgroundCanvas />

      {/* Sidebar — hidden by default, toggled via button */}
      <Sidebar
        onNewVideo={handleNewVideo}
        onConversationClick={handleConversationClick}
        conversations={conversations}
        loading={convLoading}
        activeChatId={currentChatId}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />

      {/* Main Content — always full width */}
      <main
        className="absolute inset-0 overflow-y-auto no-scrollbar z-10"
        style={{ paddingBottom: '140px' }}
      >
        <div ref={contentRef} className="min-h-full">
          {screen === 'welcome' && (
            messages.length > 0 ? (
              <MainChatScreen 
                messages={messages} 
                loading={chatLoading} 
                currentJobId={currentJobId}
                jobProgress={jobProgress}
              />
            ) : (
              <WelcomeScreen onPromptSelect={handlePromptSelect} />
            )
          )}
        </div>
      </main>

      {/* Bottom Input Bar */}
      <BottomInputBar onSubmit={handleSubmit} disabled={transitioning || chatLoading} />
    </div>
  );
}
