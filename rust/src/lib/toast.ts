// Ephemeral feedback for an action that just happened.
//
//   toast.success('51 lines filled from memory');
//   toast.error('Could not write tavern.rpy', { action: { label: 'Details', run: showDetails } });
//
// The <ToastHost> in the layout draws the list. Messages must already be
// localised (`$t(...)`).

import { writable } from 'svelte/store';

export type ToastKind = 'success' | 'info' | 'error';

export interface ToastAction {
	label: string;
	run: () => void;
}

export interface ToastItem {
	id: number;
	kind: ToastKind;
	message: string;
	action?: ToastAction;
	/** Milliseconds before auto-dismiss; 0 keeps it until dismissed. */
	duration: number;
}

export interface ToastOptions {
	action?: ToastAction;
	duration?: number;
}

// Mockup: 4 s. Errors and toasts carrying a button stay longer, since
// aiming at a button or reading a diagnosis takes more than 4 seconds.
const DEFAULT_DURATION = 4000;
const LONG_DURATION = 10000;

const MAX_VISIBLE = 4;

export const toasts = writable<ToastItem[]>([]);

let nextId = 1;

function push(kind: ToastKind, message: string, options: ToastOptions = {}): number {
	const id = nextId++;
	const duration =
		options.duration ??
		(kind === 'error' || options.action ? LONG_DURATION : DEFAULT_DURATION);
	toasts.update((list) =>
		[...list, { id, kind, message, action: options.action, duration }].slice(-MAX_VISIBLE)
	);
	return id;
}

export function dismissToast(id: number): void {
	toasts.update((list) => list.filter((item) => item.id !== id));
}

export const toast = {
	success: (message: string, options?: ToastOptions) => push('success', message, options),
	info: (message: string, options?: ToastOptions) => push('info', message, options),
	error: (message: string, options?: ToastOptions) => push('error', message, options),
	dismiss: dismissToast
};
