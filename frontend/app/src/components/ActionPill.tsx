import { type LucideIcon } from 'lucide-react';

interface ActionPillProps {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
}

export default function ActionPill({ icon: Icon, label, onClick }: ActionPillProps) {
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 px-5 py-2.5 rounded-pill glass-panel text-body-md text-text-primary transition-all duration-200 hover:glass-panel-heavy hover:border-glass-border-strong hover:shadow-glass active:scale-[0.97]"
    >
      <Icon className="w-4 h-4 text-text-secondary" />
      {label}
    </button>
  );
}
