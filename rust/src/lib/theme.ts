// Theme: the `theme` setting is "system" | "light" | "dark". The tokens only
// know light and dark, so the resolved value is written on <html> as
// `data-theme`; "system" is resolved here and follows the OS live.
//
//   setTheme(settings.theme)         // apply a value read from the settings
//   $themePreference                 // what the user chose
//   $resolvedTheme                   // what is actually drawn

import { derived, writable } from 'svelte/store';

export type ThemePreference = 'system' | 'light' | 'dark';
export type ResolvedTheme = 'light' | 'dark';

export const THEME_PREFERENCES: readonly ThemePreference[] = ['system', 'light', 'dark'];

export const themePreference = writable<ThemePreference>('system');

const systemDark = writable(false);

export const resolvedTheme = derived(
	[themePreference, systemDark],
	([$preference, $systemDark]): ResolvedTheme =>
		$preference === 'system' ? ($systemDark ? 'dark' : 'light') : $preference
);

/** Anything unknown (null, an old value, a typo) is "system". */
export function parseTheme(value: string | null | undefined): ThemePreference {
	return value === 'light' || value === 'dark' ? value : 'system';
}

/**
 * Switch theme immediately. This only changes the display: persisting the
 * choice is the settings dialog's job (`api.saveSettings`).
 */
export function setTheme(value: string | null | undefined): void {
	themePreference.set(parseTheme(value));
}

if (typeof window !== 'undefined') {
	const media = window.matchMedia('(prefers-color-scheme: dark)');
	systemDark.set(media.matches);
	media.addEventListener('change', (event) => systemDark.set(event.matches));
	resolvedTheme.subscribe((theme) => {
		document.documentElement.dataset.theme = theme;
	});
}
