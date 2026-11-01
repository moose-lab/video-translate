import { api } from "./client";
export type Page<T> = {items: T[]; total: number};
export type Project = {id: string; name: string; revision: number; status: string; source_language: string; target_languages: string[]; source_asset_id: string | null; source_track_index: number};
export const projectPath = (id: string) => `/projects/${encodeURIComponent(id)}`;
export const projectsApi = {
  list: (offset = 0, signal?: AbortSignal) => api<Page<Project>>(`/projects?limit=50&offset=${offset}`, {signal}),
  get: (id: string, signal?: AbortSignal) => api<Project>(projectPath(id), {signal}),
  create: (body: {name: string; source_language: string; target_languages: string[]}, csrf: string) => api<Project>("/projects", {method: "POST", body: JSON.stringify(body)}, csrf),
};
