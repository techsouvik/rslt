export type ScreenState = 'welcome' | 'generating' | 'result';

export interface AgentStep {
  id: number;
  label: string;
  status: 'completed' | 'active' | 'pending';
}

export interface AgentInfo {
  id: string;
  name: string;
  quote: string;
}

export interface StatData {
  label: string;
  value: number;
  suffix: string;
  subtitle: string;
}

export interface PromptSuggestion {
  id: number;
  icon: string;
  title: string;
  description: string;
}
