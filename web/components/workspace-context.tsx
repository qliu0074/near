'use client';
import {createContext, useContext} from 'react';
import type {Me} from '../lib/types';
import type {useActions} from '../hooks/use-actions';

export const WorkspaceContext = createContext<{me: Me; actions: ReturnType<typeof useActions>} | null>(null);
export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error('Workspace context is required');
  return context;
}
