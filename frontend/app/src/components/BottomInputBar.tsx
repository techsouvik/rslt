import { useState, useRef } from 'react';
import { ArrowRight } from 'lucide-react';
import gsap from 'gsap';

interface BottomInputBarProps {
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

export default function BottomInputBar({ onSubmit, disabled }: BottomInputBarProps) {
  const [text, setText] = useState('');
  const [focused, setFocused] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const barRef = useRef<HTMLDivElement>(null);

  const handleSubmit = () => {
    if (!text.trim() || disabled) return;
    onSubmit(text.trim());
    setText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSendClick = () => {
    if (barRef.current) {
      gsap.to(barRef.current, {
        scale: 0.98,
        duration: 0.1,
        ease: 'power2.in',
        onComplete: () => {
          gsap.to(barRef.current, { scale: 1, duration: 0.15, ease: 'power2.out' });
        },
      });
    }
    handleSubmit();
  };

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 w-full max-w-[800px] px-4">
      <div
        ref={barRef}
        className={`flex items-center gap-2 px-2 py-2 rounded-pill transition-all duration-200 ${
          focused
            ? 'glass-panel-heavy shadow-[0_0_0_3px_rgba(37,99,235,0.2)] border-primary/40'
            : 'glass-panel-heavy'
        }`}
      >
        <input
          ref={inputRef}
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          onKeyDown={handleKeyDown}
          placeholder="Paste product URL or describe your video..."
          disabled={disabled}
          className="flex-1 pl-4 bg-transparent text-body-md text-text-primary placeholder:text-text-tertiary outline-none min-w-0"
        />
        <button
          onClick={handleSendClick}
          disabled={!text.trim() || disabled}
          className={`flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-full transition-all duration-150 ${
            text.trim() && !disabled
              ? 'bg-primary text-white hover:bg-primary-hover hover:scale-105 active:scale-95'
              : 'bg-white/[0.06] text-text-tertiary cursor-not-allowed'
          }`}
        >
          <ArrowRight className="w-5 h-5" />
        </button>
      </div>
      <p className="text-center text-label-sm uppercase text-text-tertiary tracking-wider mt-3 opacity-50">
        UGC Studio AI can make mistakes. Verify important information.
      </p>
    </div>
  );
}
