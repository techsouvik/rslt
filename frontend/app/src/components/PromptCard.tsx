import { Sparkles, Target, Link } from 'lucide-react';

interface PromptCardProps {
  icon: 'sparkles' | 'target' | 'link';
  title: string;
  description: string;
  onClick: () => void;
}

const iconMap = {
  sparkles: Sparkles,
  target: Target,
  link: Link,
};

export default function PromptCard({ icon, title, description, onClick }: PromptCardProps) {
  const Icon = iconMap[icon];

  return (
    <button
      onClick={onClick}
      className="group text-left w-full max-w-[280px] p-5 rounded-2xl glass-panel-light transition-all duration-200 ease-out hover:-translate-y-0.5 hover:scale-[1.02] hover:border-glass-border-strong hover:shadow-glass active:scale-[0.98]"
    >
      <div className="w-10 h-10 rounded-lg bg-primary-light/40 flex items-center justify-center mb-3 transition-colors duration-200 group-hover:bg-primary-light/60">
        <Icon className="w-5 h-5 text-primary" />
      </div>
      <h3 className="text-headline-md text-text-primary mb-2">{title}</h3>
      <p className="text-body-md text-text-secondary">{description}</p>
    </button>
  );
}
