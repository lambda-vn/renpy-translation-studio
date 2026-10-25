// Which destinations the shell lets the user reach right now.

export type BlockReason = 'no_project' | 'job';

export const ROUTES = {
	setup: '/',
	review: '/review',
	export: '/export',
	characters: '/characters',
	universe: '/universe',
	providers: '/provider-config'
} as const;

/** Routes that only make sense with a project open. */
const NEEDS_PROJECT = new Set<string>([
	ROUTES.review,
	ROUTES.export,
	ROUTES.characters,
	ROUTES.universe
]);

/** `/review/` and `/review` are the same page. */
export function normalizePath(pathname: string): string {
	return pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
}

/**
 * Why `href` can't be followed, or null when it can. While a translation job
 * runs only the review screen is reachable: its progress and Cancel button
 * live there.
 */
export function blockReason(
	href: string,
	state: { hasProject: boolean; jobRunning: boolean }
): BlockReason | null {
	if (NEEDS_PROJECT.has(href) && !state.hasProject) return 'no_project';
	if (state.jobRunning && href !== ROUTES.review) return 'job';
	return null;
}

export function blockMessageKey(reason: BlockReason): string {
	return reason === 'job' ? 'nav.unavailable_during_job' : 'nav.unavailable_no_project';
}
