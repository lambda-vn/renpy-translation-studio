import { writable } from 'svelte/store';
import type { ProjectInfo } from './api';

// The project currently open, shared across routes so navigating away
// from review (to characters, universe, provider config...) and back
// doesn't require reopening it. Reset only by picking a different
// project from /setup.
export const project = writable<ProjectInfo | null>(null);
