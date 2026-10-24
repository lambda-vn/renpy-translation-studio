// UI strings. The catalogs are the ones the 1.x application ships
// (`src/locales/`), copied and extended, so a screen ported from Python
// keeps its wording in both languages. A key missing from the chosen
// language falls back on English, then on the key itself, so a missing
// string shows up as a visible identifier rather than as nothing.

import { derived, writable } from 'svelte/store';
import en from './locales/en.json';
import fr from './locales/fr.json';

interface Catalog {
	[key: string]: string | Catalog;
}

const catalogs: Record<string, Catalog> = { en, fr };

export const locale = writable<string>('en');

function lookup(catalog: Catalog | undefined, key: string): string | undefined {
	let node: string | Catalog | undefined = catalog;
	for (const part of key.split('.')) {
		if (node === undefined || typeof node === 'string') return undefined;
		node = node[part];
	}
	return typeof node === 'string' ? node : undefined;
}

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export function translate(
	language: string,
	key: string,
	params?: Record<string, string | number>
): string {
	const text = lookup(catalogs[language], key) ?? lookup(catalogs.en, key) ?? key;
	if (!params) return text;
	return text.replace(/\{(\w+)\}/g, (match, name: string) =>
		name in params ? String(params[name]) : match
	);
}

export const t = derived(locale, ($locale): Translate => (key, params) => translate($locale, key, params));
