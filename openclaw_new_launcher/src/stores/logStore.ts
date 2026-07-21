import { create } from 'zustand';

interface LogState {
  lines: string;
  append: (text: string) => void;
  replace: (text: string) => void;
  clear: () => void;
}

function capLog(text: string): string {
  const maxLen = 100000;
  if (text.length <= maxLen) return text;
  const truncated = text.slice(-maxLen);
  const firstNewline = truncated.indexOf('\n');
  return firstNewline >= 0 ? truncated.slice(firstNewline + 1) : truncated;
}

export const useLogStore = create<LogState>((set) => ({
  lines: '',
  append: (text: string) => set((state) => {
    return { lines: capLog(state.lines + text) };
  }),
  replace: (text: string) => set({ lines: capLog(text) }),
  clear: () => set({ lines: '' }),
}));
