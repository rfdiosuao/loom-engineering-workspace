import { configApi } from '../../services/api';
import type { StoryboardProject, StoryboardProjectsIndexEntry } from './storyboardTypes';

const PROJECTS_PATH = '.openclaw/nine-step/projects';
const INDEX_PATH = `${PROJECTS_PATH}/index.json`;
const BASE_PROJECTS_PATH = 'data/.openclaw/nine-step/projects';

function nowIso(): string {
  return new Date().toISOString();
}

export function newProjectId(): string {
  const rand = Math.random().toString(16).slice(2, 10);
  return `sb_${rand}`;
}

export function emptyProject(title = '未命名项目'): StoryboardProject {
  const now = nowIso();
  return {
    projectId: newProjectId(),
    title,
    createdAt: now,
    updatedAt: now,
    target: { category: '', object: '' },
    selections: {},
    script: { content: '' },
    storyboard: { shots: [] },
  };
}

export async function loadProjectsIndex(): Promise<StoryboardProjectsIndexEntry[]> {
  const { data } = await configApi.read(INDEX_PATH, []);
  return Array.isArray(data) ? (data as StoryboardProjectsIndexEntry[]) : [];
}

export async function saveProjectsIndex(entries: StoryboardProjectsIndexEntry[]): Promise<void> {
  await configApi.write(INDEX_PATH, entries);
}

export async function loadProject(projectId: string): Promise<StoryboardProject | null> {
  const { data } = await configApi.read(`${PROJECTS_PATH}/${projectId}.json`, null);
  return (data && typeof data === 'object') ? (data as StoryboardProject) : null;
}

export async function saveProject(project: StoryboardProject): Promise<void> {
  const updated = { ...project, updatedAt: nowIso() };
  await configApi.write(`${PROJECTS_PATH}/${updated.projectId}.json`, updated);
  const entries = await loadProjectsIndex();
  const without = entries.filter((entry) => entry.projectId !== updated.projectId);
  without.unshift({ projectId: updated.projectId, title: updated.title, updatedAt: updated.updatedAt });
  await saveProjectsIndex(without);
}

export async function deleteProject(projectId: string): Promise<void> {
  const entries = await loadProjectsIndex();
  await saveProjectsIndex(entries.filter((entry) => entry.projectId !== projectId));
  // Note: configApi has no delete; leave the JSON file in place, it is just unlisted.
}

// `BASE_PROJECTS_PATH` exported for contract tests; not used at runtime.
export { BASE_PROJECTS_PATH };
