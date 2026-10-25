// Display helpers for the language codes stored in a project (the names of
// the `tl/` folders: "english", "french", "schinese"...).

import type { Translate } from './i18n';

const ISO: Record<string, string> = {
	english: 'EN',
	english_us: 'EN',
	english_gb: 'EN',
	french: 'FR',
	german: 'DE',
	spanish: 'ES',
	italian: 'IT',
	portuguese: 'PT',
	brazilian: 'PT',
	dutch: 'NL',
	polish: 'PL',
	russian: 'RU',
	ukrainian: 'UK',
	turkish: 'TR',
	arabic: 'AR',
	japanese: 'JA',
	korean: 'KO',
	schinese: 'ZH',
	tchinese: 'ZH'
};

/** Two-letter label for an `<abbr>` ("french" -> "FR"); unknown codes keep their first two letters. */
export function languageShort(code: string): string {
	return ISO[code] ?? code.slice(0, 2).toUpperCase();
}

/** Full name in the interface language, for the `<abbr title>`. */
export function languageName(code: string, t: Translate): string {
	const key = `languages.${code}`;
	const name = t(key);
	return name === key ? code : name;
}
