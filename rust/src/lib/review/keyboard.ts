// The review screen's keyboard: one handler for the window, bound to the
// shortcut table of $lib/shortcuts. The page supplies what each shortcut does.
import { get } from 'svelte/store';
import { matches } from '$lib/shortcuts';
import { modalDepth, project } from '$lib/stores';

export interface ReviewKeyboardActions {
	/** Is there something typed in the search box, applied or not? */
	searching: () => boolean;
	clearSearch: () => void;
	focusSearch: () => void;
	save: () => void;
	/** The row holding the focus, if any. */
	currentRowId: () => string | undefined;
	spreadRow: (blockId: string) => void;
	validateRow: (blockId: string) => void;
	copySource: (blockId: string) => void;
	toggleFlag: (blockId: string) => void;
	moveRow: (delta: number) => void;
	stepFile: (delta: number) => void;
	stepPage: (delta: number) => void;
}

export function createReviewKeydown(actions: ReviewKeyboardActions): (event: KeyboardEvent) => void {
	return (event) => {
		if (!get(project) || get(modalDepth) > 0) return;

		if (matches('escape', event)) {
			if (actions.searching()) {
				event.preventDefault();
				actions.clearSearch();
			}
			return;
		}

		const rowId = actions.currentRowId();
		if (matches('search', event)) {
			event.preventDefault();
			actions.focusSearch();
		} else if (matches('save', event)) {
			event.preventDefault();
			actions.save();
		} else if (matches('spread_duplicates', event)) {
			event.preventDefault();
			if (rowId) actions.spreadRow(rowId);
		} else if (matches('validate', event)) {
			event.preventDefault();
			if (rowId) actions.validateRow(rowId);
		} else if (matches('copy_source', event)) {
			event.preventDefault();
			if (rowId) actions.copySource(rowId);
		} else if (matches('needs_review', event)) {
			event.preventDefault();
			if (rowId) actions.toggleFlag(rowId);
		} else if (matches('prev_row', event)) {
			event.preventDefault();
			actions.moveRow(-1);
		} else if (matches('next_row', event)) {
			event.preventDefault();
			actions.moveRow(1);
		} else if (matches('prev_file', event)) {
			event.preventDefault();
			actions.stepFile(-1);
		} else if (matches('next_file', event)) {
			event.preventDefault();
			actions.stepFile(1);
		} else if (matches('prev_page', event)) {
			event.preventDefault();
			actions.stepPage(-1);
		} else if (matches('next_page', event)) {
			event.preventDefault();
			actions.stepPage(1);
		}
	};
}
