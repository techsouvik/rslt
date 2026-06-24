import { useRef, useEffect } from 'react';
import gsap from 'gsap';
import PromptCard from '@/components/PromptCard';

interface WelcomeScreenProps {
  onPromptSelect: (prompt: string) => void;
}

const promptSuggestions = [
  {
    id: 1,
    icon: 'sparkles' as const,
    title: "I'm building CalAI...",
    description: 'Generate an intro script for a productivity app.',
  },
  {
    id: 2,
    icon: 'target' as const,
    title: 'Create a marketing video...',
    description: 'Short-form vertical video for TikTok ads.',
  },
  {
    id: 3,
    icon: 'link' as const,
    title: 'https://calai.app',
    description: 'Fetch content and scripts from this landing page.',
  },
];

export default function WelcomeScreen({ onPromptSelect }: WelcomeScreenProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const ctx = gsap.context(() => {
      gsap.fromTo('.welcome-headline',
        { opacity: 0, y: 20 },
        { opacity: 1, y: 0, duration: 0.4, ease: 'power2.out' }
      );
      gsap.fromTo('.welcome-subtitle',
        { opacity: 0, y: 15 },
        { opacity: 1, y: 0, duration: 0.35, ease: 'power2.out', delay: 0.1 }
      );
      gsap.fromTo('.welcome-card',
        { opacity: 0, y: 20, scale: 0.96 },
        { opacity: 1, y: 0, scale: 1, duration: 0.35, ease: 'power2.out', stagger: 0.08, delay: 0.2 }
      );
    }, containerRef);
    return () => ctx.revert();
  }, []);

  return (
    <div ref={containerRef} className="flex flex-col items-center justify-center min-h-full py-12 px-4">
      <h1 className="welcome-headline text-display-xl text-text-primary text-center mb-4">
        Generate Viral UGC Videos
      </h1>
      <p className="welcome-subtitle text-body-lg text-text-secondary text-center max-w-[520px] mb-12">
        Paste a product URL or describe your startup to start creating high-converting social content.
      </p>

      <div className="flex flex-col sm:flex-row gap-4 items-stretch justify-center w-full max-w-[900px]">
        {promptSuggestions.map((prompt) => (
          <div key={prompt.id} className="welcome-card flex-1 flex justify-center">
            <PromptCard
              icon={prompt.icon}
              title={prompt.title}
              description={prompt.description}
              onClick={() => onPromptSelect(prompt.title)}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
