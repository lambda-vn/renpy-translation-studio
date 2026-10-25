import { writable } from 'svelte/store';
import type { ProjectInfo } from './api';

// The project currently open, shared across routes so navigating away
// from review (to characters, universe, provider config...) and back
// doesn't require reopening it. Reset only by picking a different
// project from /setup.
export const project = writable<ProjectInfo | null>(null);

// True while a translation job runs. The review screen sets it; the step
// navigation and the tool navigation read it and refuse to leave review
// (the job's progress and cancel button live there).
export const jobRunning = writable(false);

// Asks for the settings dialog. The shell's gear button sets it to true; the
// dialog (not built yet) must set it back to false when it closes.
export const settingsOpen = writable(false);

// How many modal dialogs are open. A screen binding Esc ("clear the search")
// must do nothing while this is above zero: the dialog's own Esc handling
// runs after the screen's keydown listener.
export const modalDepth = writable(0);

export interface SkipLink {
	href: string;
	label: string;
}

// Extra "skip to..." links a screen wants before the header (review adds
// "Skip to the files"). The shell always provides "Skip to the content".
export const skipLinks = writable<SkipLink[]>([]);
