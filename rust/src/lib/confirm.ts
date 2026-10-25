// Promise-based replacement for window.confirm:
//
//   if (await confirmDialog({ title: t('review.clear_title'), message: ..., danger: true })) { ... }
//
// <ConfirmHost> (rendered once in the layout) shows the requests one at a
// time. Esc, the close button and "Cancel" all resolve to false.

import { writable } from 'svelte/store';

export interface ConfirmOptions {
	title: string;
	message?: string;
	/** Defaults to "Confirm" (`common.confirm`). */
	confirmLabel?: string;
	/** Defaults to "Cancel" (`common.cancel`). */
	cancelLabel?: string;
	/** Red confirm button; initial focus then lands on Cancel. */
	danger?: boolean;
}

export interface ConfirmRequest extends ConfirmOptions {
	resolve: (confirmed: boolean) => void;
}

export const pendingConfirms = writable<ConfirmRequest[]>([]);

export function confirmDialog(options: ConfirmOptions): Promise<boolean> {
	return new Promise((resolve) => {
		pendingConfirms.update((queue) => [...queue, { ...options, resolve }]);
	});
}
