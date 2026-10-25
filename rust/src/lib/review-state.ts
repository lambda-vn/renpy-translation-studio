// Where the user was on the review screen, kept for the lifetime of the
// window so a detour to Characters or Universe and back lands on the same
// file, page and filters (1.0.0 kept it in memory the same way). It belongs
// to one project: opening another resets it.

import { writable } from 'svelte/store';
import type { ListUnitsArgs } from './api';

export type StatusFilter =
	| 'all'
	| 'not_translated'
	| 'draft'
	| 'imported'
	| 'ai_suggested'
	| 'human_validated'
	| 'flagged'
	| 'errors';

export interface ReviewNav {
	/** Path of the project the rest belongs to. */
	projectPath: string;
	file: string;
	page: number;
	filter: StatusFilter;
	/** Speaker variable, '' for everybody. */
	speaker: string;
	search: string;
}

export const emptyNav = (projectPath = ''): ReviewNav => ({
	projectPath,
	file: '',
	page: 0,
	filter: 'all',
	speaker: '',
	search: ''
});

export const reviewNav = writable<ReviewNav>(emptyNav());

/** The five real statuses; the other filters are views over the lines. */
const REAL_STATUSES: readonly StatusFilter[] = [
	'not_translated',
	'draft',
	'imported',
	'ai_suggested',
	'human_validated'
];

/** The filter fields of `listUnits` / `countMatches` for a nav state. */
export function filterArgs(
	nav: Pick<ReviewNav, 'filter' | 'speaker' | 'search'>
): Required<Pick<ListUnitsArgs, 'status' | 'search' | 'speaker' | 'needsReview' | 'errorsOnly'>> {
	return {
		status: REAL_STATUSES.includes(nav.filter) ? nav.filter : null,
		search: nav.search,
		speaker: nav.speaker || null,
		needsReview: nav.filter === 'flagged',
		errorsOnly: nav.filter === 'errors'
	};
}

/** Does anything narrow the lines down (so the file panel can show matches)? */
export function isNarrowing(nav: Pick<ReviewNav, 'filter' | 'speaker' | 'search'>): boolean {
	return nav.filter !== 'all' || nav.speaker !== '' || nav.search.trim() !== '';
}
